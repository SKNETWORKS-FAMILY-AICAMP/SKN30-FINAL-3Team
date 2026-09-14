/** Linux Chrome 자체 배율로 현재 HEAD와 작업 트리의 근거 표시를 비교한다. API·DB 불필요. */
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { openEvidencePanel } from "../helpers/f3-evidence.mjs";

const frontend = process.cwd();
const output = resolve(process.env.F3_EVIDENCE_OUTPUT ?? "../docs/validation/f3-evidence-korean-2026-09-10");
const scratch = await mkdtemp(join(tmpdir(), "f3-evidence-chrome-"));
const children = [];
let context;
const report = { baseline: process.env.F3_EVIDENCE_BASELINE ?? "HEAD", cases: [], errors: [] };
async function serve(cwd) {
  const vite = pathToFileURL(join(frontend, "node_modules/vite/dist/node/index.js")).href;
  const runner = `import { createServer } from ${JSON.stringify(vite)};
    const server = await createServer({ cacheDir: process.env.F3_EVIDENCE_CACHE,
      server: { host: "127.0.0.1", port: 0 } });
    await server.listen(); server.printUrls();`;
  const child = spawn(process.execPath, ["--input-type=module", "-e", runner], {
    cwd, env: { ...process.env, VITE_LEDGER_SOURCE: "mock", VITE_F3_SOURCE: "mock",
      F3_EVIDENCE_CACHE: join(scratch, `vite-cache-${children.length}`),
      VITE_AUTH_DEVELOPMENT_ENABLED: "true", VITE_MOCK_LATENCY_MS: "0", VITE_MOCK_ROW_COUNT: "40",
      VITE_API_BASE_URL: "/api/v1", FRONTEND_BACKEND_ORIGIN: "http://127.0.0.1:8013" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  return new Promise((resolveUrl, reject) => {
    const timer = setTimeout(() => reject(new Error("Vite startup timeout")), 30000);
    let output = "";
    const read = data => {
      output += String(data).replace(/\x1b\[[0-9;]*m/g, "");
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if (match) { clearTimeout(timer); resolveUrl(match[0]); }
    };
    child.stdout.on("data", read); child.stderr.on("data", read);
    child.on("exit", code => { clearTimeout(timer); reject(new Error(`Vite ${code}: ${output}`)); });
  });
}
try {
  await mkdir(output, { recursive: true });
  const baseline = join(scratch, "baseline");
  await mkdir(baseline);
  const archive = execFileSync("git", ["archive", report.baseline, "frontend"], { cwd: resolve(frontend, ".."), maxBuffer: 30 * 1024 * 1024 });
  execFileSync("tar", ["-x", "-C", baseline], { input: archive });
  await symlink(join(frontend, "node_modules"), join(baseline, "frontend/node_modules"));
  const urls = { before: await serve(join(baseline, "frontend")), after: await serve(frontend) };
  context = await chromium.launchPersistentContext(join(scratch, "profile"), {
    channel: "chrome", headless: false, viewport: null, args: ["--disable-gpu"],
  });
  const page = context.pages()[0];
  const settings = await context.newPage();
  await settings.goto("chrome://settings/appearance");
  await settings.locator("#zoomLevel").waitFor();
  report.browser = await page.evaluate(() => navigator.userAgent);
  page.on("pageerror", error => report.errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  const cdp = await context.newCDPSession(page);
  const { windowId } = await cdp.send("Browser.getWindowForTarget");
  for (const [width, height] of [[1920, 1080], [1366, 768]]) {
    for (const zoom of [1, 2]) {
      await settings.locator("#zoomLevel").selectOption(String(zoom));
      await cdp.send("Browser.setWindowBounds", { windowId, bounds: { width, height, windowState: "normal" } });
      await page.bringToFront();
      for (const kind of ["listing", "requirement"]) {
        for (const revision of ["before", "after"]) {
          const opener = await openEvidencePanel(page, urls[revision], kind);
          const panel = page.locator("#cross-match-panel");
          const firstLabel = panel.locator(".cross-match-panel__evidence-field").first();
          await firstLabel.evaluate(el => el.scrollIntoView({ block: "center", behavior: "instant" }));
          await page.waitForTimeout(400);
          const labels = await panel.locator(".cross-match-panel__evidence-field").allTextContents();
          const geometry = await page.evaluate(() => ({ outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight], dpr: devicePixelRatio }));
          assert.equal(geometry.dpr, zoom);
          if (revision === "after") {
            assert.deepEqual(labels, ["확정 기한", "일정 조건", "제시 금액", "판정 근거"]);
            assert.doesNotMatch(await panel.innerText(), /timing|hard_deadline|stated_amount|future\.internal_key/);
          } else assert.equal(labels[0], "timing.hard_deadline");
          const overflow = await panel.locator(".cross-match-panel__evidence").evaluate(el => el.scrollWidth > el.clientWidth);
          assert.equal(overflow, false);
          const fieldUncovered = await firstLabel.evaluate(el => {
            const rect = el.getBoundingClientRect();
            return el.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
          });
          const name = `${kind}-${width}-${zoom * 100}-${revision}`;
          const shot = await cdp.send("Page.captureScreenshot", { captureBeyondViewport: false });
          await writeFile(join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
          await panel.getByRole("button", { name: "교차 판정 Panel 닫기" }).focus();
          await page.keyboard.press("Enter");
          await panel.waitFor({ state: "hidden" });
          await page.waitForFunction(() => document.activeElement?.textContent?.trim().startsWith("교차 판정"));
          assert.equal(await opener.evaluate(el => el === document.activeElement), true);
          assert.equal(await page.evaluate(() => window.evidenceSubmissions), 1);
          report.cases.push({ name, requested: [width, height], zoom, ...geometry, labels, overflow, fieldUncovered, focusRestored: true });
          console.log(`PASS ${name}`);
        }
      }
    }
  }
  assert.deepEqual(report.errors, []);
} finally {
  await context?.close();
  for (const child of children) {
    if (child.exitCode == null) {
      const stopped = new Promise(resolveExit => child.once("exit", resolveExit));
      child.kill(); await stopped;
    }
  }
  await rm(scratch, { recursive: true, force: true });
  await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2));
}
