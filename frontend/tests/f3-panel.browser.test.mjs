/**
 * F3 후보 패널 브라우저 확인.
 *
 * decoder와 mock 시나리오는 단위 테스트가 덮지만, 훅이 실제로 단계를 넘기며 화면을 다시
 * 그리는지는 브라우저에서만 확인할 수 있다. polling, 단계 전환, 등급 그룹, 부모별 기각 노출,
 * 페이지네이션을 한 번에 본다.
 *
 * 백엔드 없이 돈다. mock 장부에서는 `AuthGate`가 세션을 요구하지 않고 F3도 mock 출처를 따른다.
 *
 * 느린 테스트다. mock이 완료까지 10.5초를 쓰므로 기본 테스트 묶음에 넣지 않고 `test:browser`로
 * 따로 실행한다.
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { after, before, test } from "node:test";
import { chromium } from "playwright";

/** 실제 사용자 데이터와 무관한 mock 설정. 지연을 0으로 두어 확인 시간을 줄인다. */
const SERVER_ENV = {
  VITE_LEDGER_SOURCE: "mock",
  VITE_API_BASE_URL: "/api/v1",
  VITE_MOCK_ROW_COUNT: "40",
  VITE_MOCK_LATENCY_MS: "0",
  FRONTEND_BACKEND_ORIGIN: "http://127.0.0.1:8000",
};

/** mock 실행이 완료까지 쓰는 시간(10.5초)에 여유를 더한다. */
const COMPLETION_TIMEOUT_MS = 30_000;

/** vite가 주소를 색으로 감싸 출력한다. */
const ANSI = new RegExp(String.fromCharCode(27) + "\[[0-9;]*m", "g");

let server;
let browser;
let baseUrl;

function startDevServer() {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      ["./node_modules/vite/bin/vite.js", "--host", "127.0.0.1"],
      { env: { ...process.env, ...SERVER_ENV }, stdio: ["ignore", "pipe", "pipe"] },
    );

    const timer = setTimeout(
      () => reject(new Error(`vite dev server did not start
${output}`)),
      60_000,
    );
    let output = "";

    // vite는 주소를 색으로 감싸 출력하므로 포트 앞뒤에 제어 문자가 낀다. 지우고 읽는다.
    const read = (chunk) => {
      output += String(chunk).replace(ANSI, "");
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if (match) {
        clearTimeout(timer);
        resolve({ child, url: match[0] });
      }
    };

    child.stdout.on("data", read);
    child.stderr.on("data", read);
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`vite exited with ${code}\n${output}`));
    });
  });
}

before(async () => {
  const started = await startDevServer();
  server = started.child;
  baseUrl = started.url;
  browser = await chromium.launch();
});

after(async () => {
  await browser?.close();
  server?.kill();
});

test("판정이 단계를 넘겨 후보와 등급까지 그린다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage();
  const failures = [];
  page.on("pageerror", (error) => failures.push(String(error)));

  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });

  // 매물 건이 있는 세대를 연다. mock 장부는 네 세대 중 하나를 매물 없는 세대로 만든다.
  const links = page.locator(".ledger-grid__detail-link");
  await links.first().waitFor();
  await links.nth(1).click();

  const panel = page.locator("#cross-match-panel");
  await panel.waitFor();

  // 접수 직후에는 진행 단계만 보이고 후보는 없다. 완료를 가장하지 않는다.
  await page.getByText("기준 세대 확인").waitFor();
  assert.equal(await page.locator(".cross-match-panel__grade-heading h4").count(), 0);

  // 완료되면 등급 그룹이 나타난다.
  await page
    .locator(".cross-match-panel__grade-heading h4")
    .first()
    .waitFor({ timeout: COMPLETION_TIMEOUT_MS });

  // 세대 상세는 기각을 숨기고 강함·약함만 보여준다.
  const grades = await page.locator(".cross-match-panel__grade-heading h4").allInnerTexts();
  assert.deepEqual(grades, ["강함", "약함"]);

  // 카드화되지 않은 SQL 후보는 판정 실패가 아니라 별도 그룹으로 접어 둔다.
  const collapsed = await page
    .locator(".cross-match-panel__grade.is-collapsed summary strong")
    .allInnerTexts();
  assert.ok(collapsed.includes("상세 판정 미수행"));

  // 전체 23건 중 기각 5건을 숨겨 15건이 보이고, 첫 페이지는 20건 기준이다.
  assert.equal(await page.locator(".cross-match-panel__candidate").count(), 15);
  const pager = page.getByLabel("후보 페이지 이동");
  assert.match((await pager.innerText()).replace(/\s+/g, " "), /1–20 \/ 23/);

  await pager.getByRole("button", { name: "다음" }).click();
  await page.waitForFunction(
    () => document.querySelectorAll(".cross-match-panel__candidate").length === 3,
    undefined,
    { timeout: 10_000 },
  );

  assert.deepEqual(failures, []);
  await page.close();
});

test("관심없음은 판정 식별자가 없어 잠겨 있다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage();
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });

  const links = page.locator(".ledger-grid__detail-link");
  await links.first().waitFor();
  await links.nth(1).click();
  await page
    .locator(".cross-match-panel__grade-heading h4")
    .first()
    .waitFor({ timeout: COMPLETION_TIMEOUT_MS });

  await page.locator(".cross-match-panel__more-actions summary").first().click();

  // `match_candidate_evaluation_id`가 공개 계약에 없다. 장부 ID로 추측해 보내면 서버 검증은
  // 통과하고 엉뚱한 판정 행에 저장되므로 화면이 버튼을 잠근다.
  const button = page.getByRole("button", { name: "관심없음" });
  assert.equal(await button.isDisabled(), true);
  assert.ok((await page.getByText("판정 식별자 연동 후").count()) > 0);

  await page.close();
});
