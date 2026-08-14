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

function buildMessageDraft(candidate, anchor) {
  const recipient = candidate.title.split(" · ")[0];
  return `${recipient}님, ${anchor.complex} ${anchor.building}동 ${anchor.unit}호 ${anchor.area || ""} ${anchor.listingType || "매물"} 조건을 확인드리려고 연락드립니다. 검토 가능하시면 편한 시간을 알려주세요.`;
}

function CandidateGroups({ candidates, selectedId, onSelect }) {
  return (
    <div className="cross-match-panel__groups" aria-label="교차 판정 후보 목록">
      {GRADE_ORDER.map((grade) => {
        const items = candidates.filter((candidate) => candidate.grade === grade);
        return (
          <section className="cross-match-panel__grade" key={grade} aria-labelledby={`candidate-grade-${grade}`}>
            <div className="cross-match-panel__grade-heading">
              <h4 id={`candidate-grade-${grade}`}>{grade}</h4>
              <Label isCompact color="grey" variant="outline">
                {items.length}건
              </Label>
            </div>
            <div className="cross-match-panel__candidate-list">
              {items.map((candidate) => {
                const isSelected = selectedId === candidate.id;
                return (
                  <button
                    className={`cross-match-panel__candidate${isSelected ? " is-selected" : ""}`}
                    key={candidate.id}
                    type="button"
                    aria-pressed={isSelected}
                    aria-controls="cross-match-candidate-detail"
                    onClick={() => onSelect(candidate)}
                  >
                    <span className="cross-match-panel__candidate-topline">
                      <Label isCompact {...gradeLabelProps(candidate.grade)}>
                        {candidate.grade}
                      </Label>
                      <span className="cross-match-panel__rank">우선순위 {candidate.rank}</span>
                    </span>
                    <strong>{candidate.title}</strong>
                    <span>{candidate.summary}</span>
                    <span className="cross-match-panel__candidate-meta">
                      예산 {candidate.budget} · 시점 {candidate.timing}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function SequentialState({ step }) {
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

function CandidateDetail({ candidate, anchor, isReadOnly, onComposeMessage }) {
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setNotice("");
  }, [candidate, anchor]);

  const openMessageComposer = () => {
    const nextDraft = buildMessageDraft(candidate, anchor);
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
          <dt>예산</dt>
          <dd>{candidate.budget}</dd>
        </div>
        <div>
          <dt>희망 시점</dt>
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
              onClick={() => setNotice("나중에 처리 목록에 추가했습니다")}
            >
              나중에
            </Button>
            <Button
              variant="secondary"
              icon={<BanIcon />}
              isDisabled={isReadOnly}
              onClick={() => setNotice("관심없음 피드백 초안을 기록했습니다")}
            >
              관심없음
            </Button>
            <Button
              variant="secondary"
              icon={<CalendarAltIcon />}
              isDisabled={isReadOnly}
              onClick={() => setNotice("F1 일정 검토 항목을 준비했습니다")}
            >
              일정 검토
            </Button>
          </div>
        </details>
      </div>

    </article>
  );
}

export function CrossMatchPanel({ isOpen, onClose, anchorRow, onComposeMessage }) {
  const [viewState, setViewState] = useState("sequential");
  const panelRef = useRef(null);
  const [processStep, setProcessStep] = useState(0);
  const [selectedId, setSelectedId] = useState(candidateMatches[0]?.id);
  const anchor = useMemo(() => ({ ...FALLBACK_ANCHOR, ...(anchorRow || {}) }), [anchorRow]);
  const selectedCandidate =
    candidateMatches.find((candidate) => candidate.id === selectedId) || candidateMatches[0];
  const showsCandidates = ["ready", "partial-error", "cached", "readonly"].includes(viewState);

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
            () => setViewState("ready"),
            PROTOTYPE_ASSUMPTIONS.timing.f3CompletionDelayMs,
          );
          return current;
        }
        return current + 1;
      });
    }, PROTOTYPE_ASSUMPTIONS.timing.f3ProcessingStepMs);
    return () => window.clearInterval(timer);
  }, [isOpen, viewState]);

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
            isReadOnly={viewState === "readonly"}
            onComposeMessage={onComposeMessage}
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
          <p>
            {anchor.complex} {anchor.building}동 {anchor.unit}호 · {anchor.area} · {anchor.listingType || "현매물 없음"} {anchor.price || ""}
          </p>
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
              <SequentialState step={processStep} />
            ) : showsCandidates ? (
              <>
                <div className="cross-match-panel__list-heading">
                  <div>
                    <p className="cross-match-panel__eyebrow">판정 후보</p>
                    <h3>강함, 약함, 기각을 함께 검토합니다</h3>
                  </div>
                  <Label color="grey" variant="outline">
                    전체 {candidateMatches.length}건
                  </Label>
                </div>
                <CandidateGroups
                  candidates={candidateMatches}
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
