import { Label } from "@patternfly/react-core";
import { candidateEligibilityLabel } from "./model.ts";
import type { CandidateEligibility } from "./model.ts";

/** 현재 적격성만 표시한다. 저장된 등급·후보 순서·페이지는 바꾸지 않는다. */
export function CandidateEligibilityLabel({
  value,
}: {
  value: CandidateEligibility | null;
}) {
  const label = candidateEligibilityLabel(value);
  return label == null ? null : <Label color="orange">{label}</Label>;
}
