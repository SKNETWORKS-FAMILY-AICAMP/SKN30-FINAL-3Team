import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  FormSelect,
  FormSelectOption,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from "@patternfly/react-core";
import type {
  AnchorCardDto,
  EvidenceDto,
  FeedbackReason,
} from "../model/dto.ts";
import { f3Transport } from "../api/f3Transport.ts";
import { dateLabel, gradeLabel } from "./model.ts";
import type { JudgmentCandidate, TargetIdentity } from "./model.ts";
import { ApiError } from "../../../shared/api/index.ts";
import { isDenied, judgmentError } from "./useJudgmentTarget.ts";
export type OpenLedger = (
  target: TargetIdentity,
  interactionId?: number,
) => void;
const reasons: { value: FeedbackReason; label: string }[] = [
  { value: "CONDITION_MISMATCH", label: "조건 불일치" },
  { value: "ALREADY_CONTACTED", label: "이미 연락함" },
  { value: "WRONG_JUDGMENT", label: "판정 오류" },
  { value: "OTHER", label: "기타" },
];
function readable(value: unknown): string {
  if (typeof value === "string")
    return (
      {
        PRESENT: "있음",
        ABSENT: "없음",
        WITHDRAWN: "철회",
        UNKNOWN: "판단 어려움",
        URGENT: "급함",
        NORMAL: "보통",
        RELAXED: "여유 있음",
        GOOD: "연락 원활",
        CAUTION: "확인 필요",
        UNREACHABLE: "연락 어려움",
        SALE: "매매",
        JEONSE: "전세",
        MONTHLY_RENT: "월세",
        BUDGET: "예산",
        SELL_INTENT: "매도 의향",
      }[value] ?? value
    );
  if (typeof value === "number") return value.toLocaleString("ko-KR");
  if (Array.isArray(value))
    return value.map(readable).filter(Boolean).join(", ");
  if (value && typeof value === "object")
    return Object.entries(value)
      .filter(
        ([key]) =>
          !["evidence", "evidence_ids", "interaction_ids"].includes(key),
      )
      .map(([key, v]) => `${fieldLabel(key)}: ${readable(v)}`)
      .join(" · ");
  return "";
}
function fieldLabel(key: string): string {
  return (
    {
      intent: "의향",
      timing: "시기",
      flexible: "조정 가능한 조건",
      inflexible: "고정 조건",
      contactability: "연락 가능성",
      value: "판정",
      status: "상태",
      note: "설명",
      constraints: "조건",
      hard_deadline: "최종 시한",
      price_kind: "가격 종류",
      actual_amount: "원장 금액",
      estimated_amount: "추정 금액",
      actual_monthly_amount: "원장 월세",
      estimated_monthly_amount: "추정 월세",
      confidence: "근거 확실성",
      negotiation_intent: "협상 의사",
      urgency: "긴급도",
      preferred_timing: "희망 시기",
      flexible_conditions: "조정 가능한 조건",
      inflexible_conditions: "고정 조건",
      contactability_status: "연락 가능성",
      price: "가격",
      estimated_price: "추정 가격",
      estimated_price_amount: "추정 가격",
      summary: "요약",
      action: "행동",
      reason: "이유",
      message: "대화 제안",
      description: "설명",
    }[key] ?? key
  );
}
function Evidence({
  items,
  anchor,
  candidate,
  onOpenLedger,
}: {
  items: EvidenceDto[];
  anchor: TargetIdentity;
  candidate: TargetIdentity;
  onOpenLedger?: OpenLedger;
}) {
  return (
    <ul className="f3-judgments__evidence">
      {items
        .filter((x) => x.quote_text || x.note)
        .map((e, i) => (
          <li key={i}>
            <span>{e.quote_text ? `“${e.quote_text}”` : e.note}</span>
            {e.interaction_id != null && onOpenLedger && (
              <Button
                variant="link"
                isInline
                onClick={() =>
                  onOpenLedger(
                    e.evidence_side === candidate.anchor_type
                      ? candidate
                      : anchor,
                    e.interaction_id ?? undefined,
                  )
                }
              >
                원본 상담 #{e.interaction_id}
              </Button>
            )}
          </li>
        ))}
    </ul>
  );
}
function PositionCard({
  card,
  title,
  target,
  onOpenLedger,
}: {
  card: AnchorCardDto | null;
  title: string;
  target: TargetIdentity;
  onOpenLedger?: OpenLedger;
}) {
  return (
    <details className="f3-judgments__card">
      <summary>{title}</summary>
      {card ? (
        <>
          <p>분석 당시 조건 · {dateLabel(card.generated_at)}</p>
          <DescriptionList isCompact>
            {Object.entries(card.analysis).map(([key, value]) => (
              <DescriptionListGroup key={key}>
                <DescriptionListTerm>{fieldLabel(key)}</DescriptionListTerm>
                <DescriptionListDescription>
                  {readable(value) || "미기재"}
                </DescriptionListDescription>
              </DescriptionListGroup>
            ))}
          </DescriptionList>
          <Evidence
            items={card.evidence}
            anchor={target}
            candidate={target}
            onOpenLedger={onOpenLedger}
          />
        </>
      ) : (
        <p>생성된 카드가 없습니다.</p>
      )}
    </details>
  );
}
export function CandidateDetail({
  candidate,
  anchor,
  anchorCard,
  stale,
  onOpenLedger,
  onRecorded,
  onAccessDenied,
  onSessionExpired,
}: {
  candidate: JudgmentCandidate;
  anchor: TargetIdentity;
  anchorCard: AnchorCardDto | null;
  stale: boolean;
  onOpenLedger?: OpenLedger;
  onRecorded: () => void;
  onAccessDenied?: () => void;
  onSessionExpired?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<FeedbackReason>("CONDITION_MISMATCH");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    setOpen(false);
    setNotice("");
    setError("");
    setSending(false);
    lock.current = false;
    return () => controller.current?.abort();
  }, [candidate.candidate_id]);
  const submit = async () => {
    if (candidate.judgment_id == null || lock.current) return;
    lock.current = true;
    setSending(true);
    setError("");
    const c = new AbortController();
    controller.current = c;
    try {
      await f3Transport.sendNotInterested(
        { targetId: candidate.judgment_id, reason },
        c.signal,
      );
      if (!c.signal.aborted) {
        setOpen(false);
        setNotice(
          "관심없음 피드백을 기록했습니다. 영구 제외나 처리 완료를 뜻하지 않습니다.",
        );
        onRecorded();
      }
    } catch (cause) {
      if (!c.signal.aborted) {
        setError(judgmentError(cause));
        if (isDenied(cause)) onAccessDenied?.();
        if (cause instanceof ApiError && cause.kind === "unauthorized")
          onSessionExpired?.();
      }
    } finally {
      if (!c.signal.aborted) {
        lock.current = false;
        setSending(false);
      }
    }
  };
  return (
    <article className="f3-judgments__candidate">
      <h3>
        {candidate.target.display_name}{" "}
        <Label>{gradeLabel(candidate.match_grade)}</Label>{" "}
        {stale && <Label color="orange">이전 분석</Label>}
      </h3>
      <p>
        후보 담당자 {candidate.target.assignee_name ?? "미지정"} · 현재 조건{" "}
        {candidate.target.current_conditions ?? "미기재"}
      </p>
      {stale && (
        <Alert
          variant="warning"
          isInline
          title="현재 조건과 분석 당시 조건을 확인해 주세요"
        >
          이전 분석의 다음 대화 제안은 참고용입니다.
        </Alert>
      )}
      <DescriptionList isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>다음 대화 제안</DescriptionListTerm>
          <DescriptionListDescription>
            {candidate.match_grade == null
              ? "AI 미판정"
              : typeof candidate.recommended_action?.message === "string"
                ? candidate.recommended_action.message
                : "제안 없음"}
          </DescriptionListDescription>
        </DescriptionListGroup>
        {[
          ["판정 근거", candidate.evaluation_basis],
          ["걸림돌", candidate.primary_obstacle],
          ["양보할 부분", candidate.possible_concession],
          ["기각 이유", candidate.exclusion_reason],
        ].map(([label, text]) => (
          <DescriptionListGroup key={label}>
            <DescriptionListTerm>{label}</DescriptionListTerm>
            <DescriptionListDescription>
              {text ||
                (candidate.match_grade == null ? "AI 미판정" : "기재 없음")}
            </DescriptionListDescription>
          </DescriptionListGroup>
        ))}
      </DescriptionList>
      <Evidence
        items={candidate.evidence}
        anchor={anchor}
        candidate={candidate.target}
        onOpenLedger={onOpenLedger}
      />
      <div className="f3-judgments__actions">
        {onOpenLedger && (
          <>
            <Button variant="secondary" onClick={() => onOpenLedger(anchor)}>
              기준 장부 열기
            </Button>
            <Button
              variant="secondary"
              onClick={() => onOpenLedger(candidate.target)}
            >
              후보 장부 열기
            </Button>
          </>
        )}
        <Button
          variant="secondary"
          isDisabled={candidate.judgment_id == null}
          onClick={() => setOpen(true)}
        >
          관심없음 기록
        </Button>
      </div>
      <h4>기존 기록 확인</h4>
      <p>
        대상 일반 상담은 이 매물·손님 쌍의 연락 완료를 뜻하지 않습니다. 기록이
        없어도 미연락으로 단정하지 않습니다.
      </p>
      {candidate.recent_records.length ? (
        <ul>
          {candidate.recent_records.map((r) => {
            const t =
              r.anchor_type === anchor.anchor_type &&
              r.anchor_id === anchor.anchor_id
                ? anchor
                : candidate.target;
            return (
              <li key={`${r.record_type}-${r.record_id}`}>
                {dateLabel(r.created_at)} ·{" "}
                {r.record_type === "FEEDBACK"
                  ? `관심없음 피드백 (${reasons.find((reason) => reason.value === r.reason)?.label ?? "사유 미확인"})`
                  : "상담"}{" "}
                · {r.scope === "PAIR" ? "해당 쌍의 기록" : "대상 일반 상담"}{" "}
                {onOpenLedger && (
                  <Button
                    variant="link"
                    isInline
                    onClick={() =>
                      onOpenLedger(t, r.interaction_id ?? undefined)
                    }
                  >
                    원본 장부 열기
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p>확인 가능한 기존 기록 없음</p>
      )}
      <PositionCard
        title="기준 포지션 카드 펼치기"
        card={anchorCard}
        target={anchor}
        onOpenLedger={onOpenLedger}
      />
      <PositionCard
        title="후보 포지션 카드 펼치기"
        card={candidate.position_card}
        target={candidate.target}
        onOpenLedger={onOpenLedger}
      />
      {notice && <Alert variant="success" isInline title={notice} />}
      <Modal
        isOpen={open}
        onClose={() => !sending && setOpen(false)}
        variant="small"
        aria-label="관심없음 사유"
      >
        <ModalHeader
          title="관심없음 사유"
          description="현재 후보 판정에 피드백을 기록합니다."
        />
        <ModalBody>
          <label htmlFor="f3-feedback-reason">사유</label>
          <FormSelect
            id="f3-feedback-reason"
            value={reason}
            onChange={(_e, value) => {
              const found = reasons.find((r) => r.value === value);
              if (found) setReason(found.value);
            }}
          >
            {reasons.map((r) => (
              <FormSelectOption key={r.value} value={r.value} label={r.label} />
            ))}
          </FormSelect>
          {error && <Alert variant="danger" isInline title={error} />}
        </ModalBody>
        <ModalFooter>
          <Button
            variant="primary"
            isLoading={sending}
            isDisabled={sending}
            onClick={() => void submit()}
          >
            피드백 기록
          </Button>
          <Button
            variant="link"
            isDisabled={sending}
            onClick={() => setOpen(false)}
          >
            취소
          </Button>
        </ModalFooter>
      </Modal>
    </article>
  );
}
