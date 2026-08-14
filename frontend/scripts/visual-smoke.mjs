import { chromium } from "playwright";
import fs from "node:fs/promises";

const baseUrl = process.env.PROTOTYPE_URL || "http://127.0.0.1:4173/";
const outputDir = new URL("../artifacts/", import.meta.url);
const outputPath = (name) => new URL(name, outputDir).pathname;
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(error.message));

await page.goto(baseUrl, { waitUntil: "networkidle" });
await page.screenshot({ path: outputPath("01-grid-default.png"), fullPage: true });

const assertions = {
  heading: await page.getByRole("heading", { name: "매물장" }).isVisible(),
  grid: await page.locator(".ag-root-wrapper").isVisible(),
  rows: (await page.locator(".ag-row").count()) > 0,
  saveHeader: await page.getByText("저장 상태", { exact: true }).first().isVisible(),
  aiHeader: await page.getByText("AI 처리 상태", { exact: true }).first().isVisible(),
};

await page.getByRole("button", { name: "래미안 원베일리" }).first().click();
await page.waitForTimeout(400);
await page.screenshot({ path: outputPath("02-detail-default.png"), fullPage: true });
assertions.detailOpen = await page.getByText("세대 상세", { exact: false }).first().isVisible().catch(() => false);

const voiceButton = page.getByRole("button", { name: /녹음 시작|음성메모 녹음/ }).first();
if (await voiceButton.isVisible().catch(() => false)) {
  await voiceButton.click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: outputPath("03-f2-recording.png"), fullPage: true });
  assertions.f2Recording = await page.getByText(/녹음 중/).first().isVisible().catch(() => false);
}

const crossButton = page.getByRole("button", { name: /교차 매칭|교차 판정|추천 후보|후보 판정/ }).first();
if (await crossButton.isVisible().catch(() => false)) {
  await crossButton.click();
  await page.locator(".cross-match-panel").scrollIntoViewIfNeeded();
  await page.locator(".cross-match-panel__prototype-tools > summary").click();
  await page.locator("#cross-match-state").selectOption("ready");
  await page.waitForTimeout(250);
  await page.screenshot({ path: outputPath("04-f3-primary-detail.png"), fullPage: true });
  assertions.f3Open = await page.getByText(/강함/).first().isVisible().catch(() => false);
}

await browser.close();

const result = { baseUrl, assertions, consoleErrors, passed: Object.values(assertions).every(Boolean) && consoleErrors.length === 0 };
await fs.writeFile(new URL("visual-smoke.json", outputDir), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
if (!result.passed) process.exitCode = 1;
