/**
 * Opt-in real-browser reads of the existing local database's F3 synthetic seed.
 * No HTTP routes/responses are mocked. Only development-session creation mutates state.
 * Run after applying the seed to the configured local API; this script never seeds or resets DBs.
 * Kept outside *.test.mjs discovery, independently of the disposable-database integration script.
 */
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { chromium } from "playwright";

assert.equal(process.env.F3_SEED_INTEGRATION, "existing-local-synthetic-seed");
assert.equal(process.env.F3_SEED_LOGIN_ID, "f3_synthetic_dev");
const origin = process.env.F3_BROWSER_ORIGIN ?? "http://127.0.0.1:5178";
const url = new URL(origin);
assert.ok(
  ["127.0.0.1", "localhost"].includes(url.hostname) &&
    url.protocol === "http:" && url.port === "5178",
  "Only the dedicated loopback frontend is permitted.",
);
const browser = await chromium.launch();
const report = {
  model: "Persisted deterministic seed examples; not real model inference.",
  checks: [], requests: { runPosts: 0, feedbackPosts: 0, unexpectedWrites: 0, resultGets: 0 },
  pageErrors: [], consoleErrors: [], screenshots: [],
};
let page;
const date = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
async function get(path) {
  const response = await page.request.get(`${origin}/api/v1${path}`);
  assert.equal(response.status(), 200, path);
  assert.equal(response.headers()["cache-control"], "no-store", path);
  return response.json();
}
async function list(type) {
  const items = []; let cursor; let pages = 0;
  do {
    const params = new URLSearchParams({ anchor_type: type, filter: "ALL", limit: "100" });
    if (cursor) params.set("cursor", cursor);
    const result = await get(`/f3/judgment-results?${params}`);
    items.push(...result.items); cursor = result.next_cursor; pages++;
    assert.ok(pages <= 10, "Synthetic seed lookup must remain bounded.");
  } while (cursor);
  return items;
}
function available(target) {
  return target.is_synthetic_fixture === true && target.freshness === "CURRENT" &&
    target.content_availability === "AVAILABLE" && target.result_id != null && target.summary != null;
}
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: "reduce" });
  await context.addInitScript(key => localStorage.setItem("time-keeper.last-briefing", key), date);
  page = await context.newPage();
  page.setDefaultTimeout(20_000);
  page.on("pageerror", error => report.pageErrors.push(error.message));
  page.on("console", message => { if (message.type() === "error") report.consoleErrors.push(message.text()); });
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path === "/api/v1/f3/runs") report.requests.runPosts++;
    if (request.method() === "POST" && path === "/api/v1/f3/feedback") report.requests.feedbackPosts++;
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method()) &&
      path.startsWith("/api/") && path !== "/api/v1/auth/development-session") report.requests.unexpectedWrites++;
    if (request.method() === "GET" && /\/f3\/judgment-results\/\d+$/.test(path)) report.requests.resultGets++;
  });
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "개발용 세션으로 로그인", exact: true }).click();
  await page.getByRole("button", { name: "교차 판정", exact: true }).waitFor();
  const session = await get("/auth/me");
  assert.equal(session.user.login_id, "f3_synthetic_dev", "Stop before opening business views for any other user.");
  assert.equal(session.user.brokerage_id, 2, "Only the existing local synthetic brokerage is permitted.");
  report.checks.push({ name: "seed_session", loginId: session.user.login_id, brokerageId: session.user.brokerage_id });
  const sources = await page.evaluate(async () => {
    const { APP_ENV } = await import("/src/config/env.ts");
    return { f3: APP_ENV.f3Source, ledger: APP_ENV.ledgerSource };
  });
  assert.deepEqual(sources, { f3: "api", ledger: "api" });
  const listings = await list("LISTING"); const buyers = await list("REQUIREMENT");
  const listing = listings.find(item => available(item) && item.summary.judged_count > 0);
  const buyer = buyers.find(item => available(item) && item.summary.judged_count > 0);
  const noCandidates = [...listings, ...buyers].find(item => available(item) && item.summary.total_count === 0);
  const unjudged = [...listings, ...buyers].find(item => available(item) && item.summary.unjudged_count > 0);
  assert.ok(listing && buyer && noCandidates && unjudged, "The seed must provide both directions, a no-candidate case and an unjudged case.");
  report.checks.push({ name: "dynamic_seed_scenarios", listingCount: listings.length, buyerCount: buyers.length,
    listingResult: listing.result_id, buyerResult: buyer.result_id, noCandidateResult: noCandidates.result_id, unjudgedResult: unjudged.result_id });
  await page.getByRole("button", { name: "교차 판정", exact: true }).click();
  const region = page.getByRole("region", { name: "교차 판정 업무 목록", exact: true });
  async function openTarget(target) {
    const close = region.getByRole("button", { name: "결과 상세 닫기", exact: true });
    if (await close.isVisible()) await close.click();
    await region.getByRole("tab", { name: target.anchor.anchor_type === "LISTING" ? "매물 기준" : "손님 기준", exact: true }).click();
    await region.locator("#f3-result-filter").selectOption("ALL");
    await region.locator("#f3-result-search").fill(target.anchor.display_name);
    const row = region.locator(`#f3-anchor-${target.anchor.anchor_id}`);
    await row.waitFor();
    const rowBody = row.locator("xpath=ancestor::li[1]");
    await rowBody.getByText("시드 예시 결과", { exact: true }).waitFor();
    await row.click();
    const result = region.getByRole("region", { name: "교차 판정 결과 상세", exact: true });
    await result.getByText("실제 모델 추론 결과가 아닙니다.", { exact: true }).first().waitFor();
    return result;
  }
  let detail = await openTarget(listing);
  await detail.locator(".f3-judgments__candidate").waitFor();
  assert.match(await detail.innerText(), /예시 판정/);
  for (let index = 0; index < 10; index++) {
    const response = page.waitForResponse(r => /\/f3\/judgment-results\/\d+(?:\?|$)/.test(r.url()) && r.status() === 200 && r.request().method() === "GET");
    await detail.getByRole("button", { name: "결과 새로고침", exact: true }).click(); await response;
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some(button => button.textContent === "결과 새로고침" && !button.disabled));
  }
  report.checks.push({ name: "seed_listing_detail_and_ten_read_only_refreshes", resultId: listing.result_id });
  await page.screenshot({ path: "/tmp/f3-seed-integration-listing.png", fullPage: true }); report.screenshots.push("/tmp/f3-seed-integration-listing.png");
  detail = await openTarget(buyer); await detail.locator(".f3-judgments__candidate").waitFor();
  report.checks.push({ name: "seed_buyer_detail", resultId: buyer.result_id });
  detail = await openTarget(noCandidates); await detail.getByText("저장된 조건 후보가 없습니다.", { exact: true }).waitFor();
  assert.equal(await detail.locator(".f3-judgments__candidate").count(), 0);
  report.checks.push({ name: "zero_candidates_remain_normal_seed_result", resultId: noCandidates.result_id });
  detail = await openTarget(unjudged);
  const result = await get(`/f3/judgment-results/${unjudged.result_id}?limit=100`);
  const candidate = result.candidates.find(item => item.match_grade == null);
  assert.ok(candidate, "The persisted seed must expose an unjudged SQL candidate.");
  const unjudgedButton = detail.locator(".f3-judgments__candidate-list").getByRole("button", { name: new RegExp(`^${candidate.target.display_name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} · AI 미판정`) });
  await unjudgedButton.click();
  await detail.locator(".f3-judgments__candidate").getByText("AI 미판정", { exact: true }).first().waitFor();
  assert.equal(await detail.getByRole("button", { name: "관심없음 기록", exact: true }).isDisabled(), true);
  assert.match(await detail.innerText(), new RegExp(`미판정\\s+${unjudged.summary.unjudged_count}`));
  report.checks.push({ name: "unjudged_is_not_rejected_and_feedback_disabled", resultId: unjudged.result_id, count: unjudged.summary.unjudged_count });
  await detail.locator(".f3-judgments__candidate").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/f3-seed-integration-unjudged.png", fullPage: true }); report.screenshots.push("/tmp/f3-seed-integration-unjudged.png");
  assert.equal(report.requests.runPosts, 0); assert.equal(report.requests.feedbackPosts, 0); assert.equal(report.requests.unexpectedWrites, 0);
  assert.deepEqual(report.pageErrors, []);
  report.unexpectedConsoleErrors = report.consoleErrors.filter(message => !/401 \(Unauthorized\)/.test(message));
  assert.deepEqual(report.unexpectedConsoleErrors, []);
  await context.close();
} catch (error) {
  report.failure = error instanceof Error ? error.message : String(error);
  if (page) await page.screenshot({ path: "/tmp/f3-seed-integration-failure.png", fullPage: true }).catch(() => {});
  throw error;
} finally {
  await writeFile("/tmp/f3-seed-integration-report.json", JSON.stringify(report, null, 2));
  await browser.close(); console.log(JSON.stringify(report, null, 2));
}
