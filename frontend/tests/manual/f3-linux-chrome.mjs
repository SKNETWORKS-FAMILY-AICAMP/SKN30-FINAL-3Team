/** Explicit manual-run verification against local synthetic ledgers; F3 uses a transport double. */
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

const baseUrl = process.env.F3_CHROME_URL ?? "http://localhost:5183/";
const beforeUrl = process.env.F3_CHROME_BASELINE_URL ?? "http://localhost:5184/";
const output = process.env.F3_CHROME_OUTPUT ?? "/tmp/f3-linux-chrome-validation";
for (const url of [baseUrl, beforeUrl]) {
  assert.ok(["localhost", "127.0.0.1"].includes(new URL(url).hostname), "local fixture only");
}
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "f3-chrome-"));
const context = await chromium.launchPersistentContext(profile, {
  channel: "chrome", headless: false, viewport: null, args: ["--disable-gpu"],
});
const page = context.pages()[0];
const settings = await context.newPage();
await settings.goto("chrome://settings/appearance");
await settings.locator("#zoomLevel").waitFor();
const report = { browser: await page.evaluate(() => navigator.userAgent), mode: "headed", cases: [], errors: [] };
page.on("pageerror", error => report.errors.push(error.message));
await page.emulateMedia({ reducedMotion: "reduce" });
await page.addInitScript(() => localStorage.setItem("time-keeper.last-briefing", new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10)));
const cdp = await context.newCDPSession(page);
const { windowId } = await cdp.send("Browser.getWindowForTarget");

