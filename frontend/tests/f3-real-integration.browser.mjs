/** Opt-in real HTTP + DB integration. No route/response mocks. Uses independently persisted Worker
 * results; the approved deterministic Worker model adapter is not a real model-quality evaluation.
 * Intentionally excluded from the default *.test.mjs discovery. */
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { chromium } from "playwright";
const origin = process.env.F3_BROWSER_ORIGIN ?? "http://127.0.0.1:5178";
const url = new URL(origin);
assert.equal(process.env.F3_REAL_INTEGRATION, "synthetic-local-validation");
assert.equal(process.env.F3_VALIDATION_DATABASE, "f3_expansion_validation");
assert.ok(
  ["127.0.0.1", "localhost"].includes(url.hostname) &&
    url.protocol === "http:" &&
    url.port === "5178",
  "Only the dedicated loopback validation frontend is permitted.",
);
const browser = await chromium.launch();
const report = {
  origin,
  model:
    "approved deterministic Worker test adapter; no real model success claim",
  checks: [],
  requests: { runPosts: 0, feedbackPosts: 0, targetGets: 0, detailGets: 0 },
  pageErrors: [],
  consoleErrors: [],
  screenshots: [],
};
const date = new Date(Date.now() + 9 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10);
async function context() {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    reducedMotion: "reduce",
  });
  await ctx.addInitScript(
    (key) => localStorage.setItem("time-keeper.last-briefing", key),
    date,
  );
  return ctx;
}
async function login(page) {
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page
    .getByRole("button", { name: "개발용 세션으로 로그인", exact: true })
    .click();
  await page.getByRole("button", { name: "교차 판정", exact: true }).waitFor();
  const me = await page.request.get(`${origin}/api/v1/auth/me`);
  assert.equal(me.status(), 200);
  assert.equal(
    (await me.json()).user.login_id,
    "f3_synthetic_dev",
    "Only the dedicated synthetic user is permitted.",
  );
  const source = await page.evaluate(async () => {
    const { APP_ENV } = await import("/src/config/env.ts");
    return { f3: APP_ENV.f3Source, ledger: APP_ENV.ledgerSource };
  });
  assert.deepEqual(source, { f3: "api", ledger: "api" });
}
async function get(page, path) {
  const r = await page.request.get(`${origin}/api/v1${path}`);
  assert.equal(r.status(), 200, path);
  assert.equal(r.headers()["cache-control"], "no-store");
  return r.json();
}
let activePage;
try {
  const ctx = await context();
  const page = await ctx.newPage();
  activePage = page;
  page.on("pageerror", (e) => report.pageErrors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") report.consoleErrors.push(m.text());
  });
  page.on("request", (r) => {
    const path = new URL(r.url()).pathname;
    const method = r.method();
    if (path === "/api/v1/f3/runs" && method === "POST")
      report.requests.runPosts++;
    if (path === "/api/v1/f3/feedback" && method === "POST")
      report.requests.feedbackPosts++;
    if (path.includes("/f3/judgment-targets/") && method === "GET")
      report.requests.targetGets++;
    if (/\/f3\/judgment-results\/\d+$/.test(path) && method === "GET")
      report.requests.detailGets++;
  });
  await login(page);
  const listings = await get(
    page,
    "/f3/judgment-results?anchor_type=LISTING&filter=ALL",
  );
  const buyers = await get(
    page,
    "/f3/judgment-results?anchor_type=REQUIREMENT&filter=ALL",
  );
  const listing = listings.items.find((x) => x.anchor.anchor_id === 2);
  const buyer = buyers.items.find((x) => x.anchor.anchor_id === 1);
  assert.ok(listing?.result_id && buyer?.result_id);
  assert.equal(listing.freshness, "CURRENT");
  assert.equal(buyer.freshness, "CURRENT");
  report.checks.push({
    name: "persisted_both_directions",
    listingResult: listing.result_id,
    buyerResult: buyer.result_id,
  });
  await page.getByRole("button", { name: "교차 판정", exact: true }).click();
  const region = page.getByRole("region", {
    name: "교차 판정 업무 목록",
    exact: true,
  });
  await region.locator("#f3-result-filter").selectOption("ALL");
  await region
    .getByRole("button", {
      name: `${listing.anchor.display_name} 결과 보기`,
      exact: true,
    })
    .click();
  const detail = region.getByRole("region", {
    name: "교차 판정 결과 상세",
    exact: true,
  });
  await detail.locator(".f3-judgments__candidate").waitFor();
  assert.match(await detail.innerText(), /조건 후보 3 · AI 판정 3/);
  const snapshot = await get(page, `/f3/judgment-results/${listing.result_id}`);
  assert.equal(snapshot.candidates.length, 3);
  assert.equal(
    await detail
      .getByText("기준 포지션 카드 펼치기", { exact: true })
      .locator("..")
      .getAttribute("open"),
    null,
  );
  await detail.getByText("기준 포지션 카드 펼치기", { exact: true }).click();
  await detail.getByText("후보 포지션 카드 펼치기", { exact: true }).click();
  report.checks.push({
    name: "drawer_candidates_cards",
    candidates: snapshot.candidates.length,
  });
  for (let i = 0; i < 10; i++) {
    const response = page.waitForResponse(
      (r) =>
        /\/f3\/judgment-results\/\d+(?:\?|$)/.test(r.url()) &&
        r.request().method() === "GET" &&
        r.status() === 200,
    );
    await detail
      .getByRole("button", { name: "결과 새로고침", exact: true })
      .click();
    await response;
    await page.waitForFunction(() =>
      [...document.querySelectorAll("button")].some(
        (b) => b.textContent === "결과 새로고침" && !b.disabled,
      ),
    );
  }
  assert.equal(report.requests.runPosts, 0);
  report.checks.push({
    name: "ten_get_refreshes_zero_run_posts",
    refreshes: 10,
    runPosts: report.requests.runPosts,
  });
  const selected = await detail
    .locator(".f3-judgments__candidate h3")
    .innerText();
  await detail
    .getByRole("button", { name: "기준 장부 열기", exact: true })
    .click();
  await page.locator("#detail-log").waitFor();
  await page.getByRole("button", { name: "상세 닫기", exact: true }).click();
  await detail.locator(".f3-judgments__candidate").waitFor();
  assert.equal(await region.locator("#f3-result-filter").inputValue(), "ALL");
  assert.equal(
    await detail.locator(".f3-judgments__candidate h3").innerText(),
    selected,
  );
  report.checks.push({ name: "ledger_return_restores_filter_selection" });
  const original = detail.getByRole("button", { name: /^원본 상담 #/ }).first();
  if (await original.count()) {
    await original.click();
    const modal = page.getByRole("dialog", {
      name: "판정 근거 원본 상담",
      exact: true,
    });
    await modal.waitFor();
    await modal.getByText("대상 일반 상담", { exact: false }).waitFor();
    await modal
      .getByRole("button", { name: "목록으로 돌아가기", exact: true })
      .click();
    await detail.locator(".f3-judgments__candidate").waitFor();
    report.checks.push({ name: "exact_original_consultation_and_return" });
  } else
    report.checks.push({
      name: "original_consultation",
      available: false,
      reason: "Persisted deterministic result contains no quoted interaction.",
    });
  await detail
    .getByRole("button", { name: "관심없음 기록", exact: true })
    .click();
  const modal = page.getByRole("dialog", {
    name: "관심없음 사유",
    exact: true,
  });
  await modal.locator("#f3-feedback-reason").selectOption("ALREADY_CONTACTED");
  const pendingFeedback = page.waitForResponse(
    (r) => r.url().endsWith("/f3/feedback") && r.request().method() === "POST",
  );
  await modal.getByRole("button", { name: "피드백 기록", exact: true }).click();
  const feedback = await pendingFeedback;
  assert.equal(feedback.status(), 201);
  await modal.waitFor({ state: "hidden" });
  const saved = await get(
    page,
    `/f3/judgment-results/${listing.result_id}?candidate_id=${snapshot.selected_candidate.candidate_id}`,
  );
  assert.ok(
    saved.selected_candidate.recent_records.some(
      (r) =>
        r.record_type === "FEEDBACK" &&
        r.reason === "ALREADY_CONTACTED" &&
        r.scope === "PAIR",
    ),
  );
  report.checks.push({
    name: "feedback_persisted_real_database",
    feedbackPosts: report.requests.feedbackPosts,
  });
  await page.evaluate(() => {
    document.querySelector(".f3-judgments").scrollTop = 0;
    document.querySelector(".pf-v6-c-drawer__panel").scrollTop = 0;
  });
  await page.screenshot({
    path: "/tmp/f3-integration-final.png",
    fullPage: true,
  });
  report.screenshots.push("/tmp/f3-integration-final.png");
  await region
    .getByRole("button", { name: "결과 상세 닫기", exact: true })
    .click();
  await region.getByRole("tab", { name: "손님 기준", exact: true }).click();
  await region
    .getByRole("button", {
      name: `${buyer.anchor.display_name} 결과 보기`,
      exact: true,
    })
    .click();
  await detail.locator(".f3-judgments__candidate").waitFor();
  assert.match(await detail.innerText(), /조건 후보 2 · AI 판정 2/);
  report.checks.push({ name: "buyer_direction_actual_result" });
  const link = page.url();
  const other = await context();
  const restored = await other.newPage();
  await login(restored);
  await restored.goto(link);
  await restored
    .getByRole("region", { name: "교차 판정 결과 상세", exact: true })
    .locator(".f3-judgments__candidate")
    .waitFor();
  const current = await get(restored, "/f3/judgment-targets/REQUIREMENT/1");
  assert.equal(current.result_id, buyer.result_id);
  report.checks.push({
    name: "independent_context_restores_database_result",
    result: current.result_id,
  });
  await other.close();
  await page.setViewportSize({ width: 390, height: 844 });
  await detail.locator(".f3-judgments__candidate").waitFor();
  await page.evaluate(() => {
    document.querySelector(".f3-judgments").scrollTop = 0;
    document.querySelector(".pf-v6-c-drawer__panel").scrollTop = 0;
  });
  const closeBox = await region
    .getByRole("button", { name: "결과 상세 닫기", exact: true })
    .boundingBox();
  assert.ok(
    closeBox &&
      closeBox.y >= 48 &&
      closeBox.y + closeBox.height <= 844 &&
      closeBox.x >= 0 &&
      closeBox.x + closeBox.width <= 390,
    "Mobile drawer close action must be in the viewport",
  );
  const overflow = await page.evaluate(() => ({
    width: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
      panelWidth: document.querySelector('.pf-v6-c-drawer__panel').clientWidth,
      panelContentWidth: document.querySelector('.pf-v6-c-drawer__panel').scrollWidth,
  }));
  await page.screenshot({
    path: "/tmp/f3-integration-mobile.png",
    fullPage: true,
  });
  report.screenshots.push("/tmp/f3-integration-mobile.png");
  report.checks.push({ name: "mobile", ...overflow });
  assert.ok(overflow.panelContentWidth <= overflow.panelWidth + 1, 'Mobile result content must fit the panel');
  assert.ok(
    overflow.documentWidth <= overflow.width + 1,
    "Mobile horizontal overflow",
  );
  assert.equal(report.requests.runPosts, 0);
  assert.deepEqual(report.pageErrors, []);
  report.unexpectedConsoleErrors = report.consoleErrors.filter(
    (m) => !/401 \(Unauthorized\)/.test(m),
  );
  assert.deepEqual(report.unexpectedConsoleErrors, []);
  await ctx.close();
} catch (error) {
  if (activePage)
    await activePage
      .screenshot({ path: "/tmp/f3-integration-failure.png", fullPage: true })
      .catch(() => {});
  report.failure = error instanceof Error ? error.message : String(error);
  throw error;
} finally {
  await writeFile(
    "/tmp/f3-real-integration-report.json",
    JSON.stringify(report, null, 2),
  );
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
}
