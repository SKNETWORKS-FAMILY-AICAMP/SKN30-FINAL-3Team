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
import { openEvidencePanel } from "./helpers/f3-evidence.mjs";

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

/** F3 브라우저 검증이 실행 시각에 따라 자동 브리핑 모달에 가로막히지 않게 격리한다. */
async function markDailyBriefingComplete(page) {
  const businessDate = new Date(Date.now() + 9 * 60 * 60 * 1_000).toISOString().slice(0, 10);
  await page.addInitScript((key) => {
    window.localStorage.setItem("time-keeper.last-briefing", key);
  }, businessDate);
}

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

test("매물·구입 판정의 내부 필드명은 제목과 설명에서 한국어로 표시된다", { timeout: 60_000 }, async () => {
  for (const kind of ["listing", "requirement"]) {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
    try {
      await openEvidencePanel(page, baseUrl, kind);
      const panel = page.locator("#cross-match-panel");
      assert.deepEqual(await panel.locator(".cross-match-panel__evidence-field").allTextContents(),
        ["확정 기한", "일정 조건", "제시 금액", "판정 근거"]);
      const text = await panel.innerText();
      assert.doesNotMatch(text, /timing|hard_deadline|stated_amount|future\.internal_key/);
      assert.match(text, /2027-05-07/);
      assert.match(text, /8천만원/);
      assert.match(text, /5천만원/);
      assert.equal(await page.evaluate(() => window.evidenceSubmissions), 1);
    } finally { await page.close(); }
  }
});

/** 첫 화면은 홈이다. 장부 그리드를 보려면 상단바에서 매물장을 먼저 연다. */
async function openPropertyLedger(page) {
  await markDailyBriefingComplete(page);
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
  await markDailyBriefingComplete(page);
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "매물장", exact: true }).click();
  const links = page.locator(".ledger-grid__detail-link");
  await links.first().waitFor();
  await links.nth(1).click();

  // 판정을 실행하면 패널로 스크롤한다.
  await page.locator("#detail-section-cross-match").waitFor();
  await runCrossJudgment(page);
  await page.waitForFunction(() => window.__scrollBehaviors.length > 0, undefined, { timeout: 10_000 });
  return page.evaluate(() => window.__scrollBehaviors);
}

test("동작 감소를 켜면 섹션 스크롤에 애니메이션을 쓰지 않는다", { timeout: 120_000 }, async () => {
  const reduced = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await reduced.emulateMedia({ reducedMotion: "reduce" });
  const reducedBehaviors = await openDetailAndRecordScroll(reduced);
  assert.deepEqual([...new Set(reducedBehaviors)], ["auto"]);
  await reduced.close();

  // 설정을 켜지 않은 환경에서는 종전대로 부드럽게 움직인다.
  const normal = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await normal.emulateMedia({ reducedMotion: "no-preference" });
  const normalBehaviors = await openDetailAndRecordScroll(normal);
  assert.deepEqual([...new Set(normalBehaviors)], ["smooth"]);
  await normal.close();
});

/**
 * 판정을 시작하는 버튼은 둘이고, 상세 진입은 어느 쪽도 부르지 않는다.
 *
 * 액션 레일의 [교차 판정]과 섹션의 [교차 판정 실행]은 같은 실행을 요청한다.
 * 저장과 상세 진입은 판정을 시작하지 않는다(F3-CR-03·04).
 */
test("상세 진입은 판정을 시작하지 않고 두 버튼이 각각 실행한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const failures = [];
  page.on("pageerror", (error) => failures.push(String(error)));

  const links = await openPropertyLedger(page);
  await links.nth(1).click();

  // 섹션은 늘 보이지만 상세를 열기만 해서는 판정이 돌지 않는다.
  await page.locator("#detail-section-cross-match").waitFor();
  assert.equal(await page.locator("#cross-match-panel").count(), 0);

  // 섹션의 실행 버튼이 판정을 시작한다.
  await runCrossJudgment(page);
  await page.getByText("기준 세대 확인").waitFor();
  await page.close();

  // 레일 버튼도 같은 실행을 요청한다. 여닫기가 아니므로 aria-expanded를 갖지 않는다.
  const rail = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const railLinks = await openPropertyLedger(rail);
  await railLinks.nth(1).click();
  assert.equal(await rail.locator("#cross-match-panel").count(), 0);
  const railButton = rail.getByRole("button", { name: "교차 판정", exact: true });
  assert.equal(await railButton.getAttribute("aria-expanded"), null);
  // 패널이 없는 동안에는 없는 id를 가리키지 않는다.
  assert.equal(await railButton.getAttribute("aria-controls"), null);
  await railButton.click();
  await rail.locator("#cross-match-panel").waitFor();
  assert.equal(await railButton.getAttribute("aria-controls"), "cross-match-panel");
  await rail.getByText("기준 세대 확인").waitFor();
  await rail.close();

  assert.deepEqual(failures, []);
});
/** 매물 건이 있는 세대 상세를 열고 사용자가 실제로 교차 판정 버튼을 누르는 흐름. */
async function openListingCrossMatch(page) {
  const links = await openPropertyLedger(page);
  // mock index 1은 listingFor 규칙상 매물 건을 가진다.
  await links.nth(1).click();
  await runCrossJudgment(page);
}

