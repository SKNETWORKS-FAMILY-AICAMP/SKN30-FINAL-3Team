import { chromium } from "playwright";
import fs from "node:fs/promises";

const baseUrl = process.env.PROTOTYPE_URL || "http://127.0.0.1:4173/";
const outputDir = new URL("../artifacts/", import.meta.url);
const outputPath = (name) => new URL(name, outputDir).pathname;
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
const consoleErrors = [];
const assertions = {};
const metrics = {};

function observe(page) {
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
}

async function openPage(viewport) {
  const page = await context.newPage();
  await page.setViewportSize(viewport);
  observe(page);
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator(".ag-root-wrapper").waitFor({ state: "visible" });
  return page;
}

async function openFirstDetail(page) {
  await page.getByRole("button", { name: /상세 열기/ }).first().click();
  await page.locator(".detail-workspace-modal").waitFor({ state: "visible" });
}

const page1600 = await openPage({ width: 1600, height: 900 });
await page1600.screenshot({ path: outputPath("05-grid-1600-filtered.png") });
assertions.filteredCountMatches = /필터 [1-9][0-9,]*건/.test(await page1600.locator(".f1-topbar__counts").innerText());
assertions.separateSaveAndAI =
  (await page1600.getByText("저장 상태", { exact: true }).count()) > 0 &&
  (await page1600.getByText("AI 처리 상태", { exact: true }).count()) > 0;
assertions.gridRowsPresent = (await page1600.locator(".ag-row").count()) > 0;
assertions.bulkSelectionPresent = (await page1600.locator(".grid-statusbar").innerText()).includes("0건 선택");
metrics.gridRowHeight = (await page1600.locator(".ag-row").first().boundingBox())?.height;
assertions.gridDensity40 = Math.abs((metrics.gridRowHeight || 0) - 40) < 1;

await openFirstDetail(page1600);
const modalBox = await page1600.locator(".detail-workspace-modal").boundingBox();
const actionRailBox = await page1600.locator(".detail-workspace__action-rail").boundingBox();
metrics.modal1600 = modalBox;
metrics.actionRail1600 = actionRailBox;
assertions.singleDetailModal = (await page1600.locator(".detail-workspace-modal").count()) === 1;
assertions.actionRailVisible = Boolean(actionRailBox && actionRailBox.x + actionRailBox.width <= 1600);
assertions.saveEnabled = await page1600.locator(".detail-workspace__action-rail").getByRole("button", { name: "저장", exact: true }).isEnabled();

await page1600.locator("#detail-owner").fill("저장안함 검증 소유자");
await page1600.locator(".detail-workspace__action-rail").getByRole("button", { name: "상세 닫기" }).click();
const dirtyDialog = page1600.getByRole("alertdialog");
await dirtyDialog.waitFor({ state: "visible" });
await page1600.screenshot({ path: outputPath("06-detail-close-three-way.png") });
assertions.closeThreeWay =
  await dirtyDialog.getByRole("button", { name: "저장", exact: true }).isVisible() &&
  await dirtyDialog.getByRole("button", { name: "저장 안 함", exact: true }).isVisible() &&
  await dirtyDialog.getByRole("button", { name: "취소", exact: true }).isVisible();
await dirtyDialog.getByRole("button", { name: "저장 안 함", exact: true }).click();
await page1600.locator(".detail-workspace-modal").waitFor({ state: "detached" });
assertions.discardDoesNotLeak = (await page1600.getByText("저장안함 검증 소유자", { exact: true }).count()) === 0;

await page1600.getByRole("button", { name: "행 추가", exact: true }).click();
await page1600.locator(".detail-workspace-modal").waitFor({ state: "visible" });
const draftRail = page1600.locator(".detail-workspace__action-rail");
assertions.incompleteSaveEnabled = await draftRail.getByRole("button", { name: "저장", exact: true }).isEnabled();
await draftRail.getByRole("button", { name: "저장", exact: true }).click();
await page1600.locator(".detail-workspace__state-summary").getByText("작성 중", { exact: true }).waitFor({ state: "visible" });
await page1600.screenshot({ path: outputPath("07-detail-incomplete-saved.png") });
assertions.incompleteSavedAsDraft = await page1600.locator(".detail-workspace__state-summary").getByText("작성 중", { exact: true }).isVisible();
await draftRail.getByRole("button", { name: "상세 닫기" }).click();
await page1600.locator(".detail-workspace-modal").waitFor({ state: "detached" });

