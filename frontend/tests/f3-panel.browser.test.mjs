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
  VITE_AUTH_DEVELOPMENT_ENABLED: "true",
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

/** 첫 화면은 홈이다. 장부 그리드를 보려면 상단바에서 매물장을 먼저 연다. */
async function openPropertyLedger(page) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "매물장", exact: true }).click();
  const links = page.locator(".ledger-grid__detail-link");
  await links.first().waitFor();
  return links;
}

/**
 * 상세의 [교차 판정 실행]을 눌러 판정을 시작한다.
 *
 * 상세 진입과 저장은 판정을 시작하지 않는다(F3-CR-03·04). 실행 시점은 사용자가 정하므로
 * 브라우저 검사도 같은 경로로 들어간다.
 */
async function runCrossJudgment(page) {
  await page.getByRole("button", { name: "교차 판정 실행", exact: true }).click();
  const panel = page.locator("#cross-match-panel");
  await panel.waitFor();
  return panel;
}

/**
 * 동작 감소 설정을 켜면 스크롤 애니메이션을 쓰지 않는다.
 *
 * `styles.css`의 `scroll-behavior: auto`는 CSS 경로에만 걸린다. `scrollIntoView`에 옵션으로
 * 직접 넘긴 `behavior`가 CSS를 이기므로, 설정을 코드에서 읽지 않으면 동작 감소를 켠
 * 사용자에게도 애니메이션이 남는다. 실제로 어떤 `behavior`로 불렀는지를 본다.
 */
async function openDetailAndRecordScroll(page) {
  // 페이지 스크립트보다 먼저 걸어야 첫 호출부터 기록된다.
  await page.addInitScript(() => {
    window.__scrollBehaviors = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function record(options) {
      window.__scrollBehaviors.push(options && options.behavior);
      return original.call(this, options);
    };
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "매물장", exact: true }).click();
  const links = page.locator(".ledger-grid__detail-link");
  await links.first().waitFor();
  await links.nth(1).click();

  // 접었다 펴면 섹션으로 스크롤한다.
  const rail = page.getByRole("button", { name: "교차 판정", exact: true });
  await page.locator("#detail-section-cross-match").waitFor();
  await rail.click();
  await page.locator("#detail-section-cross-match").waitFor({ state: "detached" });
  await rail.click();
  await page.locator("#detail-section-cross-match").waitFor();
  await page.waitForFunction(() => window.__scrollBehaviors.length > 0, undefined, { timeout: 10_000 });
  return page.evaluate(() => window.__scrollBehaviors);
}

test("동작 감소를 켜면 섹션 스크롤에 애니메이션을 쓰지 않는다", { timeout: 120_000 }, async () => {
  const reduced = await browser.newPage();
  await reduced.emulateMedia({ reducedMotion: "reduce" });
  const reducedBehaviors = await openDetailAndRecordScroll(reduced);
  assert.deepEqual([...new Set(reducedBehaviors)], ["auto"]);
  await reduced.close();

  // 설정을 켜지 않은 환경에서는 종전대로 부드럽게 움직인다.
  const normal = await browser.newPage();
  await normal.emulateMedia({ reducedMotion: "no-preference" });
  const normalBehaviors = await openDetailAndRecordScroll(normal);
  assert.deepEqual([...new Set(normalBehaviors)], ["smooth"]);
  await normal.close();
});

/**
 * 두 버튼의 역할이 다르다.
 *
 * 레일의 [교차 판정]은 섹션을 여닫기만 하고, 섹션 안의 [교차 판정 실행]이 판정을 시작한다.
 * 여닫기가 실행을 겸하면 접어 두려고 누른 버튼이 판정을 새로 세운다.
 */
