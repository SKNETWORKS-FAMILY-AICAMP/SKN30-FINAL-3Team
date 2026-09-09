/** Saved target summary is a GET. Expanding it never submits a model task. */
import { useEffect, useRef, useState } from "react";
import { Alert, Button, Skeleton } from "@patternfly/react-core";
import type { AnchorRowView } from "./CrossMatchPanel.tsx";
import type { ParentContext } from "./model/viewModel.ts";
import type { AnchorType } from "./model/dto.ts";
import { JudgmentResult } from "./judgments/JudgmentResult.tsx";
import type { JudgmentSelection } from "./judgments/navigation.ts";
import { TargetStatus } from "./judgments/TargetStatus.tsx";
import { useJudgmentTarget } from "./judgments/useJudgmentTarget.ts";
import "./judgments/Judgments.css";
export interface DetailRow extends AnchorRowView {
  serverId?: number | null;
  rowVersion?: number | null;
  listingId?: number | null;
  listingRowVersion?: number | null;
}
export interface CrossMatchSectionProps {
  isOpen: boolean;
  onClose: () => void;
  row: DetailRow | null;
  parentContext: ParentContext;
  focusRequest?: number;
  onSessionExpired?: () => void;
}
export function CrossMatchSection({
  isOpen,
  onClose,
  row,
  parentContext,
  focusRequest = 0,
  onSessionExpired,
}: CrossMatchSectionProps) {
  const type: AnchorType =
    parentContext === "buyer-detail" ? "REQUIREMENT" : "LISTING";
  const id = (type === "LISTING" ? row?.listingId : row?.serverId) ?? null;
  const [selection, setSelection] = useState<JudgmentSelection | null>(null);
  const [expanded, setExpanded] = useState(false);
  const title = useRef<HTMLHeadingElement>(null);
  const live = useJudgmentTarget(
    id == null ? null : type,
    id,
    row != null && !isOpen && !expanded,
    onSessionExpired,
  );
  useEffect(() => {
    setSelection(null);
    setExpanded(false);
    live.reload();
  }, [id, type, row?.rowVersion, row?.listingRowVersion]);
  useEffect(() => {
    if (isOpen && id != null) {
      setExpanded(true);
      setSelection(
        (s) => s ?? { anchor_type: type, anchor_id: id, result_id: null },
      );
      requestAnimationFrame(() => title.current?.focus());
    }
  }, [isOpen, focusRequest, type, id]);
  if (!row) return null;
  return (
    <section
      className="f3-target-summary"
      id="cross-match-panel"
      aria-label="저장된 교차 판정"
    >
      <h2 id="cross-match-panel-title" ref={title} tabIndex={-1}>
        교차 판정
      </h2>
      {id == null ? (
        <p>
          {type === "LISTING"
            ? "저장된 매물 건을 먼저 선택해 주세요. 세대만으로는 판정하지 않습니다."
            : "구입장을 먼저 저장해 주세요."}
        </p>
      ) : (
        <>
          {!expanded && (
            <>
              {live.loading && !live.target && (
                <Skeleton screenreaderText="판정 요약 조회 중" />
              )}
              {live.target && <TargetStatus target={live.target} />}
              {live.error && (
                <Alert variant="warning" isInline title={live.error} />
              )}
              <div className="f3-judgments__actions">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSelection({
                      anchor_type: type,
                      anchor_id: id,
                      result_id: live.target?.result_id ?? null,
                    });
                    setExpanded(true);
                  }}
                >
                  결과 보기
                </Button>
                <Button variant="link" onClick={live.reload}>
                  요약 새로고침
                </Button>
                {live.target?.eligibility === "ELIGIBLE" &&
                  live.target.freshness !== "CURRENT" &&
                  !["QUEUED", "RUNNING"].includes(live.target.generation) && (
                    <Button
                      variant="primary"
                      isDisabled={live.sending}
                      isLoading={live.sending}
                      onClick={() => void live.ensure()}
                    >
                      최신 분석 요청
                    </Button>
                  )}
              </div>
            </>
          )}
          {expanded && selection && (
            <>
              <p>
                저장된 원장 기준입니다. 편집 중인 값은 저장 후 분석에
                반영됩니다. 다른 장부·원본 상담 이동은 편집을 저장하거나 닫은 뒤
                교차 판정 목록에서 이용할 수 있습니다.
              </p>
              <Button
                variant="link"
                onClick={() => {
                  setExpanded(false);
                  onClose();
                  live.reload();
                }}
              >
                결과 접기
              </Button>
              <JudgmentResult
                selection={selection}
                onSelection={setSelection}
                onSessionExpired={onSessionExpired}
              />
            </>
          )}
        </>
      )}
    </section>
  );
}
export default CrossMatchSection;
