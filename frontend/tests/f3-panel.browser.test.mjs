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
  VITE_F3_SOURCE: "mock",
  VITE_CALENDAR_SOURCE: "mock",
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
  await page.getByRole("button", { name: "교차 판정 결과 보기", exact: true }).click();
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

test("목록 조회·상세 열기·새로고침은 실행을 접수하지 않고 키보드 초점을 복원한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page); await recordWrites(page);
    await page.getByRole("button", { name: "교차 판정", exact: true }).click();
    const row = page.getByRole("button", { name: "합성 매물 #2 결과 보기", exact: true });
    await row.click();
    await page.getByRole("heading", { name: "판정 결과 상세", exact: true }).waitFor();
    await page.locator(".f3-judgments__candidate").waitFor();
    for (let i = 0; i < 10; i++) {
      const refresh = page.getByRole("button", { name: "결과 새로고침", exact: true });
      await refresh.click(); await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === '결과 새로고침' && !b.disabled));
    }
    assert.equal(await page.evaluate(() => window.__writes.runs), 0);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.activeElement?.textContent === '합성 매물 #2 결과 보기');
    assert.equal(await page.locator('.f3-judgments__candidate').count(), 0);
  } finally { await page.close(); }
});

test("미판정 후보를 숨기지 않고 페이지를 이동하며 판정 전 피드백은 잠근다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page); await page.getByRole("button", { name: "교차 판정", exact: true }).click();
    await page.getByRole("button", { name: "합성 매물 #2 결과 보기", exact: true }).click();
    await page.locator('.f3-judgments__candidate').waitFor();
    assert.match(await page.locator('.f3-judgments__result').innerText(), /AI 판정 5 · 미판정 18/);
    await page.getByRole('button', { name: '다음 후보', exact: true }).click();
    await page.getByText('후보 페이지 2', { exact: true }).waitFor();
    await page.locator('.f3-judgments__candidate-list button').first().click();
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === '관심없음 기록' && b.disabled));
    assert.match(await page.locator('.f3-judgments__candidate').innerText(), /AI 미판정/);
  } finally { await page.close(); }
});

test("상세 편집 중 결과 보기는 GET이며 편집값을 유지한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    const links = await openPropertyLedger(page); await links.nth(1).click(); await recordWrites(page);
    await page.locator('#detail-memo').fill('저장 전 편집 유지');
    await runCrossJudgment(page); await page.locator('.f3-judgments__candidate').waitFor();
    assert.equal(await page.locator('#detail-memo').inputValue(), '저장 전 편집 유지');
    assert.equal(await page.evaluate(() => window.__writes.runs), 0);
    await page.getByRole('button', { name: '결과 접기', exact: true }).click();
    assert.equal(await page.locator('#detail-memo').inputValue(), '저장 전 편집 유지');
  } finally { await page.close(); }
});

test("관심없음은 판정 ID로 저장하고 미판정 필터를 유지한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page); await page.getByRole('button', { name: '교차 판정', exact: true }).click();
    await page.locator('#f3-result-filter').selectOption('HAS_UNJUDGED');
    await page.getByRole('button', { name: '합성 매물 #2 결과 보기', exact: true }).click();
    await page.getByRole('button', { name: '관심없음 기록', exact: true }).click();
    const modal = page.getByRole('dialog', { name: '관심없음 사유', exact: true });
    await modal.getByRole('button', { name: '피드백 기록', exact: true }).click();
    await modal.waitFor({ state: 'hidden' });
    await page.getByText('관심없음 피드백을 기록했습니다. 영구 제외나 처리 완료를 뜻하지 않습니다.', { exact: false }).waitFor();
    assert.equal(await page.locator('#f3-result-filter').inputValue(), 'HAS_UNJUDGED');
  } finally { await page.close(); }
});

test("선택 대상의 접근 권한을 잃으면 이전 후보·카드를 즉시 제거한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page); await page.getByRole('button', { name: '교차 판정', exact: true }).click();
    await page.getByRole('button', { name: '합성 매물 #2 결과 보기', exact: true }).click();
    await page.locator('.f3-judgments__candidate').waitFor();
    await page.evaluate(async () => {
      const { judgmentApi } = await import('/src/features/f3/judgments/api.ts');
      const { ApiError } = await import('/src/shared/api/index.ts');
      judgmentApi.target = async () => { throw new ApiError({ kind: 'forbidden', status: 403, message: 'synthetic access revocation' }); };
    });
    await page.getByRole('button', { name: '결과 새로고침', exact: true }).click();
    await page.getByText('대상이 없거나 현재 접근할 수 없습니다.', { exact: false }).waitFor();
    assert.equal(await page.locator('.f3-judgments__candidate').count(), 0);
    assert.equal(await page.getByText('기준 포지션 카드 펼치기', { exact: true }).count(), 0);
  } finally { await page.close(); }
});

