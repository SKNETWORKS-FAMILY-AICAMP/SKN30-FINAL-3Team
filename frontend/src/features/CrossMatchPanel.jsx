import { useEffect, useMemo, useRef, useState } from "react";
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
  TextArea,
} from "@patternfly/react-core";
import {
  BanIcon,
  BookmarkIcon,
  CalendarAltIcon,
  CommentDotsIcon,
  SyncAltIcon,
} from "@patternfly/react-icons";
import "@patternfly/react-core/dist/styles/base.css";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import { candidateMatches } from "../data/ledgerData.js";
import "./CrossMatchPanel.css";

const VIEW_STATES = [
  ["sequential", "순차 로딩"],
  ["ready", "판정 완료"],
  ["empty", "후보 없음"],
  ["partial-error", "부분 실패"],
  ["failed", "전체 실패"],
  ["cached", "캐시 또는 오래됨"],
  ["readonly", "읽기 전용"],
];

const GRADE_ORDER = ["강함", "약함", "기각"];

const FALLBACK_ANCHOR = {
  id: "H-0001",
  complex: "래미안 원베일리",
  building: "101",
  unit: "203",
  area: "33평",
  listingType: "매매",
  price: "28.8억",
  saveState: "저장 완료",
};

const FALLBACK_BUYER_ANCHOR = {
  id: "B-0001",
  buyer: "손님 정보 미입력",
  category: "매수",
  complex: "희망 단지 미입력",
  area: "평형 미입력",
  budget: "예산 미입력",
};

const BUYER_CANDIDATES = [
  { id: "P-01", grade: "강함", rank: 1, title: "래미안 원베일리 103동 1204호", summary: "희망 단지·평형·예산이 모두 일치", phone: "010-4421-3088", budget: "29억", timing: "2026년 10월 입주", blocker: "방향과 수리 범위 확인 필요", concession: "입주일 2주 조정 가능", evidence: "매물장 최근 상담: 33평, 29억, 10월 입주 협의" },
  { id: "P-02", grade: "강함", rank: 2, title: "래미안 원베일리 105동 807호", summary: "예산과 입주 시점이 일치", phone: "010-6930-2714", budget: "28.7억", timing: "협의", blocker: "희망 동과 다름", concession: "동 선호 완화 시 방문 가능", evidence: "매물장 최근 상담: 가격 조정 가능, 즉시 방문 가능" },
  { id: "P-03", grade: "약함", rank: 3, title: "아크로리버파크 102동 1503호", summary: "평형은 맞지만 희망 단지가 다름", phone: "010-8164-5207", budget: "28억", timing: "2026년 11월 입주", blocker: "단지 선호와 입주 시점 차이", concession: "인접 단지와 한 달 차이를 허용하면 검토 가능", evidence: "매물장 최근 상담: 33평, 11월 입주 가능" },
  { id: "P-04", grade: "기각", rank: 4, title: "반포자이 118동 2101호", summary: "희망 예산을 3억 초과", phone: "010-3275-9401", budget: "33억", timing: "즉시", blocker: "현재 매매가가 최대 예산을 초과", concession: "가격이 30억 이하로 조정되면 재검토", evidence: "매물장 최근 상담: 33억 이하 조정 불가" },
];

const PROCESS_STEPS = ["기준 세대 확인", "조건 후보 조회", "후보별 근거 판정"];

function gradeLabelProps(grade) {
  if (grade === "강함") return { status: "success" };
  if (grade === "약함") return { status: "warning" };
  return { color: "grey", variant: "outline" };
}

function nextActionFor(candidate) {
  if (candidate.grade === "강함") return "조건을 재확인하고 일정 검토";
  if (candidate.grade === "약함") return "걸림돌을 먼저 확인한 뒤 재판정";
  return "조건 변화가 생길 때까지 기각 이력 유지";
}

function buildMessageDraft(candidate, anchor, parentContext) {
  if (parentContext === "buyer-detail") {
    return `안녕하세요. ${anchor.buyer || "손님"} 고객의 ${anchor.complex || "희망 단지"} ${anchor.area || ""} ${anchor.budget || ""} 조건과 관련해 ${candidate.title} 확인드립니다. 상담 가능 시간을 알려주세요.`;
  }
  const recipient = candidate.title.split(" · ")[0];
  return `${recipient}님, ${anchor.complex} ${anchor.building}동 ${anchor.unit}호 ${anchor.area || ""} ${anchor.listingType || "매물"} 조건을 확인드리려고 연락드립니다. 검토 가능하시면 편한 시간을 알려주세요.`;
}

