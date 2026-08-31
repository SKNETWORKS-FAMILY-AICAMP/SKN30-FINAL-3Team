/**
 * F3 교차 판정 Panel.
 *
 * 표시 전용이다. 실행 확보, polling, 단계 전환과 결과 조립은 `features/f3`의 훅이 소유하고
 * 여기서는 그 결과를 그린다. 화면이 자기 상태 기계를 따로 가지면 서버가 말한 단계와 화면이
 * 보여주는 단계가 어긋난다.
 *
 * F1 비차단이다. 판정이 늦거나 실패해도 상세의 편집·저장·닫기를 막지 않는다.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  Alert,
  Button,
  Divider,
  Drawer,
  DrawerContent,
  DrawerContentBody,
  DrawerPanelBody,
  DrawerPanelContent,
  FormSelect,
  FormSelectOption,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Skeleton,
  Spinner,
} from "@patternfly/react-core";
import {
  BanIcon,
  BookmarkIcon,
  CalendarAltIcon,
  CommentDotsIcon,
  SyncAltIcon,
} from "@patternfly/react-icons";
import "@patternfly/react-core/dist/styles/base.css";
import {
  DEFAULT_FEEDBACK_REASON,
  FEEDBACK_REASON_CHOICES,
  GRADE_ORDER,
  collapsedGrades as collapsedGradesFor,
  describePanelState,
  hiddenGrades as hiddenGradesFor,
} from "./model/viewModel.ts";
import type {
  CandidateView,
  EvidenceView,
  GradeLabel,
  PanelState,
  ParentContext,
} from "./model/viewModel.ts";
import { describeForUser } from "../ledger/index.ts";
import { scrollIntoViewRespectingMotion } from "../../shared/motion/index.ts";
import type { CrossJudgment } from "./hooks/useCrossJudgment.ts";
import type { FeedbackReason } from "./model/dto.ts";
import "./CrossMatchPanel.css";

/**
 * 앵커 행에서 이 패널이 실제로 읽는 값.
 *
 * 장부의 행 타입을 그대로 가져오지 않는다. 패널은 머리말과 문안 초안에 쓸 몇 개의 표시값만
 * 필요하고, 장부 타입을 끌어오면 F1 계약이 바뀔 때마다 이 파일이 함께 흔들린다.
 */
export interface AnchorRowView {
  complex?: string;
  building?: string;
  unit?: string;
  area?: string;
  listingType?: string;
  price?: string;
  buyer?: string;
  category?: string;
  budget?: string;
}

export interface ActionPayload {
  candidate: CandidateView;
  anchorRow: AnchorRowView | null;
}

/** 문자 작성 화면으로 넘기는 값. 실제 발송은 F1이 대상·동의·번호를 다시 확인한 뒤에 한다. */
export interface ComposeMessagePayload extends ActionPayload {
  mode: string;
  title: string;
  draft: string;
}

interface CrossMatchPanelProps {
  isOpen: boolean;
  onClose: () => void;
  anchorRow: AnchorRowView | null;
  judgment: CrossJudgment;
  parentContext?: ParentContext;
  onComposeMessage?: (payload: ComposeMessagePayload) => void;
  onOpenEvidence?: (payload: ActionPayload) => void;
  onLater?: (payload: ActionPayload) => void;
  /**
   * 관심없음 기록. 성공하면 resolve하고 실패하면 reject한다.
   *
   * 모달은 이 약속이 지켜진 뒤에만 닫는다. 요청을 보내자마자 닫으면 서버가 거절해도 사용자는
   * 기록된 줄 안다.
   */
  onNotInterested?: (payload: {
    candidate: CandidateView;
    reason: FeedbackReason;
  }) => Promise<void>;
  onSchedule?: (payload: ActionPayload) => void;
  focusRequest?: number;
}