await openFirstDetail(page1600);
const f2Panel = page1600.locator(".detail-section--f2");
await f2Panel.scrollIntoViewIfNeeded();
await f2Panel.getByRole("button", { name: /상담 후 음성메모 녹음/ }).click();
await f2Panel.getByText("음성메모 녹음 중", { exact: true }).waitFor({ state: "visible" });
await f2Panel.screenshot({ path: outputPath("08-f2-recording-focused.png") });
assertions.f2Recording = await f2Panel.getByText("음성메모 녹음 중", { exact: true }).isVisible();
await f2Panel.getByRole("button", { name: "녹음 종료", exact: true }).click();
await f2Panel.getByRole("button", { name: "분석 시작", exact: true }).click();
await f2Panel.getByText("음성메모를 분석하고 있습니다", { exact: true }).waitFor({ state: "visible" });
await page1600.locator(".detail-workspace__action-rail").getByRole("button", { name: "상세 닫기" }).click();
const processingDialog = page1600.getByRole("alertdialog");
await processingDialog.getByText("진행 중인 분석을 취소할까요?", { exact: true }).waitFor({ state: "visible" });
await page1600.screenshot({ path: outputPath("09-f2-processing-close-warning.png") });
assertions.processingWarningFirst = await processingDialog.getByRole("button", { name: "분석 취소하고 닫기 계속", exact: true }).isVisible();
await processingDialog.getByRole("button", { name: "분석 계속", exact: true }).click();
await f2Panel.getByText("필드 제안 검토", { exact: true }).waitFor({ state: "visible", timeout: 8000 });
await f2Panel.scrollIntoViewIfNeeded();
await f2Panel.screenshot({ path: outputPath("10-f2-review-focused.png") });
assertions.f2ReviewSixColumns = (await f2Panel.locator("thead th").allTextContents()).join("|") === "반영|필드|현재값|제안|상태|근거";
await page1600.locator(".detail-workspace__action-rail").getByRole("button", { name: "상세 닫기" }).click();
const f2DirtyDialog = page1600.getByRole("alertdialog");
await f2DirtyDialog.getByRole("button", { name: "저장 안 함", exact: true }).click();
await page1600.locator(".detail-workspace-modal").waitFor({ state: "detached" });

for (const [stateLabel, expectedText, key] of [
  ["결과 없음", "조건에 맞는 세대가 없습니다", "emptyState"],
  ["불러오기 오류", "매물장을 불러오지 못했습니다", "errorState"],
  ["오프라인", "오프라인 · 변경 내용은 브라우저에 보관됩니다", "offlineState"],
]) {
  await page1600.getByRole("button", { name: "프로토타입 상태 도구" }).click();
  await page1600.getByRole("menuitem", { name: new RegExp(`프로토타입 상태 · ${stateLabel}`) }).click();
  await page1600.getByText(expectedText, { exact: false }).first().waitFor({ state: "visible" });
  assertions[key] = true;
  if (stateLabel === "결과 없음") {
    await page1600.locator(".ledger-grid__overlay").getByRole("button", { name: "모든 필터 해제" }).click();
  } else if (stateLabel === "불러오기 오류") {
    await page1600.locator(".ledger-grid__overlay").getByRole("button", { name: "다시 시도" }).click();
  }
}
await page1600.screenshot({ path: outputPath("11-grid-offline.png") });