async function geometry(width, height, zoom) {
  await settings.locator("#zoomLevel").selectOption(String(zoom));
  await cdp.send("Browser.setWindowBounds", { windowId, bounds: { width, height, windowState: "normal" } });
  await page.bringToFront();
  await page.waitForTimeout(400);
  const actual = await page.evaluate(() => ({ outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight], dpr: devicePixelRatio }));
  assert.ok(Math.abs(actual.dpr - zoom) < 0.01, `native browser zoom: ${JSON.stringify(actual)}`);
  return { requested: [width, height], zoom, ...actual };
}
async function open(kind, revision = "after", phase = "COMPLETED") {
  await page.goto(revision === "before" ? beforeUrl : baseUrl);
  const login = page.getByRole("button", { name: "개발용 세션으로 로그인" });
  await login.or(page.getByRole("button", { name: "매물장", exact: true })).first().waitFor();
  if (await login.isVisible()) await login.click();
  await page.getByRole("button", { name: "매물장", exact: true }).waitFor();
  await page.evaluate(async phase => {
    const { f3Transport } = await import("/src/features/f3/api/f3Transport.ts");
    const { runPayload, statusPayload, resultPayload } = await import("/src/features/f3/mock/scenario.ts");
    const { decodeRun, decodeRunStatus, decodeRunResult } = await import("/src/features/f3/model/decode.ts");
    const { ApiError } = await import("/src/shared/api/index.ts");
    const control = window.chromeF3 = { phase, writes: 0, statusGets: 0, resultGets: 0, failure: "", empty: false, long: false, lastResultStatus: "" };
    let run;
    f3Transport.createRun = async anchor => {
      control.writes++;
      run = { runId: 9000 + control.writes, anchorType: anchor.anchorType, anchorId: anchor.anchorId, createdAt: Date.UTC(2026, 8, 10) };
      return decodeRun(runPayload(run, control.phase));
    };
    f3Transport.getRunStatus = async () => {
      control.statusGets++;
      if (control.failure === "notFound") throw new ApiError({ kind: "notFound", status: 404, message: "합성 실행 없음" });
      return decodeRunStatus(statusPayload(run, control.phase));
    };
    f3Transport.getRunResult = async (_id, requestedPage) => {
      control.resultGets++;
      if (control.failure === "network") throw new ApiError({ kind: "network", message: "합성 연결 오류" });
      const result = resultPayload(run, control.phase, requestedPage);
      if (control.empty) { result.candidates = []; result.candidates_total = 0; result.candidate_selection = { ...result.candidate_selection, total_count: 0, carded_count: 0, remaining_count: 0 }; }
      if (control.long && result.candidates[0]) result.candidates[0].evaluation_basis = "긴 조건과 상담 근거를 줄바꿈으로 확인합니다. ".repeat(30) + "LONG_UNBROKEN_".repeat(20);
      control.lastResultStatus = control.phase;
      return decodeRunResult(result);
    };
  }, phase);
  await page.getByRole("button", { name: kind === "listing" ? "매물장" : "구입장", exact: true }).click();
  await page.locator(kind === "listing" ? '.ag-row[row-id="5"] .ledger-grid__detail-link' : '.buyer-ledger-grid .ag-row[row-id="1"] [col-id="buyer"]').click();
  const trigger = page.getByRole("button", { name: kind === "listing" ? "교차 판정 실행" : "교차 판정", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await page.locator("#cross-match-panel").waitFor();
  await page.waitForFunction(() => window.chromeF3.resultGets > 0);
  await page.waitForTimeout(150);
  return trigger;
}
async function screenshot(name) {
  await page.locator("#cross-match-panel").scrollIntoViewIfNeeded();
  const shot = await cdp.send("Page.captureScreenshot", { captureBeyondViewport: false });
  await writeFile(join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
}
async function snapshot() {
  return page.locator("#cross-match-panel").evaluate(root => ({
    width: root.getBoundingClientRect().width,
    clientWidth: root.clientWidth, scrollWidth: root.scrollWidth,
    styles: [root, ...root.querySelectorAll("h3, h4, .cross-match-panel__candidate, .cross-match-panel__state-card")].map(el => {
      const css = getComputedStyle(el);
      return { tag: el.tagName, font: css.font, color: css.color, background: css.backgroundColor, padding: css.padding, gap: css.gap, borderRadius: css.borderRadius };
    }),
  }));
}
async function reachable(locator) {
  await locator.focus();
  await page.waitForTimeout(80);
  return locator.evaluate(el => {
    const r = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(innerWidth - 1, r.x + r.width / 2));
    const y = Math.max(0, Math.min(innerHeight - 1, r.y + r.height / 2));
    const hit = document.elementFromPoint(x, y);
    return { focused: document.activeElement === el, visible: r.width > 0 && r.height > 0 && r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth, uncovered: hit === el || el.contains(hit) };
  });
}
try {
  // Compare identical completed synthetic results in baseline and revised product UI.
  for (const kind of ["listing", "requirement"]) {
    for (const [width, height, zoom] of [[1920, 1080, 1], [1366, 768, 1], [1920, 1080, 2], [1366, 768, 2]]) {
      const results = {};
      for (const revision of ["before", "after"]) {
        await geometry(width, height, zoom);
        const trigger = await open(kind, revision);
        const actual = await geometry(width, height, zoom);
        await screenshot(`${revision}-${kind}-${width}-${zoom * 100}`);
        results[revision] = await snapshot();
        if (revision === "after") {
          const next = page.getByRole("button", { name: "다음", exact: true });
          const nextAccess = await reachable(next);
          await page.keyboard.press("Enter");
          await page.getByText("21–23 / 23", { exact: true }).waitFor();
          await page.getByRole("button", { name: "이전", exact: true }).click();
          await page.getByText("1–20 / 23", { exact: true }).waitFor();
          const close = page.getByRole("button", { name: "교차 판정 Panel 닫기" });
          const closeAccess = await reachable(close);
          await page.keyboard.press("Enter");
          await page.locator("#cross-match-panel").waitFor({ state: "hidden" });
          await page.waitForTimeout(100);
          const focusRestored = await trigger.evaluate(el => document.activeElement === el);
          assert.equal(focusRestored, true, "panel close must restore its trigger");
          await trigger.click();
          await page.locator("#cross-match-panel").waitFor();
          assert.equal(await page.evaluate(() => window.chromeF3.writes), 1);
          report.cases.push({ kind, ...actual, nextAccess, closeAccess, focusRestored, reopenPostCount: 1 });
        }
      }
      const equal = JSON.stringify(results.before) === JSON.stringify(results.after);
      report.cases.at(-1).baselineStylesAndWidthEqual = equal;
      report.cases.at(-1).panelHorizontalOverflow = results.after.scrollWidth > results.after.clientWidth + 1;
      if (!equal) report.cases.at(-1).styleDifference = results;
      await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2));
    }
  }
  await geometry(1366, 768, 1);
  for (const phase of ["QUEUED", "RUNNING", "ANCHOR_READY", "CANDIDATES_READY", "CANDIDATE_CARDS_READY", "JUDGING", "FAILED_TERMINAL"]) {
    await open("listing", "after", phase);
    await screenshot(`state-${phase}`);
    const memo = page.locator("#detail-memo");
    const original = await memo.inputValue();
    await memo.fill(`${original} 합성 편집 확인`);
    assert.equal(await memo.inputValue(), `${original} 합성 편집 확인`);
    await memo.fill(original);
    report.cases.push({ phase, editableDuringJudgment: true });
  }
  // Real product panel with deterministic transport fault/long-running double.
  await page.clock.install();
  for (const scenario of ["paused", "network", "notFound", "empty", "long"]) {
    const trigger = await open("listing", "after", scenario === "paused" ? "JUDGING" : "COMPLETED");
    if (scenario === "paused") {
      await page.clock.runFor(66000);
      assert.equal(await page.getByRole("button", { name: "다시 확인", exact: true }).count(), 0);
      await page.clock.runFor(240000);
      await page.getByRole("button", { name: "다시 확인", exact: true }).waitFor();
    } else {
      await page.getByRole("button", { name: "교차 판정 Panel 닫기" }).click();
      await page.evaluate(s => {
        if (["network", "notFound"].includes(s)) window.chromeF3.failure = s;
        else window.chromeF3[s] = true;
      }, scenario);
      await trigger.click();
      if (["network", "notFound"].includes(scenario)) await page.getByRole("button", { name: scenario === "notFound" ? "판정 다시 시도" : "다시 확인", exact: true }).waitFor();
      else await page.waitForTimeout(150);
    }
    await screenshot(`state-${scenario}`);
    if (["paused", "network", "notFound"].includes(scenario)) {
      const retry = page.getByRole("button", { name: scenario === "notFound" ? "판정 다시 시도" : "다시 확인", exact: true });
      const access = await reachable(retry);
      await page.evaluate(() => Object.assign(window.chromeF3, { failure: "", phase: "COMPLETED" }));
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => window.chromeF3.lastResultStatus === "COMPLETED");
      await page.waitForTimeout(100);
      const expected = scenario === "notFound" ? 2 : 1;
      assert.equal(await page.evaluate(() => window.chromeF3.writes), expected);
      report.cases.push({ scenario, retryAccess: access, postCount: expected });
    } else report.cases.push({ scenario, panel: await snapshot() });
  }
} catch (error) {
  report.failure = error.stack;
  await page.screenshot({ path: join(output, "failure.png") }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2));
  await context.close();
  console.log(JSON.stringify({ cases: report.cases.length, failure: report.failure, errors: report.errors }));
}
