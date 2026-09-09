import { useState } from "react";
import { createRoot } from "react-dom/client";
import { useCrossJudgment } from "../../src/features/f3/hooks/useCrossJudgment.ts";
import { f3Transport } from "../../src/features/f3/api/f3Transport.ts";

let submissions = 0;
const original = f3Transport.createRun.bind(f3Transport);
f3Transport.createRun = async (...args) => {
  submissions += 1;
  return original(...args);
};
function Harness() {
  const [version, setVersion] = useState(1);
  const [enabled, setEnabled] = useState(false);
  const judgment = useCrossJudgment({ anchorType: "LISTING", anchorId: 1, dataVersion: version, enabled });
  return <>
    <button onClick={() => setEnabled(true)}>판정 열기</button>
    <button onClick={() => setVersion((current) => current + 1)}>외부 버전 갱신</button>
    <button onClick={judgment.retry}>명시적 재판정</button>
    <output id="lifecycle-state">{judgment.state}</output>
    <output id="lifecycle-count">{submissions}</output>
  </>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