const page1366 = await openPage({ width: 1366, height: 768 });
await page1366.screenshot({ path: outputPath("12-grid-1366.png") });
metrics.document1366 = await page1366.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
assertions.noPageOverflow1366 = metrics.document1366.scrollWidth <= metrics.document1366.clientWidth;
await openFirstDetail(page1366);
await page1366.locator(".detail-workspace__action-rail").getByRole("button", { name: "교차 매칭", exact: true }).click();
const f3Panel = page1366.locator(".cross-match-panel");
await f3Panel.scrollIntoViewIfNeeded();
await page1366.locator(".cross-match-panel__prototype-tools > summary").click();
await page1366.locator("#cross-match-state").selectOption("ready");
await f3Panel.getByRole("heading", { name: "강함, 약함, 기각을 함께 검토합니다" }).waitFor({ state: "visible" });
const candidateBox = await page1366.locator(".cross-match-panel__candidates").boundingBox();
const detailBox = await page1366.locator(".cross-match-panel__detail-panel").boundingBox();
metrics.f3Ratio1366 = candidateBox && detailBox ? candidateBox.width / (candidateBox.width + detailBox.width) : 0;
assertions.f3FortySixty = metrics.f3Ratio1366 > 0.35 && metrics.f3Ratio1366 < 0.45;
assertions.f3AllGrades = await Promise.all(["강함", "약함", "기각"].map(async (grade) => (await f3Panel.getByRole("heading", { name: grade, exact: true }).count()) > 0)).then((values) => values.every(Boolean));
assertions.f1ActionsRemainVisibleWithF3 =
  await page1366.locator(".detail-workspace__action-rail").getByRole("button", { name: "저장", exact: true }).isVisible() &&
  await page1366.locator(".detail-workspace__action-rail").getByRole("button", { name: "상세 닫기", exact: true }).isVisible();
await page1366.screenshot({ path: outputPath("13-f3-1366-primary-detail.png") });

await f3Panel.getByRole("button", { name: "문자 작성", exact: true }).click();
const messageModal = page1366.locator(".pf-v6-c-modal-box").filter({ hasText: "문자 작업" });
await messageModal.waitFor({ state: "visible" });
const messageTextareas = messageModal.locator(".message-composer textarea");
assertions.messageTargetAndPhone =
  (await messageModal.locator(".message-composer__recipients input[type=checkbox]").count()) > 0 && Boolean((await messageTextareas.nth(0).inputValue()).trim());
const messageButtonTexts = await messageModal.locator("button").allTextContents();
const copyVisible = await messageModal.locator("button").filter({ hasText: "번호 목록 복사" }).first().isVisible();
assertions.copyOnlyNoSend = copyVisible && messageButtonTexts.every((text) => !["발송", "보내기", "전송", "지금 보내기"].includes(text.trim()));
metrics.messageButtonTexts = messageButtonTexts;
metrics.copyButtonVisible = copyVisible;
await messageModal.screenshot({ path: outputPath("14-message-copy-only.png") });
const expectedPhone = await messageTextareas.nth(0).inputValue();
const copyButton = messageModal.locator("button").filter({ hasText: "번호 목록 복사" }).first();
await copyButton.click();
const copiedPhone = await page1366.evaluate(() => navigator.clipboard.readText());
assertions.phoneCopied = copiedPhone === expectedPhone;
await messageModal.locator("button").filter({ hasText: "닫기" }).first().click();
await messageModal.waitFor({ state: "hidden" });
await f3Panel.scrollIntoViewIfNeeded();

await page1366.locator("#cross-match-state").selectOption("failed");
await f3Panel.locator(".cross-match-panel__state-card").filter({ hasText: "F3만 실패했습니다" }).waitFor({ state: "visible" });
assertions.f3FailureIsolated =
  await page1366.locator(".detail-workspace__action-rail").getByRole("button", { name: "저장", exact: true }).isEnabled() &&
  await page1366.locator(".detail-workspace__action-rail").getByRole("button", { name: "상세 닫기", exact: true }).isEnabled();
await page1366.screenshot({ path: outputPath("15-f3-failure-isolated.png") });

await browser.close();
const passed = Object.values(assertions).every(Boolean) && consoleErrors.length === 0;
const result = { baseUrl, assertions, metrics, consoleErrors, passed };
await fs.writeFile(new URL("workflow-smoke.json", outputDir), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
if (!passed) process.exitCode = 1;