/**
 * 업무 처리 단계.
 *
 * `QUEUED`·`RUNNING`은 Worker가 작업을 잡았는지를 나타내는 실행 제어 상태이므로 이 축에 넣지
 * 않는다. 둘을 섞으면 아직 아무 일도 시작되지 않았는데 진행률이 올라간 것처럼 보인다.
 */
const PROCESS_STEPS = ["기준 세대 확인", "조건 후보 조회", "후보별 근거 판정"] as const;

function stepIndexFor(state: PanelState): number {
  switch (state) {
    case "anchor-ready":
      return 1;
    case "candidates-ready":
    case "carding":
    case "judging":
      return 2;
    case "ready":
    case "empty":
      return PROCESS_STEPS.length;
    default:
      return 0;
  }
}

const RUNNING_STATES: readonly PanelState[] = [
  "queueing",
  "queued",
  "running",
  "anchor-ready",
  "candidates-ready",
  "carding",
  "judging",
];

/** 아직 서버가 단계를 진행 중인가. 종료 상태에서는 진행 표시를 걷는다. */
function isRunning(state: PanelState): boolean {
  return RUNNING_STATES.includes(state);
}

const FAILURE_STATES: readonly PanelState[] = ["failed", "superseded", "paused"];

function GradeBadge({ grade }: { grade: GradeLabel | null }) {
  if (grade === "강함") return <Label status="success">강함</Label>;
  if (grade === "약함") return <Label status="warning">약함</Label>;
  if (grade === "기각") {
    return (
      <Label color="grey" variant="outline">
        기각
      </Label>
    );
  }
  return (
    <Label color="grey" variant="outline">
      상세 판정 미수행
    </Label>
  );
}

function anchorHeadline(anchorRow: AnchorRowView | null, parentContext: ParentContext): string {
  if (anchorRow == null) return "판정 대상을 선택해 주세요";
  if (parentContext === "buyer-detail") {
    return [anchorRow.buyer, anchorRow.category, anchorRow.complex, anchorRow.area, anchorRow.budget]
      .filter(Boolean)
      .join(" · ");
  }
  const place = [
    anchorRow.complex,
    anchorRow.building && `${anchorRow.building}동`,
    anchorRow.unit && `${anchorRow.unit}호`,
  ]
    .filter(Boolean)
    .join(" ");
  return [place, anchorRow.area, anchorRow.listingType, anchorRow.price].filter(Boolean).join(" · ");
}

function buildMessageDraft(
  candidate: CandidateView,
  anchorRow: AnchorRowView | null,
  parentContext: ParentContext,
): string {
  if (parentContext === "buyer-detail") {
    return `안녕하세요. ${anchorRow?.buyer || "손님"} 고객의 ${anchorRow?.complex || "희망 단지"} 조건과 관련해 ${candidate.title} 확인드립니다. 상담 가능 시간을 알려주세요.`;
  }
  const place = [
    anchorRow?.complex,
    anchorRow?.building && `${anchorRow.building}동`,
    anchorRow?.unit && `${anchorRow.unit}호`,
  ]
    .filter(Boolean)
    .join(" ");
  return `${place} ${anchorRow?.listingType || "매물"} 조건을 확인드리려고 연락드립니다. 검토 가능하시면 편한 시간을 알려주세요.`;
}

interface GroupProps {
  candidates: CandidateView[];
  selectedId: number | undefined;
  onSelect: (candidate: CandidateView) => void;
}