test("판정이 단계를 넘겨 후보와 등급까지 그린다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
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
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
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
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
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

/** Instrument the selected synthetic transport without connecting to a real API or model. */
async function recordWrites(page) {
  await page.evaluate(async () => {
    const { ledgerTransport } = await import("/src/features/ledger/api/ledgerTransport.ts");
    const { f3Transport } = await import("/src/features/f3/api/f3Transport.ts");
    window.__writes = { interactions: 0, runs: 0 };
    const interaction = ledgerTransport.createClientInteraction.bind(ledgerTransport);
    ledgerTransport.createClientInteraction = async (...args) => {
      window.__writes.interactions += 1;
      return interaction(...args);
    };
    const createRun = f3Transport.createRun.bind(f3Transport);
    f3Transport.createRun = async (...args) => {
      window.__writes.runs += 1;
      return createRun(...args);
    };
  });
}

async function saveDetail(page) {
  await page.getByRole("button", { name: "저장", exact: true }).click();
  // Synthetic rows do not necessarily start with the UI duplicate check completed.
  const temporary = page.getByRole("button", { name: "임시저장", exact: true });
  const settled = page.getByText("모든 변경 저장됨", { exact: true }).first();
  await Promise.race([temporary.waitFor(), settled.waitFor()]);
  if (await temporary.isVisible()) await temporary.click();
  await settled.waitFor();
}

test("비고 저장은 상담 로그를 복제하거나 열린 F3를 재실행하지 않는다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    const links = await openPropertyLedger(page);
    await links.nth(1).click();
    await page.locator("#detail-log").waitFor();
    await recordWrites(page);
    await page.locator("#detail-log").fill("합성 회귀 상담 내용");
    await saveDetail(page);
    assert.equal(await page.evaluate(() => window.__writes.interactions), 1);
    await runCrossJudgment(page);
    await page.waitForFunction(() => window.__writes.runs === 1);
    await page.locator("#detail-memo").fill("LOCAL_REGRESSION_UNIQUE_MEMO");
    await saveDetail(page);
    assert.deepEqual(await page.evaluate(() => window.__writes), { interactions: 1, runs: 1 });
    assert.equal(await page.locator("#cross-match-panel").count(), 0);
    await runCrossJudgment(page);
    await page.waitForFunction(() => window.__writes.runs === 2);
    await page.getByRole("button", { name: "상세 닫기", exact: true }).click();
    await page.getByRole("textbox", { name: "통합 검색" }).fill("LOCAL_REGRESSION_UNIQUE_MEMO");
    await page.waitForFunction(() => document.querySelector(".grid-statusbar")?.textContent?.startsWith("1건 표시"));
    await page.locator(".ledger-grid__detail-link").first().waitFor();
    assert.equal(await page.locator('.ledger-grid__ag-grid .ag-row [col-id="unit"]').count(), 1);

    // A completed append followed by a failed refresh must stay single when retried from the grid.
    await page.locator(".ledger-grid__detail-link").first().click();
    await page.locator("#detail-log").fill("후속 조회 실패 회귀 상담");
    await page.locator("#detail-duplicate-check").check();
    await page.evaluate(async () => {
      const { ledgerTransport } = await import("/src/features/ledger/api/ledgerTransport.ts");
      const create = ledgerTransport.createClientInteraction.bind(ledgerTransport);
      const get = ledgerTransport.getPropertyUnit.bind(ledgerTransport);
      let failRefresh = false;
      ledgerTransport.createClientInteraction = async (...args) => {
        const result = await create(...args);
        failRefresh = true;
        return result;
      };
      ledgerTransport.getPropertyUnit = async (...args) => {
        if (failRefresh) { failRefresh = false; throw new Error("synthetic refresh failure"); }
        return get(...args);
      };
    });
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await page.locator(".detail-workspace__save-error").waitFor();
    assert.match(await page.locator(".detail-workspace__save-error").innerText(), /synthetic refresh failure/);
    assert.equal(await page.evaluate(() => window.__writes.interactions), 2);
    await page.getByRole("button", { name: "상세 닫기", exact: true }).click();
    await page.getByRole("button", { name: "저장 안 함", exact: true }).click();
    await page.getByRole("button", { name: /변경 저장/ }).click();
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some((button) => button.textContent === "변경 저장" && button.disabled));
    assert.equal(await page.evaluate(() => window.__writes.interactions), 2);
  } finally { await page.close(); }
});

