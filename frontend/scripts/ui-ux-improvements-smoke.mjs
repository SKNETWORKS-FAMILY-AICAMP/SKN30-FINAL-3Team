import { chromium } from "playwright";
import fs from "node:fs/promises";

const baseUrl = process.env.PROTOTYPE_URL || "http://127.0.0.1:4173/";
const outputDir = new URL("../artifacts/", import.meta.url);
const outputPath = (name) => new URL(name, outputDir).pathname;
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
const assertions = {};
const metrics = {};
const consoleErrors = [];

function observe(page, name) {
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`${name}: ${message.text()}`); });
  page.on("pageerror", (error) => consoleErrors.push(`${name}: ${error.message}`));
}

async function pageAt(width, height, name) {
  const page = await context.newPage();
  await page.setViewportSize({ width, height });
  observe(page, name);
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator(".ag-root-wrapper").waitFor({ state: "visible" });
  return page;
}

async function layoutMetrics(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    under12: Array.from(document.querySelectorAll("body *")).filter((node) => {
      const style = getComputedStyle(node);
      const ownText = Array.from(node.childNodes).some((child) => child.nodeType === Node.TEXT_NODE && child.textContent.trim());
      return ownText && style.display !== "none" && style.visibility !== "hidden" && !node.closest(".pf-v6-screen-reader") && Number.parseFloat(style.fontSize) < 11.9;
    }).map((node) => node.textContent.trim()).slice(0, 12),
  }));
}

const page1600 = await pageAt(1600, 900, "1600");
metrics.ledger1600 = await layoutMetrics(page1600);
assertions.noOverflow1600 = metrics.ledger1600.scrollWidth === metrics.ledger1600.clientWidth;
assertions.noUnder12At1600 = metrics.ledger1600.under12.length === 0;
await page1600.screenshot({ path: outputPath("21-uiux-ledger-1600.png") });
await page1600.close();

const page = await pageAt(1366, 768, "1366");
metrics.ledger1366 = await layoutMetrics(page);
assertions.noOverflow1366 = metrics.ledger1366.scrollWidth === metrics.ledger1366.clientWidth;
assertions.noUnder12At1366 = metrics.ledger1366.under12.length === 0;
assertions.migrationRemoved = await page.getByRole("button", { name: "데이터 이관", exact: true }).count() === 0 && await page.locator('[data-screen-id="F1-PG-130"]').count() === 0;
assertions.prototypeStatesDisclosed = await page.locator(".state-switcher").count() === 0 && await page.getByRole("button", { name: "프로토타입 상태 도구" }).isVisible();
assertions.unsupportedLedgerTabsDisabled = await Promise.all(["상가", "주택", "재건축"].map((name) => page.getByRole("tab", { name, exact: true }).isDisabled())).then((values) => values.every(Boolean));
await page.screenshot({ path: outputPath("22-uiux-ledger-1366.png") });

await page.getByRole("button", { name: /래미안 원베일리 101동 203호 상세 열기/ }).first().click();
const detail = page.locator(".detail-workspace-modal");
await detail.waitFor({ state: "visible" });
const nav = detail.locator(".detail-section-nav");
assertions.detailSectionOrientation = await nav.isVisible() && (await nav.getByRole("button").count()) >= 5;
const dirtyBox = await detail.locator(".action-rail__dirty").boundingBox();
const saveBox = await detail.locator(".detail-workspace__action-rail").getByRole("button", { name: "저장", exact: true }).boundingBox();
assertions.saveStateBeforeActions = Boolean(dirtyBox && saveBox && dirtyBox.y < saveBox.y);
await nav.getByRole("button", { name: "비고", exact: true }).click();
await page.waitForFunction(() => document.activeElement?.id === "detail-memo-heading");
assertions.sectionNavMovesFocus = true;
await page.screenshot({ path: outputPath("23-uiux-detail-1366.png") });
metrics.detail1366 = await layoutMetrics(page);
assertions.detailNoUnder12At1366 = metrics.detail1366.under12.length === 0;