function CandidateGroups({ candidates, selectedId, onSelect, hiddenGrades = [], collapsedGrades = [] }) {
  return (
    <div className="cross-match-panel__groups" aria-label="교차 판정 후보 목록">
      {GRADE_ORDER.map((grade) => {
        const items = candidates.filter((candidate) => candidate.grade === grade);
        if (hiddenGrades.includes(grade)) return null;
        const isCollapsed = collapsedGrades.includes(grade);
        return (
          <section className={`cross-match-panel__grade${isCollapsed ? " is-collapsed" : ""}`} key={grade} aria-labelledby={`candidate-grade-${grade}`}>
            {isCollapsed ? (
              <details>
                <summary className="cross-match-panel__grade-heading">
                  <span><strong id={`candidate-grade-${grade}`}>{grade}</strong><span className="cross-match-panel__grade-note">판정 실행·피드백에서 확인</span></span>
                  <Label isCompact color="grey" variant="outline">{items.length}건</Label>
                </summary>
                <div className="cross-match-panel__candidate-list">
                  {items.map((candidate) => <CandidateButton key={candidate.id} candidate={candidate} selectedId={selectedId} onSelect={onSelect} />)}
                </div>
              </details>
            ) : (
              <>
                <div className="cross-match-panel__grade-heading">
                  <h4 id={`candidate-grade-${grade}`}>{grade}</h4>
                  <Label isCompact color="grey" variant="outline">{items.length}건</Label>
                </div>
                <div className="cross-match-panel__candidate-list">
                  {items.map((candidate) => <CandidateButton key={candidate.id} candidate={candidate} selectedId={selectedId} onSelect={onSelect} />)}
                </div>
              </>
            )}
          </section>
        );
      })}
    </div>
  );
}

function CandidateButton({ candidate, selectedId, onSelect }) {
  const isSelected = selectedId === candidate.id;
  return (
    <button
      className={`cross-match-panel__candidate${isSelected ? " is-selected" : ""}`}
      type="button"
      aria-pressed={isSelected}
      aria-controls="cross-match-candidate-detail"
      onClick={() => onSelect(candidate)}
    >
      <span className="cross-match-panel__candidate-topline">
        <Label isCompact {...gradeLabelProps(candidate.grade)}>{candidate.grade}</Label>
        <span className="cross-match-panel__rank">우선순위 {candidate.rank}</span>
      </span>
      <strong>{candidate.title}</strong>
      <span>{candidate.summary}</span>
      <span className="cross-match-panel__candidate-meta">예산 {candidate.budget} · 시점 {candidate.timing}</span>
    </button>
  );
}

function SequentialState({ step, anchor, candidates, parentContext }) {
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
              ) : (
                <Label isCompact status={index < step ? "success" : undefined} color={index < step ? undefined : "grey"}>
                  {status}
                </Label>
              )}
            </li>
          );
        })}
      </ol>
      <div className="cross-match-panel__skeleton-list" aria-label="후보 목록 불러오는 중">
        <p className="cross-match-panel__sequential-anchor"><strong>앵커 카드</strong> · {parentContext === "buyer-detail" ? `${anchor.buyer} · ${anchor.complex} · ${anchor.area} · ${anchor.budget}` : `${anchor.complex} ${anchor.building}동 ${anchor.unit}호`} · 추정값 기준</p>
        {step >= 1 && <p className="cross-match-panel__sequential-anchor"><strong>SQL 후보</strong> · 조건에 맞는 {candidates.length}건을 먼저 표시하고 판정을 이어갑니다.</p>}
        {step >= 1 && candidates.length > 0 && (
          <ul className="cross-match-panel__sql-preview" aria-label="SQL 후보 미리보기">
            {candidates.slice(0, 3).map((candidate) => <li key={candidate.id}>{candidate.title} · {candidate.summary}</li>)}
          </ul>
        )}
        <Skeleton width="76%" screenreaderText="후보 제목 불러오는 중" />
        <Skeleton width="100%" />
        <Skeleton width="92%" />
        <Skeleton width="68%" />
      </div>
    </div>
  );
}

function NoCandidateState({ state, onRetry, onRelax }) {
  if (state === "empty") {
    return (
      <div className="cross-match-panel__state-card">
        <h3>조건에 맞는 후보가 없습니다</h3>
        <p>단지, 평형, 가격, 입주 시점과 최근 상담 로그를 모두 적용한 결과입니다.</p>
        <Button variant="secondary" onClick={onRelax}>
          조건 완화 결과 보기
        </Button>
      </div>
    );
  }

  return (
    <div className="cross-match-panel__state-card">
      <Alert variant="danger" isInline title="교차 판정을 완료하지 못했습니다">
        F3만 실패했습니다. F1 상세 편집, 저장, 닫기는 계속 사용할 수 있습니다.
      </Alert>
      <Button variant="secondary" icon={<SyncAltIcon />} onClick={onRetry}>
        판정 다시 시도
      </Button>
    </div>
  );
}

