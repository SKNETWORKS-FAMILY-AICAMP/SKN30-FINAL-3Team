import { Label } from "@patternfly/react-core";
import type { JudgmentTarget } from "./model.ts";
import { dateLabel } from "./model.ts";
export function TargetStatus({
  target,
  snapshotOutdated = false,
}: {
  target: JudgmentTarget;
  snapshotOutdated?: boolean;
}) {
  const s = target.summary;
  return (
    <div className="f3-judgments__status" aria-live="polite">
      {target.is_synthetic_fixture && (
        <>
          <Label color="purple">시드 예시 결과</Label>
          <span>실제 모델 추론 결과가 아닙니다.</span>
        </>
      )}
      <Label
        color={
          target.freshness === "CURRENT" && !snapshotOutdated ? "green" : "grey"
        }
      >
        {snapshotOutdated
          ? "이전 조회 · 목록 갱신 필요"
          : target.freshness === "CURRENT"
            ? "최신 분석"
            : target.freshness === "STALE"
              ? "이전 분석"
              : "분석 전"}
      </Label>
      {target.generation !== "IDLE" && (
        <Label color={target.generation === "FAILED" ? "red" : "blue"}>
          {{ QUEUED: "대기 중", RUNNING: "분석 중", FAILED: "분석 실패" }[
            target.generation
          ] ?? "상태 확인 중"}
        </Label>
      )}
      {target.eligibility !== "ELIGIBLE" && (
        <span>{target.eligibility_reason ?? "원장 정보 확인 필요"}</span>
      )}
      {target.content_availability === "UNAVAILABLE" &&
      target.result_id != null ? (
        <span>결과를 공개할 수 없습니다. 원장 정보를 확인해 주세요.</span>
      ) : s ? (
        <span>
          조건 후보 {s.total_count} ·{" "}
          {target.is_synthetic_fixture ? "예시 판정" : "AI 판정"} {s.judged_count} · 미판정{" "}
          {s.unjudged_count} · 강함 {s.strong_count} · 약함 {s.weak_count} ·
          기각 {s.rejected_count}
        </span>
      ) : (
        <span>판정 건수 미확정</span>
      )}
      <span>분석 기준 {dateLabel(target.generated_at)}</span>
    </div>
  );
}
