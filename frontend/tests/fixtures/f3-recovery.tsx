import { useState } from "react";
import { createRoot } from "react-dom/client";
import { useCrossJudgment, resetCrossJudgmentCache } from "../../src/features/f3/hooks/useCrossJudgment.ts";
import { f3Transport } from "../../src/features/f3/api/f3Transport.ts";
import { ApiError } from "../../src/shared/api/index.ts";
import { decodeRun, decodeRunResult, decodeRunStatus } from "../../src/features/f3/model/decode.ts";
import { runPayload, resultPayload, statusPayload } from "../../src/features/f3/mock/scenario.ts";
import type { MockRun } from "../../src/features/f3/mock/scenario.ts";

const control = {
  submissions: 0, statusGets: 0, resultGets: 0, status: "JUDGING", resultStatus: "JUDGING",
  failure: "", holdCreate: false, release: () => {},
};
Object.assign(window, { recovery: control });
let currentRun: MockRun;
f3Transport.createRun = async (anchor) => {
  control.submissions += 1;
  const run = {runId: control.submissions, anchorType: anchor.anchorType,
    anchorId: anchor.anchorId, createdAt: Date.now()};
  if (control.holdCreate) await new Promise<void>((resolve) => { control.release = resolve; });
  currentRun = run;
  return decodeRun(runPayload(run, control.status));
};
f3Transport.getRunStatus = async () => {
  control.statusGets += 1;
  if (control.failure === "notFound") throw new ApiError({kind: "notFound", status: 404, message: "실행 없음"});
  return decodeRunStatus(statusPayload(currentRun, control.status));
};
f3Transport.getRunResult = async (_runId, page) => {
  control.resultGets += 1;
  if (control.failure === "network") throw new ApiError({kind: "network", message: "연결 끊김"});
  return decodeRunResult(resultPayload(currentRun, control.resultStatus,
    {limit: page?.limit ?? 20, offset: page?.offset ?? 0}));
};
function Harness() {
  const [enabled, setEnabled] = useState(false);
  const [version, setVersion] = useState(1);
  const value = useCrossJudgment({anchorType:"LISTING", anchorId:1, dataVersion:version, enabled});
  return <>
    <button onClick={() => setEnabled(true)}>열기</button>
    <button onClick={() => setEnabled(false)}>닫기</button>
    <button onClick={value.resume}>다시 확인</button>
    <button onClick={value.rerun}>다시 판정</button>
    <button onClick={() => value.setOffset(20)}>다음 페이지</button>
    <button onClick={() => setVersion(v => v + 1)}>버전 변경</button>
    <button onClick={() => {resetCrossJudgmentCache(); setEnabled(false);}}>세션 종료</button>
    <output id="state">{value.state}</output>
    <output id="run">{value.runId}</output>
    <output id="resume">{String(value.canResume)}</output>
  </>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