function CandidateDetail({ candidate, anchor, parentContext, isReadOnly, onComposeMessage, onOpenEvidence, onLater, onInterest, onSchedule }) {
  const [notice, setNotice] = useState("");
  const [interestOpen, setInterestOpen] = useState(false);
  const [interestReason, setInterestReason] = useState("조건 안 맞음");
  const [interestNote, setInterestNote] = useState("");

  useEffect(() => {
    setNotice("");
  }, [candidate, anchor]);

  const openMessageComposer = () => {
    const nextDraft = buildMessageDraft(candidate, anchor, parentContext);
    setNotice("");
    onComposeMessage?.({
      mode: "mvp-copy-only",
      title: candidate.title,
      phone: candidate.phone,
      candidate,
      anchorRow: anchor,
      draft: nextDraft,
    });
  };

  const recordAction = (label, callback, payload = {}) => {
    callback?.({ candidate, anchorRow: anchor, ...payload });
    setNotice(`${label} 요청을 F1 연동 대상으로 기록했습니다`);
  };

  const submitInterest = () => {
    recordAction("관심없음", onInterest, { reason: interestReason, note: interestNote });
    setInterestOpen(false);
    setInterestNote("");
  };

  return (
    <article id="cross-match-candidate-detail" className="cross-match-panel__detail" aria-live="polite">
      <div className="cross-match-panel__detail-heading">
        <div>
          <p className="cross-match-panel__eyebrow">선택 후보</p>
          <h3>{candidate.title}</h3>
          <p>{candidate.summary}</p>
        </div>
        <Label {...gradeLabelProps(candidate.grade)}>{candidate.grade}</Label>
      </div>

      <div className="cross-match-panel__recommendation">
        <span>추천 다음 행동</span>
        <strong>{nextActionFor(candidate)}</strong>
      </div>

      <dl className="cross-match-panel__facts">
        <div>
          <dt>{parentContext === "buyer-detail" ? "매물 금액" : "예산"}</dt>
          <dd>{candidate.budget}</dd>
        </div>
        <div>
          <dt>{parentContext === "buyer-detail" ? "입주 가능" : "희망 시점"}</dt>
          <dd>{candidate.timing}</dd>
        </div>
        <div>
          <dt>연락처</dt>
          <dd>{candidate.phone}</dd>
        </div>
      </dl>

      <Divider />

      <div className="cross-match-panel__reason-grid">
        <section>
          <h4>판정 근거</h4>
          <p>{candidate.evidence}</p>
          <Button
            variant="link"
            isInline
            onClick={() => {
              if (onOpenEvidence) onOpenEvidence({ candidate, anchorRow: anchor, evidence: candidate.evidence });
              else setNotice("원본 상담 로그 위치를 F1 연동 대상으로 기록했습니다");
            }}
          >
            원본 상담 로그 열기
          </Button>
        </section>
        <section>
          <h4>걸림돌</h4>
          <p>{candidate.blocker}</p>
        </section>
        <section>
          <h4>양보 지점</h4>
          <p>{candidate.concession}</p>
        </section>
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
          isDisabled={isReadOnly}
          onClick={openMessageComposer}
        >
          문자 작성
        </Button>
        <details className="cross-match-panel__more-actions">
          <summary>다른 후속 작업</summary>
          <div>
            <Button
              variant="secondary"
              icon={<BookmarkIcon />}
              isDisabled={isReadOnly}
              onClick={() => recordAction("나중에", onLater)}
            >
              나중에
            </Button>
            <Button
              variant="secondary"
              icon={<BanIcon />}
              isDisabled={isReadOnly}
              onClick={() => setInterestOpen(true)}
            >
              관심없음
            </Button>
            <Button
              variant="secondary"
              icon={<CalendarAltIcon />}
              isDisabled={isReadOnly}
              onClick={() => recordAction("일정 검토", onSchedule)}
            >
              일정 검토
            </Button>
          </div>
        </details>
      </div>

      <Modal variant="small" isOpen={interestOpen} onClose={() => setInterestOpen(false)} aria-label="관심없음 사유" data-screen-id="F3-MOD-010" data-requirement-ids="F3-CR-17, F3-TR-03, F3-TR-07">
        <ModalHeader title="관심없음 사유" description="판정 결과를 개선하기 위한 피드백을 남깁니다." />
        <ModalBody>
          <label className="cross-match-panel__field-label" htmlFor="cross-match-interest-reason">사유</label>
          <FormSelect id="cross-match-interest-reason" value={interestReason} onChange={(_event, value) => setInterestReason(value)}>
            {[
              ["조건 안 맞음", "조건 안 맞음"],
              ["이미 연락함", "이미 연락함"],
              ["판정이 틀림", "판정이 틀림"],
              ["기타", "기타"],
            ].map(([value, label]) => <FormSelectOption key={value} value={value} label={label} />)}
          </FormSelect>
          <label className="cross-match-panel__field-label" htmlFor="cross-match-interest-note">메모 (선택)</label>
          <TextArea id="cross-match-interest-note" value={interestNote} onChange={(_event, value) => setInterestNote(value)} />
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={submitInterest}>피드백 기록</Button>
          <Button variant="link" onClick={() => setInterestOpen(false)}>취소</Button>
        </ModalFooter>
      </Modal>

    </article>
  );
}

