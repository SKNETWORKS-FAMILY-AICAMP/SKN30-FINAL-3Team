/** 실제 DB·모델 없이 화면 표시 경계에 내부 필드명을 공급한다. */
export async function openEvidencePanel(page, baseUrl, kind) {
  await page.addInitScript(() => {
    localStorage.setItem("time-keeper.last-briefing", new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10));
  });
  await page.goto(baseUrl);
  await page.getByRole("button", { name: "매물장", exact: true }).waitFor();
  await page.evaluate(async () => {
    const { f3Transport } = await import("/src/features/f3/api/f3Transport.ts");
    const { runPayload, statusPayload, resultPayload } = await import("/src/features/f3/mock/scenario.ts");
    const { decodeRun, decodeRunStatus, decodeRunResult } = await import("/src/features/f3/model/decode.ts");
    let run;
    window.evidenceSubmissions = 0;
    f3Transport.createRun = async anchor => {
      window.evidenceSubmissions++;
      run = { runId: 91, anchorType: anchor.anchorType, anchorId: anchor.anchorId, createdAt: Date.now() };
      return decodeRun(runPayload(run, "COMPLETED"));
    };
    f3Transport.getRunStatus = async () => decodeRunStatus(statusPayload(run, "COMPLETED"));
    f3Transport.getRunResult = async (_id, pagination) => {
      const result = resultPayload(run, "COMPLETED", pagination);
      result.candidates[0].evaluation_basis = "희망 입주일과 timing.hard_deadline 2027-05-07이 일치해 시점 조율 부담이 작다.";
      result.candidates[0].evidence = [
        ["timing.hard_deadline", "현 임차인 계약 만료 후 입주 조건과 hard_deadline 2027-05-07이 확인된다."],
        ["timing.constraints", "후보의 희망 입주일이 2027-05-07로 기재되어 입주 가능 시점과 일치한다."],
        ["price.stated_amount", "후보 예산은 8천만원이고 매물 표기 보증금은 5천만원으로 가격 기준의 확인이 필요하다."],
        ["future.internal_key", "추가 상담을 통해 조건을 확인한다."],
      ].map(([field_name, note]) => ({ field_name, note, evidence_type: "INFERENCE", evidence_side: "ANCHOR",
        interaction_id: null, quote_text: null, quote_start_offset: null, quote_end_offset: null }));
      return decodeRunResult(result);
    };
  });
  await page.getByRole("button", { name: kind === "listing" ? "매물장" : "구입장", exact: true }).click();
  if (kind === "listing") await page.locator(".ledger-grid__detail-link").nth(1).click();
  else await page.locator('.buyer-ledger-grid .ag-row [col-id="buyer"]').first().click();
  const opener = page.getByRole("button", { name: kind === "listing" ? "교차 판정 실행" : "교차 판정", exact: true });
  await opener.click();
  await page.locator(".cross-match-panel__evidence-field").first().waitFor();
  return opener;
}
