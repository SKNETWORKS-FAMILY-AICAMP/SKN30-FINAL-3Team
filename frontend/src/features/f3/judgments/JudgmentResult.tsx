import { useEffect, useState } from "react";
import { Alert, Button, Label, Skeleton } from "@patternfly/react-core";
import { ApiError, isCanceled } from "../../../shared/api/index.ts";
import { judgmentApi } from "./api.ts";
import { CandidateEligibilityLabel } from "./CandidateEligibilityLabel.tsx";
import { CandidateDetail } from "./CandidateDetail.tsx";
import type { OpenLedger } from "./CandidateDetail.tsx";
import type { JudgmentDetail } from "./model.ts";
import { gradeLabel } from "./model.ts";
import type { JudgmentSelection } from "./navigation.ts";
import {
  isDenied,
  isInvalidCursor,
  judgmentError,
  useJudgmentTarget,
} from "./useJudgmentTarget.ts";
import { TargetStatus } from "./TargetStatus.tsx";
export function JudgmentResult({
  selection,
  onSelection,
  onOpenLedger,
  onSessionExpired,
}: {
  selection: JudgmentSelection;
  onSelection: (selection: JudgmentSelection) => void;
  onOpenLedger?: OpenLedger;
  onSessionExpired?: () => void;
}) {
  const live = useJudgmentTarget(
    selection.anchor_type,
    selection.anchor_id,
    true,
    onSessionExpired,
  );
  const [detail, setDetail] = useState<JudgmentDetail | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState("");
  const [pageNotice, setPageNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState<string | undefined>();
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [refresh, setRefresh] = useState(0);
  const resultId = selection.result_id ?? live.target?.result_id ?? null;
  useEffect(() => {
    setDetail(null);
    setUnavailable(false);
    setCursor(undefined);
    setHistory([]);
  }, [selection.anchor_type, selection.anchor_id, resultId]);
  useEffect(() => {
    if (resultId == null) return;
    const c = new AbortController();
    setLoading(true);
    setError("");
    void judgmentApi
      .detail(
        resultId,
        { candidate_id: selection.candidate_id, cursor },
        c.signal,
      )
      .then((value) => {
        if (!c.signal.aborted) {
          setDetail(value);
          setUnavailable(false);
        }
      })
      .catch((cause) => {
        if (c.signal.aborted || isCanceled(cause)) return;
        if (isInvalidCursor(cause) && cursor != null) {
          setCursor(undefined);
          setHistory([]);
          setPageNotice(
            "후보 목록이 변경되어 첫 페이지로 돌아왔습니다. 선택 후보는 유지했습니다.",
          );
          return;
        }
        if (isDenied(cause)) {
          setDetail(null);
          setUnavailable(true);
        }
        setError(judgmentError(cause));
        if (cause instanceof ApiError && cause.kind === "unauthorized")
          onSessionExpired?.();
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [resultId, selection.candidate_id, cursor, refresh, onSessionExpired]);
  const target = live.target;
  const selected =
    detail?.selected_candidate ??
    detail?.candidates.find((c) => c.candidate_id === selection.candidate_id) ??
    detail?.candidates[0];
  const currentId = target?.result_id ?? detail?.current_result_id;
  const currentSnapshot = currentId === resultId;
  const stale =
    !currentSnapshot ||
    target?.freshness !== "CURRENT" ||
    detail?.freshness !== "CURRENT";
  if (live.unavailable || unavailable)
    return (
      <Alert
        variant="warning"
        isInline
        title="대상이 없거나 현재 접근할 수 없습니다."
      />
    );
  return (
    <section className="f3-judgments__result" aria-label="교차 판정 결과 상세">
      <h2>
        {target?.anchor.display_name ??
          detail?.anchor.display_name ??
          "교차 판정 결과"}
      </h2>
      {target && (
        <>
          <p>
            현재 조건 {target.anchor.current_conditions ?? "미기재"} · 담당자{" "}
            {target.anchor.assignee_name ?? "미지정"}
          </p>
          <TargetStatus target={target} />
        </>
      )}
      {pageNotice && <Alert variant="info" isInline title={pageNotice} />}
      {(live.error || error) && (
        <Alert variant="warning" isInline title={live.error || error}>
          <Button
            variant="link"
            isInline
            onClick={() => {
              live.reload();
              setRefresh((v) => v + 1);
            }}
          >
            다시 조회
          </Button>
        </Alert>
      )}
      <div className="f3-judgments__actions">
        <Button
          variant="secondary"
          onClick={() => {
            live.reload();
            setRefresh((v) => v + 1);
          }}
          isDisabled={loading || live.loading}
        >
          결과 새로고침
        </Button>
        {target?.eligibility === "ELIGIBLE" &&
          target.freshness !== "CURRENT" &&
          !["QUEUED", "RUNNING"].includes(target.generation) && (
            <Button
              variant="primary"
              isLoading={live.sending}
              isDisabled={live.sending}
              onClick={() => void live.ensure()}
            >
              최신 분석 요청
            </Button>
          )}
        {target && onOpenLedger && (
          <Button variant="link" onClick={() => onOpenLedger(target.anchor)}>
            현재 원장 확인
          </Button>
        )}
      </div>
      {live.paused && (
        <Alert variant="info" isInline title="자동 확인을 잠시 멈췄습니다">
          서버 작업은 계속 진행될 수 있습니다. 결과 새로고침으로 확인할 수
          있습니다.
        </Alert>
      )}
      {currentId != null && !currentSnapshot && (
        <Alert variant="info" isInline title="더 최신 분석이 있습니다">
          <Button
            variant="link"
            isInline
            onClick={() =>
              onSelection({
                ...selection,
                result_id: currentId,
                candidate_id: undefined,
              })
            }
          >
            최신 분석 보기
          </Button>
        </Alert>
      )}
      {(loading || live.loading) && !detail && (
        <Skeleton screenreaderText="저장된 판정 조회 중" />
      )}
      {!loading && !live.loading && resultId == null && !live.error && (
        <p>저장된 판정이 없습니다. 분석 상태와 원장 정보를 확인해 주세요.</p>
      )}
      {detail && target && (
        <>
          <h3>
            분석 당시 결과 {stale && <Label color="orange">이전 분석</Label>}
          </h3>
          <TargetStatus
            target={{
              ...detail,
              freshness: stale ? "STALE" : detail.freshness,
            }}
          />
          {detail.content_availability === "UNAVAILABLE" ? (
            <Alert
              variant="info"
              isInline
              title="현재 공개할 수 없는 결과입니다"
            >
              현재 원장 정보를 확인해 주세요.
            </Alert>
          ) : (
            <>
              {detail.candidates.length === 0 && (
                <p>저장된 조건 후보가 없습니다.</p>
              )}
              {detail.summary &&
                detail.summary.judged_count > 0 &&
                detail.summary.strong_count + detail.summary.weak_count ===
                  0 && (
                  <p>
                    AI 판정한 후보에는 연결 추천이 없습니다. 미판정 조건 후보{" "}
                    {detail.summary.unjudged_count}건은 기각이 아닙니다.
                  </p>
                )}
              <div
                className="f3-judgments__candidate-list"
                aria-label="후보 선택"
              >
                {detail.candidates.map((candidate) => (
                  <Button
                    key={candidate.candidate_id}
                    variant={
                      selected?.candidate_id === candidate.candidate_id
                        ? "secondary"
                        : "link"
                    }
                    aria-pressed={
                      selected?.candidate_id === candidate.candidate_id
                    }
                    onClick={() =>
                      onSelection({
                        ...selection,
                        result_id: resultId,
                        candidate_id: candidate.candidate_id,
                      })
                    }
                  >
                    {candidate.target.display_name} ·{" "}
                    {gradeLabel(candidate.match_grade)} · 담당{" "}
                    {candidate.target.assignee_name ?? "미지정"}{" "}
                    <CandidateEligibilityLabel value={candidate.current_eligibility} />
                  </Button>
                ))}
              </div>
              <div className="f3-judgments__actions">
                <Button
                  variant="secondary"
                  isDisabled={history.length === 0 || loading}
                  onClick={() => {
                    setCursor(history.at(-1));
                    setHistory((h) => h.slice(0, -1));
                  }}
                >
                  이전 후보
                </Button>
                <span>후보 페이지 {history.length + 1}</span>
                <Button
                  variant="secondary"
                  isDisabled={!detail.next_cursor || loading}
                  onClick={() => {
                    setHistory((h) => [...h, cursor]);
                    setCursor(detail.next_cursor ?? undefined);
                  }}
                >
                  다음 후보
                </Button>
              </div>
              {selected && (
                <CandidateDetail
                  key={`${resultId}-${selected.candidate_id}`}
                  candidate={selected}
                  anchor={detail.anchor}
                  anchorCard={detail.anchor_card}
                  stale={stale}
                  onOpenLedger={onOpenLedger}
                  onRecorded={() => setRefresh((v) => v + 1)}
                  onAccessDenied={() => {
                    setDetail(null);
                    setUnavailable(true);
                  }}
                  onSessionExpired={onSessionExpired}
                />
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