export function CrossMatchPanel({ isOpen, onClose, anchorRow, onComposeMessage, parentContext = "unit-detail", onOpenEvidence, onLater, onInterest, onSchedule }) {
  const [viewState, setViewState] = useState("sequential");
  const panelRef = useRef(null);
  const [processStep, setProcessStep] = useState(0);
  const [selectedId, setSelectedId] = useState(candidateMatches[0]?.id);
  const cacheRef = useRef(new Map());
  const candidates = parentContext === "buyer-detail" ? BUYER_CANDIDATES : candidateMatches;
  const anchor = useMemo(
    () => ({ ...(parentContext === "buyer-detail" ? FALLBACK_BUYER_ANCHOR : FALLBACK_ANCHOR), ...(anchorRow || {}) }),
    [anchorRow, parentContext],
  );
  const selectedCandidate = candidates.find((candidate) => candidate.id === selectedId) || candidates[0];
  const showsCandidates = ["ready", "partial-error", "cached", "readonly"].includes(viewState);
  const hiddenGrades = parentContext === "unit-detail" ? ["기각"] : [];
  const collapsedGrades = parentContext === "unit-detail" ? [] : ["기각"];
  const visibleCandidates = candidates.filter((candidate) => !hiddenGrades.includes(candidate.grade));
  const cacheKey = `${parentContext}:${anchor.id}`;

  useEffect(() => {
    if (!isOpen) return undefined;
    const frame = window.requestAnimationFrame(() => {
      panelRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
      panelRef.current?.querySelector("#cross-match-panel-title")?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || viewState !== "sequential") return undefined;
    setProcessStep(0);
    const timer = window.setInterval(() => {
      setProcessStep((current) => {
        if (current >= PROCESS_STEPS.length - 1) {
          window.clearInterval(timer);
          window.setTimeout(
            () => {
              cacheRef.current.set(cacheKey, { candidates, completedAt: new Date().toISOString() });
              setViewState("ready");
            },
            PROTOTYPE_ASSUMPTIONS.timing.f3CompletionDelayMs,
          );
          return current;
        }
        return current + 1;
      });
    }, PROTOTYPE_ASSUMPTIONS.timing.f3ProcessingStepMs);
    return () => window.clearInterval(timer);
  }, [isOpen, viewState, cacheKey, candidates]);

  useEffect(() => {
    if (!isOpen) return;
    setSelectedId(visibleCandidates[0]?.id || candidates[0]?.id);
    if (cacheRef.current.has(cacheKey)) setViewState("cached");
    else setViewState("sequential");
  }, [isOpen, cacheKey]);

  if (!isOpen) return null;

  const stateBanner =
    viewState === "partial-error" ? (
      <Alert variant="warning" isInline title="일부 후보 판정에 실패했습니다">
        완료된 후보는 유지합니다. 실패한 후보 2건만 다시 시도할 수 있습니다.
      </Alert>
    ) : viewState === "cached" ? (
      <Alert variant="info" isInline title="저장된 판정 결과를 표시합니다">
        2026-08-13 10:20 기준, 판정 규칙 v4.2입니다. 최신 상담 로그 반영 여부를 확인하세요.
      </Alert>
    ) : viewState === "readonly" ? (
      <Alert variant="info" isInline title="읽기 전용 권한입니다">
        근거는 볼 수 있지만 문자, 보류, 피드백, 일정 행동은 사용할 수 없습니다.
      </Alert>
    ) : null;

  const detailPanel = (
    <DrawerPanelContent
      id="cross-match-detail-panel"
      className="cross-match-panel__detail-panel"
      isPlain
      hasNoBorder
    >
      <DrawerPanelBody>
        {viewState === "sequential" ? (
          <div className="cross-match-panel__detail-loading">
            <Skeleton width="42%" screenreaderText="판정 상세 불러오는 중" />
            <Skeleton width="86%" />
            <Skeleton width="100%" height="6rem" />
            <Skeleton width="100%" height="6rem" />
          </div>
        ) : showsCandidates && selectedCandidate ? (
          <CandidateDetail
            candidate={selectedCandidate}
            anchor={anchor}
            parentContext={parentContext}
            isReadOnly={viewState === "readonly"}
            onComposeMessage={onComposeMessage}
            onOpenEvidence={onOpenEvidence}
            onLater={onLater}
            onInterest={onInterest}
            onSchedule={onSchedule}
          />
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
    <section ref={panelRef} id="cross-match-panel" className="cross-match-panel" aria-labelledby="cross-match-panel-title" data-screen-id="F3-PNL-010 F3-PNL-020" data-requirement-ids="F3-CR-05~18, F3-BR-03~10, F3-BR-14, F3-TR-01, F3-TR-03~06; F3-PC-01~13, F3-LA-01~08, F3-CA-01~08, F3-TR-01~02">
      <header className="cross-match-panel__header">
        <div className="cross-match-panel__title-block">
          <div className="cross-match-panel__title-row">
            <h2 id="cross-match-panel-title" tabIndex={-1}>교차 판정</h2>
            <Label color="blue" variant="outline">
              F1 비차단 Panel
            </Label>
          </div>
          <p>{parentContext === "buyer-detail"
            ? `${anchor.buyer} · ${anchor.category} · ${anchor.complex} · ${anchor.area} · ${anchor.budget}`
            : `${anchor.complex} ${anchor.building}동 ${anchor.unit}호 · ${anchor.area} · ${anchor.listingType || "현매물 없음"} ${anchor.price || ""}`}</p>
        </div>
        <div className="cross-match-panel__header-actions">
          <details className="cross-match-panel__prototype-tools">
            <summary>프로토타입 상태</summary>
            <div>
              <label htmlFor="cross-match-state">교차 판정 상태</label>
              <FormSelect
                id="cross-match-state"
                aria-label="교차 판정 상태 시뮬레이션"
                value={viewState}
                onChange={(_event, value) => setViewState(value)}
              >
                {VIEW_STATES.map(([value, label]) => (
                  <FormSelectOption key={value} value={value} label={label} />
                ))}
              </FormSelect>
            </div>
          </details>
          <Button variant="plain" aria-label="교차 판정 Panel 닫기" onClick={onClose}>
            닫기
          </Button>
        </div>
      </header>

      <p className="cross-match-panel__nonblocking-note">
        판정은 제안 기능입니다. 처리 중이거나 실패해도 F1 저장과 닫기를 막지 않습니다.
      </p>

      {stateBanner && <div className="cross-match-panel__banner">{stateBanner}</div>}

      <Drawer className="cross-match-panel__drawer" isExpanded isStatic position="end">
        <DrawerContent panelContent={detailPanel} colorVariant="primary">
          <DrawerContentBody className="cross-match-panel__candidates" hasPadding>
            {viewState === "sequential" ? (
              <SequentialState step={processStep} anchor={anchor} candidates={visibleCandidates} parentContext={parentContext} />
            ) : showsCandidates ? (
              <>
                <div className="cross-match-panel__list-heading">
                  <div>
                    <p className="cross-match-panel__eyebrow">판정 후보</p>
                    <h3>{parentContext === "unit-detail" ? "강함·약함 후보를 검토합니다" : "강함·약함 후보와 기각 이력을 검토합니다"}</h3>
                  </div>
                  <Label color="grey" variant="outline">
                    표시 {visibleCandidates.length}건 · 판정 {candidates.length}건
                  </Label>
                </div>
                <CandidateGroups
                  candidates={candidates}
                  hiddenGrades={hiddenGrades}
                  collapsedGrades={collapsedGrades}
                  selectedId={selectedCandidate?.id}
                  onSelect={(candidate) => setSelectedId(candidate.id)}
                />
                {viewState === "partial-error" && (
                  <Button variant="link" icon={<SyncAltIcon />} onClick={() => setViewState("sequential")}>
                    실패한 후보만 다시 시도
                  </Button>
                )}
              </>
            ) : (
              <NoCandidateState
                state={viewState}
                onRetry={() => setViewState("sequential")}
                onRelax={() => setViewState("ready")}
              />
            )}
          </DrawerContentBody>
        </DrawerContent>
      </Drawer>
    </section>
  );
}

export default CrossMatchPanel;