test("레일 버튼은 섹션을 여닫기만 하고 판정은 실행 버튼이 시작한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage();
  const failures = [];
  page.on("pageerror", (error) => failures.push(String(error)));

  const links = await openPropertyLedger(page);
  await links.nth(1).click();

  const section = page.locator("#detail-section-cross-match");
  const rail = page.getByRole("button", { name: "교차 판정", exact: true });
  await section.waitFor();
  // 상세를 열면 섹션은 펴져 있고 판정은 아직 돌지 않는다.
  assert.equal(await page.locator("#cross-match-panel").count(), 0);

  // 접는다. 판정은 여전히 시작하지 않는다.
  await rail.click();
  await section.waitFor({ state: "detached" });
  assert.equal(await page.locator("#cross-match-panel").count(), 0);

  // 다시 편다. 여기까지도 실행은 없다.
  await rail.click();
  await section.waitFor();
  assert.equal(await page.locator("#cross-match-panel").count(), 0);

  // 실행 버튼을 눌러야 판정이 시작된다.
  await runCrossJudgment(page);
  await page.getByText("기준 세대 확인").waitFor();

  assert.deepEqual(failures, []);
  await page.close();
});
/** 매물 건이 있는 세대 상세를 열고 사용자가 실제로 교차 판정 버튼을 누르는 흐름. */
async function openListingCrossMatch(page) {
  const links = await openPropertyLedger(page);
  // mock index 1은 listingFor 규칙상 매물 건을 가진다.
  await links.nth(1).click();
  await runCrossJudgment(page);
}

test("판정이 단계를 넘겨 후보와 등급까지 그린다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage();
  const failures = [];
  page.on("pageerror", (error) => failures.push(String(error)));

  // 매물 건이 있는 세대를 연다. mock 장부는 네 세대 중 하나를 매물 없는 세대로 만든다.
  await openListingCrossMatch(page);
  const panel = page.locator("#cross-match-panel");

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

  // 전체 23건 중 상위 5건을 판정하고 기각 1건을 숨겨, 첫 페이지에 19건이 보인다.
  assert.equal(await page.locator(".cross-match-panel__candidate").count(), 19);
  assert.match(await panel.innerText(), /상위 5건 판정 · 전체 23건/);
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

test("판정된 후보에는 관심없음을 남기고 미판정 후보에는 잠긴다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage();
  const failures = [];
  page.on("pageerror", (error) => failures.push(String(error)));
  await openListingCrossMatch(page);
  await page
    .locator(".cross-match-panel__grade-heading h4")
    .first()
    .waitFor({ timeout: COMPLETION_TIMEOUT_MS });

  // 판정된 후보. `judgment_id`가 있으므로 피드백을 보낼 수 있다.
  await page.locator(".cross-match-panel__more-actions summary").first().click();
  const button = page.getByRole("button", { name: "관심없음" });
  assert.equal(await button.isDisabled(), false);

  await button.click();
  const modal = page.getByLabel("관심없음 사유");
  await modal.waitFor();
  // 자유 메모 입력란이 없다. 서버가 `detail`을 받지 않으므로 쓸 자리를 두지 않는다.
  assert.equal(await modal.locator("textarea").count(), 0);

  await modal.getByRole("button", { name: "피드백 기록" }).click();
  // 성공한 뒤에만 닫힌다. 보내자마자 닫으면 서버가 거절해도 기록된 줄 안다.
  await modal.waitFor({ state: "hidden", timeout: 10_000 });
  await page.getByText("관심없음 피드백을 기록했습니다").first().waitFor();

  // 카드화되지 않은 후보는 판정 행이 없어 잠긴 채로 남는다.
  await page.locator(".cross-match-panel__grade.is-collapsed summary").first().click();
  await page
    .locator(".cross-match-panel__grade.is-collapsed .cross-match-panel__candidate")
    .first()
    .click();
  // `details`는 후보를 바꿔도 열린 채로 남는다. 다시 누르면 닫히므로 상태를 직접 맞춘다.
  await page.locator(".cross-match-panel__more-actions").first().evaluate((el) => {
    el.open = true;
  });
  assert.equal(await page.getByRole("button", { name: "관심없음" }).isDisabled(), true);
  assert.ok((await page.getByText("아직 판정하지 않은 후보").count()) > 0);

  assert.deepEqual(failures, []);
  await page.close();
});

test("장부에 없는 후보는 식별자만 보여준다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage();
  await openListingCrossMatch(page);
  await page
    .locator(".cross-match-panel__grade-heading h4")
    .first()
    .waitFor({ timeout: COMPLETION_TIMEOUT_MS });

  // mock F3의 후보 식별자는 mock 장부에 없는 값이다. 표시 이름을 지어내지 않고 식별자만
  // 보여주며, 판정 내용은 그대로 그린다.
  const title = await page.locator(".cross-match-panel__candidate-title").first().innerText();
  assert.match(title, /^구입장 #\d+$/);
  assert.ok((await page.getByText("장부 행을 찾지 못했습니다").count()) > 0);

  await page.close();
});
