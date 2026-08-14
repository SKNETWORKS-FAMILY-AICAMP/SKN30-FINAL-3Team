import { chromium } from "playwright";
import fs from "node:fs/promises";

const baseUrl = process.env.PROTOTYPE_URL || "http://127.0.0.1:4173/";
const outputDir = new URL("../artifacts/", import.meta.url);
await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const consoleErrors = [];
const assertions = {};

const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`1600: ${message.text()}`); });
page.on("pageerror", (error) => consoleErrors.push(`1600: ${error.message}`));
await page.goto(baseUrl, { waitUntil: "networkidle" });
await page.locator(".ag-root-wrapper").waitFor({ state: "visible" });
assertions.migrationEntryRemoved = await page.getByRole("button", { name: "데이터 이관", exact: true }).count() === 0;
assertions.migrationScreenRemoved = await page.locator('[data-screen-id="F1-PG-130"]').count() === 0;

await page.getByRole("button", { name: /래미안 원베일리 101동 203호 상세 열기/ }).first().click();
const detail = page.locator(".detail-workspace-modal");
await detail.waitFor({ state: "visible" });
const personSelect = detail.locator("#detail-log-person");
await personSelect.scrollIntoViewIfNeeded();
assertions.personOptionsFollowRoleOrder = await personSelect.locator('option[value="owner:0"]').innerText() === "임대인 ① · 박이서" && await personSelect.locator('option[value="owner:1"]').innerText() === "임대인 ② · 송경련";
await personSelect.selectOption("owner:1");
const log = detail.locator("#detail-log");
await log.fill("아내와 매도 조건 재확인");
assertions.manualLogAutoIndex = (await log.inputValue()).startsWith("②") && (await detail.locator(".detail-log-person-index__status").innerText()).includes("임대인 등록 2번");
await personSelect.selectOption("");
assertions.unspecifiedDoesNotAssumeFirst = !(await log.inputValue()).startsWith("①") && (await detail.locator(".detail-log-person-index__status").innerText()).includes("상대 미지정");
await personSelect.selectOption("owner:1");
await detail.getByRole("button", { name: "음성메모 입력", exact: true }).click();
const f2 = detail.locator("#f2-panel");
await f2.getByRole("button", { name: /상담 후 음성메모 녹음/ }).click();
await f2.getByRole("button", { name: "녹음 종료", exact: true }).click();
await f2.getByRole("button", { name: "분석 시작", exact: true }).click();
await f2.getByRole("table", { name: "음성메모 분석 제안" }).waitFor({ state: "visible", timeout: 8000 });
const logProposalRow = f2.locator("tbody tr").filter({ hasText: "상담 로그" }).first();
assertions.f2GeneratedLogUsesSelectedIndex = (await logProposalRow.locator('td[data-label="제안"]').innerText()).startsWith("②");
await page.screenshot({ path: new URL("19-fifth-requirements-person-index-1600.png", outputDir).pathname, fullPage: false });

await browser.close();
const passed = Object.values(assertions).every(Boolean) && consoleErrors.length === 0;
const result = { baseUrl, assertions, consoleErrors, passed };
await fs.writeFile(new URL("fifth-requirements-smoke.json", outputDir), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
if (!passed) process.exitCode = 1;