test("FAILED_TERMINAL polling은 실패 요약을 다시 읽고 진행 중으로 덮지 않는다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page);
    await page.evaluate(async () => {
      const { judgmentApi } = await import('/src/features/f3/judgments/api.ts');
      const { f3Transport } = await import('/src/features/f3/api/f3Transport.ts');
      const target = judgmentApi.target; let terminal = false; window.__f3PollCount = 0;
      judgmentApi.target = async (...args) => ({ ...await target(...args), generation: terminal ? 'FAILED' : 'RUNNING', freshness: 'STALE' });
      f3Transport.getRunStatus = async () => { window.__f3PollCount += 1; terminal = true; return { status: 'FAILED_TERMINAL' }; };
    });
    await page.getByRole('button', { name: '교차 판정', exact: true }).click();
    await page.getByRole('button', { name: '합성 매물 #2 결과 보기', exact: true }).click();
    await page.locator('.f3-judgments__result').getByText('분석 실패', { exact: true }).waitFor();
    assert.equal(await page.locator('.f3-judgments__result').getByText('분석 중', { exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => window.__f3PollCount), 1);
  } finally { await page.close(); }
});

test("상태 polling 401은 이전 후보와 진행 중 표시를 제거한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page);
    await page.evaluate(async () => {
      const { judgmentApi } = await import('/src/features/f3/judgments/api.ts');
      const { f3Transport } = await import('/src/features/f3/api/f3Transport.ts');
      const { ApiError } = await import('/src/shared/api/index.ts'); const target = judgmentApi.target;
      judgmentApi.target = async (...args) => ({ ...await target(...args), generation: 'RUNNING' });
      f3Transport.getRunStatus = async () => { throw new ApiError({ kind: 'unauthorized', status: 401, message: 'synthetic expired session' }); };
    });
    await page.getByRole('button', { name: '교차 판정', exact: true }).click();
    await page.getByRole('button', { name: '합성 매물 #2 결과 보기', exact: true }).click();
    await page.getByText('대상이 없거나 현재 접근할 수 없습니다.', { exact: false }).waitFor();
    assert.equal(await page.locator('.f3-judgments__candidate').count(), 0);
    assert.equal(await page.locator('.f3-judgments__result').getByText('분석 중', { exact: true }).count(), 0);
  } finally { await page.close(); }
});

test("목록과 후보의 만료 cursor는 필터·선택을 유지해 첫 페이지로 복구한다", { timeout: 120_000 }, async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await openPropertyLedger(page);
    await page.evaluate(async () => {
      const { judgmentApi } = await import('/src/features/f3/judgments/api.ts');
      const { ApiError } = await import('/src/shared/api/index.ts'); const list = judgmentApi.list; const detail = judgmentApi.detail;
      window.__f3BadCursors = { list: 0, detail: 0 };
      judgmentApi.list = async (query, ...args) => { if (query.cursor) { window.__f3BadCursors.list += 1; throw new ApiError({ kind: 'validation', status: 422, code: 'F3_CURSOR_INVALID', message: 'synthetic changed revision' }); } return { ...await list(query, ...args), next_cursor: 'expired-list' }; };
      judgmentApi.detail = async (id, query, ...args) => { if (query?.cursor) { window.__f3BadCursors.detail += 1; throw new ApiError({ kind: 'validation', status: 422, code: 'F3_CURSOR_INVALID', message: 'synthetic changed revision' }); } return detail(id, query, ...args); };
    });
    await page.getByRole('button', { name: '교차 판정', exact: true }).click();
    await page.locator('#f3-result-filter').selectOption('HAS_UNJUDGED');
    await page.getByRole('button', { name: '다음 페이지', exact: true }).click();
    await page.getByText('목록이 변경되어 첫 페이지로 돌아왔습니다. 필터와 선택 대상은 유지했습니다.', { exact: false }).waitFor();
    assert.equal(await page.locator('#f3-result-filter').inputValue(), 'HAS_UNJUDGED');
    await page.getByRole('button', { name: '합성 매물 #2 결과 보기', exact: true }).click();
    await page.locator('.f3-judgments__candidate-list button').first().click();
    const selected = await page.locator('.f3-judgments__candidate h3').innerText();
    await page.getByRole('button', { name: '다음 후보', exact: true }).click();
    await page.getByText('후보 목록이 변경되어 첫 페이지로 돌아왔습니다. 선택 후보는 유지했습니다.', { exact: false }).waitFor();
    await page.getByText('후보 페이지 1', { exact: true }).waitFor();
    assert.equal(await page.locator('.f3-judgments__candidate h3').innerText(), selected);
    assert.deepEqual(await page.evaluate(() => window.__f3BadCursors), { list: 1, detail: 1 });
  } finally { await page.close(); }
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
    await page.waitForFunction(() => window.__writes.runs === 0);
    await page.locator("#detail-memo").fill("LOCAL_REGRESSION_UNIQUE_MEMO");
    await saveDetail(page);
    assert.deepEqual(await page.evaluate(() => window.__writes), { interactions: 1, runs: 0 });
    assert.equal(await page.locator("#cross-match-panel").count(), 1);
    await runCrossJudgment(page);
    await page.waitForFunction(() => window.__writes.runs === 0);
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
