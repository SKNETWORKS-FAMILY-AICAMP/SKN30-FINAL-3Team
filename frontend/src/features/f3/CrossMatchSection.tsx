/**
 * F1 상세와 F3 패널을 잇는 조합 지점.
 *
 * 앵커를 어디서 꺼내는지가 이 기능에서 가장 틀리기 쉬운 부분이다. 매물 앵커는 세대가 아니라
 * **매물 건**이고 세대와 매물 건은 각자 `row_version`을 갖는다. 세대 ID를 넘기면 다른 행을
 * 판정하거나 404가 되는데, 오타가 나도 화면은 "판정 대상이 아닙니다"를 조용히 보여줄 뿐이다.
 *
 * 그래서 이 도출을 `AppShell.jsx`에 두지 않고 여기로 옮겼다. 앱 셸은 아직 타입 검사 대상이
 * 아니라(`allowJs: false`) 그 안에서는 `detailRow.listingId`를 잘못 적어도 아무도 잡아주지
 * 않는다. 여기서는 잡힌다.
 */

import { useMemo } from "react";
import type { BuyerRow, PropertyRow } from "../ledger/index.ts";
import { useCrossJudgment } from "./hooks/useCrossJudgment.ts";
import { indexLedgerRows } from "./model/candidateLabel.ts";
import { f3Transport } from "./api/f3Transport.ts";
import { CrossMatchPanel } from "./CrossMatchPanel.tsx";
import type {
  ActionPayload,
  AnchorRowView,
  ComposeMessagePayload,
} from "./CrossMatchPanel.tsx";
import type { AnchorType, FeedbackReason } from "./model/dto.ts";
import type { CandidateView, ParentContext } from "./model/viewModel.ts";

/**
 * 상세 화면이 들고 있는 행.
 *
 * 장부 행 타입을 그대로 가져오지 않는다. 이 조합 지점이 읽는 식별자와 표시값만 선언해 두면
 * F1 계약이 넓어져도 여기가 따라 흔들리지 않는다.
 */
export interface DetailRow extends AnchorRowView {
  /** 세대 또는 구입장의 서버 식별자. 저장 전 draft는 `null`이다. */
  serverId?: number | null;
  rowVersion?: number | null;
  /** 매물 건. 세대와 별도 레코드이며 `row_version`도 따로 관리된다. */
  listingId?: number | null;
  listingRowVersion?: number | null;
}

export interface CrossMatchSectionProps {
  isOpen: boolean;
  onClose: () => void;
  row: DetailRow | null;
  parentContext: ParentContext;
  focusRequest?: number;
  onComposeMessage?: (payload: ComposeMessagePayload) => void;
  onOpenEvidence?: (payload: ActionPayload) => void;
  onLater?: (payload: ActionPayload) => void;
  onSchedule?: (payload: ActionPayload) => void;
  /**
   * 후보 표시 이름을 찾을 F1 장부 행.
   *
   * 결과 조회 응답은 후보의 표시 이름을 싣지 않는다. 후보마다 장부를 단건 조회하면 화면이
   * 쓰지 않는 인물 정보까지 받게 되므로, 이미 불러온 행에서만 찾는다.
   */
  propertyRows?: readonly PropertyRow[];
  buyerRows?: readonly BuyerRow[];
  /** 피드백 결과를 사용자에게 알리는 책임은 앱 셸에 있다. */
  onFeedbackResult?: (result: { ok: boolean; cause?: unknown }) => void;
}

/**
 * 앵커 도출.
 *
 * 저장 전 draft(`serverId`/`listingId`가 없음)와 매물 건이 없는 세대는 판정 대상이 아니다.
 * 세 값이 모두 있어야 실행을 확보한다.
 */
function anchorOf(
  row: DetailRow | null,
  parentContext: ParentContext,
): { anchorType: AnchorType | null; anchorId: number | null; dataVersion: number | null } {
  if (row == null) return { anchorType: null, anchorId: null, dataVersion: null };

  if (parentContext === "buyer-detail") {
    return {
      anchorType: row.serverId == null ? null : "REQUIREMENT",
      anchorId: row.serverId ?? null,
      dataVersion: row.rowVersion ?? null,
    };
  }

  return {
    anchorType: row.listingId == null ? null : "LISTING",
    anchorId: row.listingId ?? null,
    dataVersion: row.listingRowVersion ?? null,
  };
}

export function CrossMatchSection({
  isOpen,
  onClose,
  row,
  parentContext,
  focusRequest = 0,
  onComposeMessage,
  onOpenEvidence,
  onLater,
  onSchedule,
  propertyRows,
  buyerRows,
  onFeedbackResult,
}: CrossMatchSectionProps) {
  const anchor = anchorOf(row, parentContext);

  // 목록이 다시 로드될 때만 색인을 새로 만든다. 후보 수만큼 선형 탐색하지 않기 위한 것이다.
  const ledger = useMemo(
    () => indexLedgerRows(propertyRows ?? [], buyerRows ?? []),
    [propertyRows, buyerRows],
  );

  const judgment = useCrossJudgment({
    anchorType: anchor.anchorType,
    anchorId: anchor.anchorId,
    dataVersion: anchor.dataVersion,
    // 패널을 닫으면 브라우저 확인만 멈춘다. 서버 작업을 취소한 것이 아니다.
    enabled: isOpen && row != null,
    ledger,
  });

  /**
   * 관심없음 기록.
   *
   * 실패를 삼키지 않고 그대로 던진다. 모달이 이 결과를 보고 닫을지 사유를 보여줄지 정한다.
   * 여기서 잡아 버리면 서버가 거절해도 화면은 기록된 것처럼 닫힌다.
   */
  const recordNotInterested = async ({
    candidate,
    reason,
  }: {
    candidate: CandidateView;
    reason: FeedbackReason;
  }): Promise<void> => {
    // 버튼이 잠겨 있어 여기까지 오지 않지만, 식별자가 열린 뒤에도 같은 조건을 지킨다.
    if (candidate.feedbackTargetId == null) return;
    try {
      await f3Transport.sendNotInterested({ targetId: candidate.feedbackTargetId, reason });
    } catch (cause) {
      onFeedbackResult?.({ ok: false, cause });
      throw cause;
    }
    onFeedbackResult?.({ ok: true });
  };

  return (
    <CrossMatchPanel
      isOpen={isOpen}
      onClose={onClose}
      anchorRow={row}
      judgment={judgment}
      parentContext={parentContext}
      focusRequest={focusRequest}
      onComposeMessage={onComposeMessage}
      onOpenEvidence={onOpenEvidence}
      onLater={onLater}
      onNotInterested={recordNotInterested}
      onSchedule={onSchedule}
    />
  );
}

export default CrossMatchSection;