function CandidateGroups({
  candidates,
  selectedId,
  onSelect,
  hiddenGrades,
  collapsedGrades,
}: GroupProps & { hiddenGrades: GradeLabel[]; collapsedGrades: GradeLabel[] }) {
  return (
    <div className="cross-match-panel__groups" aria-label="교차 판정 후보 목록">
      {GRADE_ORDER.map((grade) => {
        if (hiddenGrades.includes(grade)) return null;
        const items = candidates.filter((candidate) => candidate.grade === grade);
        if (items.length === 0) return null;
        const isCollapsed = collapsedGrades.includes(grade);
        const list = (
          <div className="cross-match-panel__candidate-list">
            {items.map((candidate) => (
              <CandidateButton
                key={candidate.candidateId}
                candidate={candidate}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
        );
        return (
          <section
            className={`cross-match-panel__grade${isCollapsed ? " is-collapsed" : ""}`}
            key={grade}
            aria-labelledby={`candidate-grade-${grade}`}
          >
            {isCollapsed ? (
              <details>
                <summary className="cross-match-panel__grade-heading">
                  <span>
                    <strong id={`candidate-grade-${grade}`}>{grade}</strong>
                    <span className="cross-match-panel__grade-note">판정 실행·피드백에서 확인</span>
                  </span>
                  <Label isCompact color="grey" variant="outline">
                    {items.length}건
                  </Label>
                </summary>
                {list}
              </details>
            ) : (
              <>
                <div className="cross-match-panel__grade-heading">
                  <h4 id={`candidate-grade-${grade}`}>{grade}</h4>
                  <Label isCompact color="grey" variant="outline">
                    {items.length}건
                  </Label>
                </div>
                {list}
              </>
            )}
          </section>
        );
      })}
      <PendingGroup candidates={candidates} selectedId={selectedId} onSelect={onSelect} />
    </div>
  );
}

/**
 * 아직 판정되지 않은 SQL 후보.
 *
 * 카드화 대상은 상위 15건이라 나머지는 등급 없이 목록에만 남는다. 이것을 판정 실패로 보여주면
 * 사용자가 서버가 무언가를 놓쳤다고 오해한다.
 */
function PendingGroup({ candidates, selectedId, onSelect }: GroupProps) {
  const items = candidates.filter((candidate) => candidate.grade == null);
  if (items.length === 0) return null;
  return (
    <section className="cross-match-panel__grade is-collapsed" aria-labelledby="candidate-grade-pending">
      <details>
        <summary className="cross-match-panel__grade-heading">
          <span>
            <strong id="candidate-grade-pending">상세 판정 미수행</strong>
            <span className="cross-match-panel__grade-note">
              조건에는 맞지만 상세 판정 대상이 아닙니다
            </span>
          </span>
          <Label isCompact color="grey" variant="outline">
            {items.length}건
          </Label>
        </summary>
        <div className="cross-match-panel__candidate-list">
          {items.map((candidate) => (
            <CandidateButton
              key={candidate.candidateId}
              candidate={candidate}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      </details>
    </section>
  );
}

function CandidateButton({
  candidate,
  selectedId,
  onSelect,
}: {
  candidate: CandidateView;
  selectedId: number | undefined;
  onSelect: (candidate: CandidateView) => void;
}) {
  const isSelected = candidate.candidateId === selectedId;
  return (
    <button
      type="button"
      className={`cross-match-panel__candidate${isSelected ? " is-selected" : ""}`}
      aria-pressed={isSelected}
      aria-controls="cross-match-candidate-detail"
      onClick={() => onSelect(candidate)}
    >
      <span className="cross-match-panel__candidate-title">{candidate.title}</span>
      <span className="cross-match-panel__candidate-summary">
        {candidate.summary || candidate.budget}
      </span>
    </button>
  );
}

function ProgressState({ state, candidates }: { state: PanelState; candidates: CandidateView[] }) {
  const step = stepIndexFor(state);
  return (
    <div className="cross-match-panel__loading" aria-live="polite">
      <ol className="cross-match-panel__steps">
        {PROCESS_STEPS.map((label, index) => {
          const status = index < step ? "완료" : index === step ? "진행 중" : "대기";
          return (
            <li key={label} className={index === step ? "is-active" : ""}>
              <span>{label}</span>
              {index === step ? (
                <span className="cross-match-panel__step-status">
                  <Spinner isInline aria-label={`${label} 진행 중`} />
                  {status}
                </span>
              ) : index < step ? (
                <Label isCompact status="success">
                  {status}
                </Label>
              ) : (
                <Label isCompact color="grey">
                  {status}
                </Label>
              )}
            </li>
          );
        })}
      </ol>
      <p className="cross-match-panel__sequential-anchor">{describePanelState(state)}</p>
      {candidates.length === 0 && (
        <div className="cross-match-panel__skeleton-list" aria-label="후보 목록 불러오는 중">
          <Skeleton width="76%" screenreaderText="후보 제목 불러오는 중" />
          <Skeleton width="100%" />
          <Skeleton width="92%" />
        </div>
      )}
    </div>
  );
}

function EmptyState({ criteria, onRetry }: { criteria: string[]; onRetry: () => void }) {
  return (
    <div className="cross-match-panel__state-card">
      <h3>조건에 맞는 후보가 없습니다</h3>
      <p>아래 조건을 모두 적용한 결과입니다.</p>
      {criteria.length > 0 && (
        <ul className="cross-match-panel__sql-preview" aria-label="적용한 조회 조건">
          {criteria.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <Button variant="secondary" icon={<SyncAltIcon />} onClick={onRetry}>
        다시 판정
      </Button>
    </div>
  );
}

function FailureState({
  state,
  message,
  onRetry,
}: {
  state: PanelState;
  message: string | null;
  onRetry: () => void;
}) {
  if (state === "paused") {
    return (
      <div className="cross-match-panel__state-card">
        <Alert variant="info" isInline title="처리가 예상보다 길어지고 있습니다">
          서버에서 계속 처리 중일 수 있습니다. 확인을 잠시 멈췄습니다.
        </Alert>
        <Button variant="secondary" icon={<SyncAltIcon />} onClick={onRetry}>
          다시 확인
        </Button>
      </div>
    );
  }

  if (state === "superseded") {
    return (
      <div className="cross-match-panel__state-card">
        <Alert variant="warning" isInline title="판정 중 내용이 바뀌었습니다">
          {message || "실행 중 입력 데이터가 변경되어 결과를 반영하지 않았습니다."}
        </Alert>
        <Button variant="secondary" icon={<SyncAltIcon />} onClick={onRetry}>
          최신 내용으로 다시 판정
        </Button>
      </div>
    );
  }

  return (
    <div className="cross-match-panel__state-card">
      <Alert variant="danger" isInline title="교차 판정을 완료하지 못했습니다">
        {message || "F3만 실패했습니다."} 상세의 편집, 저장, 닫기는 계속 사용할 수 있습니다.
      </Alert>
      <Button variant="secondary" icon={<SyncAltIcon />} onClick={onRetry}>
        판정 다시 시도
      </Button>
    </div>
  );
}

/**
 * 판정 근거 목록.
 *
 * 인용(`quote`)은 카드가 실제로 갖고 있던 상담 원문이고, 인용이 없으면 카드 값들을 비교한
 * 정황 판단(`note`)이다. 둘 다 없는 근거는 보여줄 것이 없으므로 거른다.
 *
 * `interactionId`는 화면 이동에 쓰지 않는다. 상담 로그 단건 조회 경로가 아직 없어 어느 로그인지
 * 짚어 줄 수 없다. 값은 모델에 그대로 남겨 두고, 그 경로가 생기면 여기서 연결한다.
 */
function EvidenceList({ evidence }: { evidence: EvidenceView[] }) {
  const shown = evidence.filter((item) => item.quote != null || item.note != null);
  if (shown.length === 0) return null;

  return (
    <ul className="cross-match-panel__evidence" aria-label="판정 근거 목록">
      {shown.map((item, index) => (
        <li key={`${item.fieldName ?? "evidence"}-${index}`}>
          {item.fieldName != null && (
            <span className="cross-match-panel__evidence-field">{item.fieldName}</span>
          )}
          <span>{item.quote != null ? `“${item.quote}”` : item.note}</span>
        </li>
      ))}
    </ul>
  );
}

interface CandidateDetailProps {
  candidate: CandidateView;
  anchorRow: AnchorRowView | null;
  parentContext: ParentContext;
  onComposeMessage: CrossMatchPanelProps["onComposeMessage"];
  onOpenEvidence: CrossMatchPanelProps["onOpenEvidence"];
  onLater: CrossMatchPanelProps["onLater"];
  onNotInterested: CrossMatchPanelProps["onNotInterested"];
  onSchedule: CrossMatchPanelProps["onSchedule"];
}

function CandidateDetail({
  candidate,
  anchorRow,
  parentContext,
  onComposeMessage,
  onOpenEvidence,
  onLater,
  onNotInterested,
  onSchedule,
}: CandidateDetailProps) {
  const [notice, setNotice] = useState("");
  const [interestOpen, setInterestOpen] = useState(false);
  const [interestReason, setInterestReason] = useState<FeedbackReason>(DEFAULT_FEEDBACK_REASON);
  /** 피드백 전송 상태. 실패하면 모달을 열어 둔 채 사유를 보여주고 다시 시도하게 한다. */
  const [feedbackError, setFeedbackError] = useState("");
  const [feedbackSending, setFeedbackSending] = useState(false);

  useEffect(() => {
    setNotice("");
    setFeedbackError("");
  }, [candidate]);

  const submitNotInterested = async () => {
    if (onNotInterested == null) return;
    setFeedbackSending(true);
    setFeedbackError("");
    try {
      await onNotInterested({ candidate, reason: interestReason });
      setInterestOpen(false);
      setNotice("관심없음 피드백을 기록했습니다");
    } catch (cause) {
      setFeedbackError(describeForUser(cause));
    } finally {
      setFeedbackSending(false);
    }
  };

  const recordAction = (label: string, callback: ((payload: ActionPayload) => void) | undefined) => {
    callback?.({ candidate, anchorRow });
    setNotice(`${label} 요청을 F1 연동 대상으로 기록했습니다`);
  };

  // 관심없음은 장부 ID가 아니라 판정 행 ID로 저장한다. 그 ID가 응답에 없는 동안에는 버튼을
  // 잠근다. `candidateId`로 대신 보내면 서버 검증은 통과하고 엉뚱한 판정에 기록된다.
  const canGiveFeedback = candidate.feedbackTargetId != null;

  return (
    <article id="cross-match-candidate-detail" className="cross-match-panel__detail" aria-live="polite">
      <div className="cross-match-panel__detail-heading">
        <div>
          <p className="cross-match-panel__eyebrow">선택 후보</p>
          <h3>{candidate.title}</h3>
          <p>{candidate.summary}</p>
        </div>
        <GradeBadge grade={candidate.grade} />
      </div>

      {candidate.unlabeled && (
        <Alert variant="info" isInline title="현재 목록에서 이 후보의 장부 행을 찾지 못했습니다">
          판정 내용은 그대로 보여줍니다. 이름과 연락처는 해당 장부를 불러온 뒤에 표시됩니다.
        </Alert>
      )}

      {candidate.recommendedAction && (
        <div className="cross-match-panel__recommendation">
          <span>추천 다음 행동</span>
          <strong>{candidate.recommendedAction}</strong>
        </div>
      )}

      <dl className="cross-match-panel__facts">
        <div>
          <dt>{parentContext === "buyer-detail" ? "매물 금액" : "예산"}</dt>
          <dd>{candidate.budget || "미기재"}</dd>
        </div>
        <div>
          <dt>접수일</dt>
          <dd>{candidate.receivedAt || "미기재"}</dd>
        </div>
        <div>
          <dt>연락처</dt>
          {/* 판정 응답이 아니라 장부 행에서 온다. 목록에 인물이 없는 매물 후보는 비어 있다. */}
          <dd>{candidate.phone || "연락처 없음"}</dd>
        </div>
      </dl>

      <Divider />

      <div className="cross-match-panel__reason-grid">
        <section>
          <h4>판정 근거</h4>
          <p>{candidate.evaluationBasis || "아직 판정하지 않았습니다."}</p>
          <EvidenceList evidence={candidate.evidence} />
          {candidate.evaluationBasis && (
            <Button
              variant="link"
              isInline
              onClick={() => {
                if (onOpenEvidence) onOpenEvidence({ candidate, anchorRow });
                else setNotice("원본 상담 로그 위치를 F1 연동 대상으로 기록했습니다");
              }}
            >
              상세의 상담 로그로 이동
            </Button>
          )}
        </section>
        <section>
          <h4>걸림돌</h4>
          <p>{candidate.blocker || "없음"}</p>
        </section>
        <section>
          <h4>양보 지점</h4>
          <p>{candidate.concession || "없음"}</p>
        </section>
        {candidate.exclusionReason && (
          <section>
            <h4>기각 사유</h4>
            <p>{candidate.exclusionReason}</p>
          </section>
        )}
      </div>

      {notice && (
        <Alert className="cross-match-panel__action-notice" variant="info" isInline title={notice}>
          제안만 기록했습니다. F1 저장 상태는 변경되지 않았습니다.
        </Alert>
      )}

      <div className="cross-match-panel__actions" aria-label="후보 다음 행동">
        <Button
          variant="primary"
          icon={<CommentDotsIcon />}
          onClick={() => {
            setNotice("");
            onComposeMessage?.({
              mode: "mvp-copy-only",
              title: candidate.title,
              candidate,
              anchorRow,
              draft: buildMessageDraft(candidate, anchorRow, parentContext),
            });
          }}
        >
          문자 작성
        </Button>
        <details className="cross-match-panel__more-actions">
          <summary>다른 후속 작업</summary>
          <div>
            <Button
              variant="secondary"
              icon={<BookmarkIcon />}
              onClick={() => recordAction("나중에", onLater)}
            >
              나중에
            </Button>
            <Button
              variant="secondary"
              icon={<BanIcon />}
              isDisabled={!canGiveFeedback}
              onClick={() => setInterestOpen(true)}
            >
              관심없음
            </Button>
            <Button
              variant="secondary"
              icon={<CalendarAltIcon />}
              onClick={() => recordAction("일정 검토", onSchedule)}
            >
              일정 검토
            </Button>
          </div>
          {!canGiveFeedback && (
            <p className="cross-match-panel__grade-note">
              아직 판정하지 않은 후보에는 관심없음을 남길 수 없습니다.
            </p>
          )}
        </details>
      </div>

      <Modal
        variant="small"
        isOpen={interestOpen}
        onClose={() => setInterestOpen(false)}
        aria-label="관심없음 사유"
        data-screen-id="F3-MOD-010"
        data-requirement-ids="F3-CR-17, F3-TR-03, F3-TR-07"
      >
        <ModalHeader title="관심없음 사유" description="판정 결과를 개선하기 위한 피드백을 남깁니다." />
        <ModalBody>
          <label className="cross-match-panel__field-label" htmlFor="cross-match-interest-reason">
            사유
          </label>
          <FormSelect
            id="cross-match-interest-reason"
            value={interestReason}
            onChange={(_event: FormEvent<HTMLSelectElement>, value: string) =>
              setInterestReason(value as FeedbackReason)
            }
          >
            {FEEDBACK_REASON_CHOICES.map((choice) => (
              <FormSelectOption key={choice.value} value={choice.value} label={choice.label} />
            ))}
          </FormSelect>
          {feedbackError !== "" && (
            <Alert variant="danger" isInline title={feedbackError}>
              기록되지 않았습니다. 사유를 확인하고 다시 시도해 주세요.
            </Alert>
          )}
        </ModalBody>
        <ModalFooter>
          <Button
            variant="primary"
            isDisabled={feedbackSending}
            onClick={() => void submitNotInterested()}
          >
            {feedbackSending ? "기록 중" : "피드백 기록"}
          </Button>
          <Button variant="link" isDisabled={feedbackSending} onClick={() => setInterestOpen(false)}>
            취소
          </Button>
        </ModalFooter>
      </Modal>
    </article>
  );
}

export function CrossMatchPanel({
  isOpen,
  onClose,
  anchorRow,
  judgment,
  parentContext = "unit-detail",
  onComposeMessage,
  onOpenEvidence,
  onLater,
  onNotInterested,
  onSchedule,
  focusRequest = 0,
}: CrossMatchPanelProps) {
  const panelRef = useRef<HTMLElement>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const {
    state,
    candidates,
    candidatesTotal,
    limit,
    offset,
    criteria,
    failureMessage,
    error,
    setOffset,
    retry,
  } = judgment;

  const hiddenGrades = hiddenGradesFor(parentContext);
  const collapsedGrades = collapsedGradesFor(parentContext);
  const visibleCandidates = useMemo(
    () =>
      candidates.filter(
        (candidate) => candidate.grade == null || !hiddenGrades.includes(candidate.grade),
      ),
    // `hiddenGrades`는 렌더마다 새 배열이지만 값은 `parentContext`에서만 결정된다.
    // 배열 자체를 의존성에 넣으면 매 렌더 다시 계산된다.
    [candidates, parentContext],
  );

  const selectedCandidate =
    visibleCandidates.find((candidate) => candidate.candidateId === selectedId) ??
    visibleCandidates[0] ??
    null;

  /*
   * 스크롤과 포커스는 사용자가 [교차 판정]을 직접 눌러
   * `focusRequest`를 증가시킨 경우에만 옮긴다.
   * 저장 트리거로 패널이 열린 경우에는 상세의 현재 위치와 포커스를 유지한다.
   */
  useEffect(() => {
    if (!isOpen || !focusRequest) return undefined;
    const frame = window.requestAnimationFrame(() => {
      scrollIntoViewRespectingMotion(panelRef.current, { block: "start" });
      const title = panelRef.current?.querySelector<HTMLElement>("#cross-match-panel-title");
      title?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen, focusRequest]);

  if (!isOpen) return null;

  const hasCandidates = visibleCandidates.length > 0;
  const showsFailure = FAILURE_STATES.includes(state);

  const detailPanel = (
    <DrawerPanelContent
      id="cross-match-detail-panel"
      className="cross-match-panel__detail-panel"
      isPlain
      hasNoBorder
    >
      <DrawerPanelBody>
        {selectedCandidate ? (
          <CandidateDetail
            candidate={selectedCandidate}
            anchorRow={anchorRow}
            parentContext={parentContext}
            onComposeMessage={onComposeMessage}
            onOpenEvidence={onOpenEvidence}
            onLater={onLater}
            onNotInterested={onNotInterested}
            onSchedule={onSchedule}
          />
        ) : isRunning(state) ? (
          <div className="cross-match-panel__detail-loading">
            <Skeleton width="42%" screenreaderText="판정 상세 불러오는 중" />
            <Skeleton width="86%" />
            <Skeleton width="100%" height="6rem" />
          </div>
        ) : (
          <div className="cross-match-panel__state-card cross-match-panel__state-card--detail">
            <h3>선택한 후보의 상세 근거가 여기에 표시됩니다</h3>
            <p>F3 상태와 관계없이 F1 상세의 편집, 저장, 닫기는 영향을 받지 않습니다.</p>
          </div>
        )}
      </DrawerPanelBody>
    </DrawerPanelContent>
  );

  return (
    <section
      ref={panelRef}
      id="cross-match-panel"
      className="cross-match-panel"
      aria-labelledby="cross-match-panel-title"
      data-screen-id="F3-PNL-010 F3-PNL-020"
      data-requirement-ids="F3-CR-05~18, F3-BR-03~10, F3-BR-14, F3-TR-01, F3-TR-03~06; F3-PC-01~13, F3-LA-01~08, F3-CA-01~08, F3-TR-01~02"
    >
      <header className="cross-match-panel__header">
        <div className="cross-match-panel__title-block">
          <div className="cross-match-panel__title-row">
            <h2 id="cross-match-panel-title" tabIndex={-1}>
              교차 판정
            </h2>
            <Label color="blue" variant="outline">
              F1 비차단 Panel
            </Label>
          </div>
          <p>{anchorHeadline(anchorRow, parentContext)}</p>
        </div>
        <div className="cross-match-panel__header-actions">
          <Button variant="plain" aria-label="교차 판정 Panel 닫기" onClick={onClose}>
            닫기
          </Button>
        </div>
      </header>

      <p className="cross-match-panel__nonblocking-note">
        판정은 제안 기능입니다. 처리 중이거나 실패해도 F1 저장과 닫기를 막지 않습니다.
      </p>

      {error && (
        <div className="cross-match-panel__banner">
          <Alert variant="warning" isInline title="판정 정보를 불러오지 못했습니다">
            {error.requestId ? `요청 번호 ${error.requestId}` : "잠시 후 다시 시도해 주세요."}
          </Alert>
        </div>
      )}

      <Drawer className="cross-match-panel__drawer" isExpanded isStatic position="end">
        <DrawerContent panelContent={detailPanel} colorVariant="primary">
          <DrawerContentBody className="cross-match-panel__candidates" hasPadding>
            {state === "unavailable" ? (
              <div className="cross-match-panel__state-card">
                <h3>판정 대상이 아닙니다</h3>
                <p>{describePanelState(state)} 저장된 매물 건이 있어야 교차 판정을 실행합니다.</p>
              </div>
            ) : (
              <>
                {isRunning(state) && <ProgressState state={state} candidates={visibleCandidates} />}

                {hasCandidates && (
                  <>
                    <div className="cross-match-panel__list-heading">
                      <div>
                        <p className="cross-match-panel__eyebrow">판정 후보</p>
                        <h3>
                          {parentContext === "unit-detail"
                            ? "강함·약함 후보를 검토합니다"
                            : "강함·약함 후보와 기각 이력을 검토합니다"}
                        </h3>
                      </div>
                      <Label color="grey" variant="outline">
                        표시 {visibleCandidates.length}건 · 전체 {candidatesTotal}건
                      </Label>
                    </div>
                    <CandidateGroups
                      candidates={visibleCandidates}
                      hiddenGrades={hiddenGrades}
                      collapsedGrades={collapsedGrades}
                      selectedId={selectedCandidate?.candidateId}
                      onSelect={(candidate) => setSelectedId(candidate.candidateId)}
                    />
                    {candidatesTotal > limit && (
                      <div className="cross-match-panel__actions" aria-label="후보 페이지 이동">
                        <Button
                          variant="secondary"
                          isDisabled={offset === 0}
                          onClick={() => setOffset(Math.max(0, offset - limit))}
                        >
                          이전
                        </Button>
                        <Label color="grey" variant="outline">
                          {offset + 1}–{Math.min(offset + limit, candidatesTotal)} / {candidatesTotal}
                        </Label>
                        <Button
                          variant="secondary"
                          isDisabled={offset + limit >= candidatesTotal}
                          onClick={() => setOffset(offset + limit)}
                        >
                          다음
                        </Button>
                      </div>
                    )}
                  </>
                )}

                {state === "empty" && <EmptyState criteria={criteria} onRetry={retry} />}
                {showsFailure && (
                  <FailureState state={state} message={failureMessage} onRetry={retry} />
                )}
              </>
            )}
          </DrawerContentBody>
        </DrawerContent>
      </Drawer>
    </section>
  );
}

export default CrossMatchPanel;