await detail.getByRole("button", { name: "음성메모 입력", exact: true }).click();
const f2 = detail.locator("#f2-panel");
await f2.getByRole("button", { name: /상담 후 음성메모 녹음/ }).click();
await f2.getByRole("button", { name: "녹음 종료", exact: true }).click();
await f2.getByRole("button", { name: "분석 시작", exact: true }).click();
await f2.getByRole("table", { name: "음성메모 분석 제안" }).waitFor({ state: "visible", timeout: 8000 });
assertions.f2DecisionSummary = await f2.locator(".f2-review__summary").isVisible() && (await f2.locator(".f2-review__summary").innerText()).includes("결정 필요");
assertions.f2PrimaryAfterTable = await f2.locator(".f2-review__action-bar").isVisible() && await f2.getByRole("button", { name: /선택 항목 반영/ }).isVisible();
await page.screenshot({ path: outputPath("24-uiux-f2-review-1366.png") });

await detail.locator(".detail-workspace__action-rail").getByRole("button", { name: "교차 매칭", exact: true }).click();
const f3 = detail.locator(".cross-match-panel");
await f3.waitFor({ state: "visible" });
const prototypeTools = f3.locator(".cross-match-panel__prototype-tools");
assertions.f3PrototypeToolsCollapsed = !(await prototypeTools.getAttribute("open"));
await prototypeTools.locator("summary").click();
await f3.locator("#cross-match-state").selectOption("ready");
await f3.getByRole("heading", { name: "강함, 약함, 기각을 함께 검토합니다" }).waitFor({ state: "visible" });
await prototypeTools.locator("summary").click();
assertions.f3RecommendationVisible = await f3.locator(".cross-match-panel__recommendation").isVisible();
assertions.f3OnePrimaryAction = await f3.getByRole("button", { name: "문자 작성", exact: true }).isVisible() && !(await f3.locator(".cross-match-panel__more-actions").getAttribute("open"));
await page.screenshot({ path: outputPath("25-uiux-f3-1366.png") });
metrics.f3Detail1366 = await layoutMetrics(page);
assertions.f3NoUnder12At1366 = metrics.f3Detail1366.under12.length === 0;

await f3.getByRole("button", { name: "문자 작성", exact: true }).click();
const composer = page.locator(".message-composer");
await composer.waitFor({ state: "visible" });
assertions.composerHierarchy = await composer.locator(".message-composer__context").isVisible() && (await composer.locator(".message-composer__details").count()) === 2 && (await composer.locator(".message-composer__draft-label").innerText()).includes("자");
await page.screenshot({ path: outputPath("26-uiux-message-1366.png") });
metrics.message1366 = await layoutMetrics(page);
assertions.messageNoUnder12At1366 = metrics.message1366.under12.length === 0;
await page.close();

const campaignPage = await pageAt(1366, 768, "campaign-1366");
const rowCheckboxes = campaignPage.getByRole("checkbox", { name: /Space 키로 행 선택 전환/ });
for (let index = 0; index < 12; index += 1) await rowCheckboxes.nth(index).click();
await campaignPage.getByRole("button", { name: "F3 캠페인", exact: true }).click();
const campaign = campaignPage.locator(".campaign-workspace");
await campaign.waitFor({ state: "visible" });
assertions.campaignProgressBeforeRun = (await campaign.locator(".campaign-workspace__progress").innerText()).includes("대상 확인") && await campaign.locator(".campaign-workspace__progress li").nth(0).evaluate((node) => node.classList.contains("is-current"));
await campaign.getByRole("button", { name: "선택 대상 판정", exact: true }).click();
assertions.campaignProgressAfterRun = await campaign.locator(".campaign-workspace__progress li").nth(1).evaluate((node) => node.classList.contains("is-current")) && await campaign.locator(".campaign-workspace__card.is-ready").isVisible();
await campaignPage.screenshot({ path: outputPath("27-uiux-campaign-1366.png") });

metrics.final1366 = await layoutMetrics(campaignPage);
assertions.finalNoOverflow1366 = metrics.final1366.scrollWidth === metrics.final1366.clientWidth;
assertions.finalNoUnder12At1366 = metrics.final1366.under12.length === 0;
await campaignPage.close();

await browser.close();
const passed = Object.values(assertions).every(Boolean) && consoleErrors.length === 0;
const result = { baseUrl, assertions, metrics, consoleErrors, passed };
await fs.writeFile(new URL("ui-ux-improvements-smoke.json", outputDir), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
if (!passed) process.exitCode = 1;