test("구입장 검색 결과와 건수가 일치하고 비고 저장이 상담을 복제하지 않는다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page);
    await page.getByRole("button", { name: "구입장", exact: true }).click();
    await page.locator('.buyer-ledger-grid .ag-row [col-id="buyer"]').first().waitFor();
    await page.getByRole("textbox", { name: "통합 검색" }).fill("DOES_NOT_EXIST_290913");
    await page.waitForFunction(() => document.querySelector(".grid-statusbar")?.textContent?.startsWith("0건 표시"));
    assert.equal(await page.locator('.buyer-ledger-grid .ag-row [col-id="buyer"]').count(), 0);
    await page.getByRole("textbox", { name: "통합 검색" }).fill("인천사모님");
    await page.locator('.buyer-ledger-grid .ag-row [col-id="buyer"]').first().click();
    await page.locator("#buyer-content").waitFor();
    await recordWrites(page);
    await page.locator("#buyer-content").fill("합성 구입장 회귀 상담");
    await page.locator("#buyer-consent").check();
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await page.getByText("모든 변경 저장됨", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.__writes.interactions), 1);
    await page.locator("#buyer-memo").fill("구입장 비고만 변경");
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await page.getByText("모든 변경 저장됨", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.__writes.interactions), 1);
  } finally { await page.close(); }
});

test("캘린더 추가·수정 dialog는 접근성 트리에 하나만 열리고 Escape로 돌아간다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page);
    await page.getByRole("button", { name: "캘린더를 엽니다" }).click();
    await page.getByRole("dialog", { name: "캘린더", exact: true }).waitFor();
    await page.getByRole("button", { name: /일정 추가$/ }).first().click();
    const form = page.getByRole("dialog", { name: "일정 추가", exact: true });
    await form.waitFor();
    assert.equal(await page.getByRole("dialog").count(), 1);
    await form.getByRole("textbox", { name: "제목" }).fill("합성 접근성 일정");
    await form.getByRole("button", { name: "저장", exact: true }).click();
    await page.getByRole("dialog", { name: "캘린더", exact: true }).waitFor();
    await page.getByRole("button", { name: /합성 접근성 일정/ }).click();
    await page.getByRole("dialog", { name: "일정 수정", exact: true }).waitFor();
    assert.equal(await page.getByRole("dialog").count(), 1);
    await page.keyboard.press("Escape");
    await page.getByRole("dialog", { name: "캘린더", exact: true }).waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("dialog", { name: "캘린더", exact: true }).waitFor({ state: "hidden" });
    // Closing hides the dialog before the animation-frame focus restoration runs.
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "캘린더를 엽니다");
  } finally { await page.close(); }
});

test("열린 패널의 외부 버전 갱신은 명시적 재판정 전까지 실행을 접수하지 않는다", { timeout: 60_000 }, async () => {
  const page = await browser.newPage();
  try {
    await page.goto(`${baseUrl}tests/fixtures/f3-lifecycle.html`);
    await page.getByRole("button", { name: "판정 열기" }).click();
    await page.waitForFunction(() => document.querySelector("#lifecycle-count")?.textContent === "1");
    await page.getByRole("button", { name: "외부 버전 갱신" }).click();
    await page.waitForFunction(() => document.querySelector("#lifecycle-state")?.textContent === "superseded");
    assert.equal(await page.locator("#lifecycle-count").innerText(), "1");
    await page.getByRole("button", { name: "명시적 재판정" }).click();
    await page.waitForFunction(() => document.querySelector("#lifecycle-count")?.textContent === "2");
  } finally { await page.close(); }
});

test("매물·구입 F3 패널을 키보드로 닫으면 실행 버튼으로 초점을 복원한다", { timeout: 60_000 }, async () => {
  for (const kind of ["listing", "requirement"]) {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
    try {
      const links = await openPropertyLedger(page);
      if (kind === "listing") await links.nth(1).click();
      else {
        await page.getByRole("button", { name: "구입장", exact: true }).click();
        await page.locator('.buyer-ledger-grid .ag-row [col-id="buyer"]').first().click();
      }
      const opener = page.getByRole("button", {
        name: kind === "listing" ? "교차 판정 실행" : "교차 판정", exact: true,
      });
      await opener.focus();
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => document.activeElement?.id === "cross-match-panel-title");
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "교차 판정 Panel 닫기");
      await page.keyboard.press("Enter");
      await page.locator("#cross-match-panel").waitFor({ state: "hidden" });
      await page.waitForFunction(() => document.activeElement?.textContent?.trim() === "교차 판정 실행" || document.activeElement?.textContent?.trim() === "교차 판정");
      assert.equal(await opener.evaluate(element => document.activeElement === element), true);
    } finally { await page.close(); }
  }
});
