import { chromium } from "playwright";
import fs from "node:fs/promises";

const baseUrl = process.env.PROTOTYPE_URL || "http://127.0.0.1:4173/";
const outputDir = new URL("../artifacts/", import.meta.url);
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const results = {};
const consoleErrors = [];

for (const viewport of [
  { width: 1600, height: 900, name: "1600" },
  { width: 1366, height: 768, name: "1366" },
]) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(`${viewport.name}: ${message.text()}`);
  });
  page.on("pageerror", (error) => consoleErrors.push(`${viewport.name}: ${error.message}`));

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator(".ag-root-wrapper").waitFor({ state: "visible" });

  const [topbar, controls, grid, status] = await Promise.all([
    page.locator(".f1-topbar").boundingBox(),
    page.locator(".f1-control-strip").boundingBox(),
    page.locator(".ledger-grid").boundingBox(),
    page.locator(".grid-statusbar").boundingBox(),
  ]);
  const dimensions = await page.evaluate(() => ({
    documentScrollWidth: document.documentElement.scrollWidth,
    documentClientWidth: document.documentElement.clientWidth,
    controlScrollWidth: document.querySelector(".f1-control-strip")?.scrollWidth || 0,
    controlClientWidth: document.querySelector(".f1-control-strip")?.clientWidth || 0,
  }));

  const assertions = {
    compactTopbar: Boolean(topbar && topbar.y === 0 && topbar.height <= 50 && Math.abs(topbar.width - viewport.width) < 1),
    oneControlStrip: Boolean(controls && controls.y >= 47 && controls.y <= 50 && controls.height <= 58),
    gridStartsImmediately: Boolean(grid && controls && grid.y >= controls.y + controls.height - 1 && grid.y <= controls.y + controls.height + 2),
    gridUsesWorkspace: Boolean(grid && grid.width >= viewport.width - 1 && grid.height >= viewport.height - 140),
    bottomStatusVisible: Boolean(status && status.y + status.height <= viewport.height + 1),
    noPersistentSideNav: (await page.locator(".side-nav").count()) === 0,
    noLargePageHeading: (await page.locator(".page-heading").count()) === 0,
    topbarContent: await page.getByText("F1 장부", { exact: true }).isVisible()
      && await page.getByRole("tab", { name: "매물장", exact: true }).isVisible()
      && await page.getByLabel("동·호 조회").isVisible()
      && await page.getByLabel("통합 검색").isVisible(),
    controlsStayInternal: dimensions.documentScrollWidth === dimensions.documentClientWidth
      && dimensions.controlScrollWidth >= dimensions.controlClientWidth,
  };

  await page.screenshot({
    path: new URL(`17-f1-compact-layout-${viewport.name}.png`, outputDir).pathname,
  });

  await page.getByRole("button", { name: "프로토타입 상태 도구" }).click();
  await page.getByRole("menuitem", { name: /프로토타입 상태 · 오프라인/ }).click();
  const offlineBannerLocator = page.locator(".offline-banner");
  await offlineBannerLocator.waitFor({ state: "visible" });
  const [offlineBanner, offlineControls, offlineGrid] = await Promise.all([
    offlineBannerLocator.boundingBox(),
    page.locator(".f1-control-strip").boundingBox(),
    page.locator(".ledger-grid").boundingBox(),
  ]);
  const offlineDimensions = await page.evaluate(() => ({
    documentScrollWidth: document.documentElement.scrollWidth,
    documentClientWidth: document.documentElement.clientWidth,
  }));
  assertions.offlineSingleBanner = (await offlineBannerLocator.count()) === 1
    && (await page.locator(".ledger-grid__offline-alert").count()) === 0;
  assertions.offlineBannerDoesNotOverlap = Boolean(
    offlineBanner && offlineControls && offlineGrid
    && offlineBanner.y >= 47
    && offlineBanner.y + offlineBanner.height <= offlineControls.y + 1
    && offlineControls.y + offlineControls.height <= offlineGrid.y + 1,
  );
  assertions.offlineNoPageOverflow = offlineDimensions.documentScrollWidth <= offlineDimensions.documentClientWidth;
  await page.screenshot({
    path: new URL(`18-f1-offline-layout-${viewport.name}.png`, outputDir).pathname,
  });

  results[viewport.name] = {
    assertions,
    metrics: { topbar, controls, grid, status, offlineBanner, offlineControls, offlineGrid, ...dimensions, offlineDimensions },
  };
  await page.close();
}

await browser.close();
const passed = Object.values(results).every((result) => Object.values(result.assertions).every(Boolean))
  && consoleErrors.length === 0;
const output = { baseUrl, results, consoleErrors, passed };
await fs.writeFile(new URL("f1-layout-smoke.json", outputDir), JSON.stringify(output, null, 2));
console.log(JSON.stringify(output, null, 2));
if (!passed) process.exitCode = 1;
