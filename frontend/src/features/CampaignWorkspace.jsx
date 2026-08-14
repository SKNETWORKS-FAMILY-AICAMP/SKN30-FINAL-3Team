import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  TextArea,
  Title,
} from "@patternfly/react-core";
import {
  ArrowLeftIcon,
  CheckCircleIcon,
  CommentDotsIcon,
  FilterIcon,
} from "@patternfly/react-icons";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import "./CampaignWorkspace.css";

const SEGMENTS = ["매도 의향", "만기 임박", "최근 거절", "결정권 없음", "판단 불가"];
const INPUT_MODES = [["filter", "필터 조건"], ["selection", "그리드 선택"], ["natural", "자연어 입력"]];
const NO_SEND_SEGMENTS = new Set(["최근 거절", "결정권 없음"]);

function classifyTarget(row) {
  if (!row.phone) return { segment: "발송 제외", reason: "연락처 없음" };
  if (row.consent !== "동의") return { segment: "발송 제외", reason: "연락 동의 X 또는 확인 필요" };
  if (/거절|매도 의사 없음|수신 거부/.test(row.log || "")) return { segment: "최근 거절", reason: "상담 로그에 명시적 거절" };
  if (/결정권 없음|임차인/.test(row.log || "")) return { segment: "결정권 없음", reason: "상담 로그에 결정권 없음" };
  if (row.listingType) return { segment: "매도 의향", reason: `${row.listingType} 조건 보유` };
  if (row.expiry) return { segment: "만기 임박", reason: `만기 ${row.expiry}` };
  if (row.lastContact) return { segment: "판단 불가", reason: `판단에 필요한 최근 로그 부족 · 마지막 상담 ${row.lastContact}` };
  return { segment: "판단 불가", reason: "접촉 이력 부족" };
}

function defaultDraft(segment, count) {
  if (segment === "만기 임박") return `안녕하세요. 계약 만기와 향후 계획을 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
  if (segment === "판단 불가") return `안녕하세요. 보유 세대의 향후 계획을 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
  if (NO_SEND_SEGMENTS.has(segment) || segment === "발송 제외") return "";
  return `안녕하세요. 보유 세대의 매도 조건을 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
}

function replaceVariables(text, row) {
  return text
    .replaceAll("{이름}", row.owner || "성명 미입력")
    .replaceAll("{동}", row.building || "미입력")
    .replaceAll("{호}", row.unit || "미입력")
    .replaceAll("{평형}", row.area || "미입력")
    .replaceAll("{최근실거래3건}", "데이터 확인 필요");
}

export function CampaignWorkspace({ targets = [], onBack, onOpenComposer }) {
  const [inputMode, setInputMode] = useState("selection");
  const [filterComplex, setFilterComplex] = useState("");
  const [filterListingType, setFilterListingType] = useState("");
  const [naturalQuery, setNaturalQuery] = useState("");
  const [includedIds, setIncludedIds] = useState([]);
  const [manualSegments, setManualSegments] = useState({});
  const [campaignExcludedIds, setCampaignExcludedIds] = useState([]);
  const [hasRun, setHasRun] = useState(false);
  const [judgmentState, setJudgmentState] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [calledCount, setCalledCount] = useState(0);
  const [activeSegment, setActiveSegment] = useState("매도 의향");
  const [draft, setDraft] = useState("");
  const [approved, setApproved] = useState(false);
  const [sizeWarningOpen, setSizeWarningOpen] = useState(false);
  const timerRef = useRef(null);

  const sourceTargets = useMemo(() => {
    if (inputMode === "filter") {
      return targets.filter((row) => (!filterComplex || row.complex === filterComplex) && (!filterListingType || row.listingType === filterListingType));
    }
    if (inputMode === "natural") {
      const query = naturalQuery.trim().toLowerCase();
      if (!query) return targets;
      const terms = query.split(/[\s,·]+/).filter(Boolean);
      return targets.filter((row) => {
        const haystack = `${row.complex} ${row.listingType} ${row.area} ${row.log} ${row.owner}`.toLowerCase();
        return terms.every((term) => haystack.includes(term));
      });
    }
    return targets;
  }, [targets, inputMode, filterComplex, filterListingType, naturalQuery]);

  const classified = useMemo(() => sourceTargets.map((row) => ({ ...row, ...classifyTarget(row) })), [sourceTargets]);
  const eligibleIds = useMemo(() => classified.filter((row) => row.segment !== "발송 제외").map((row) => row.id), [classified]);

  useEffect(() => {
    setIncludedIds(eligibleIds);
    setCampaignExcludedIds([]);
    setManualSegments({});
    setHasRun(false);
    setJudgmentState("idle");
    setProgress(0);
  }, [eligibleIds.join(",")]);

  useEffect(() => () => timerRef.current && window.clearInterval(timerRef.current), []);

  const withSegment = useMemo(
    () => classified.map((row) => ({ ...row, segment: manualSegments[row.id] || row.segment })),
    [classified, manualSegments],
  );
  const included = withSegment.filter((row) => includedIds.includes(row.id) && !campaignExcludedIds.includes(row.id));
  const availableSegments = SEGMENTS.filter((segment) => included.some((row) => row.segment === segment));
  const selectedSegment = availableSegments.includes(activeSegment) ? activeSegment : availableSegments[0] || "매도 의향";
  const segmentTargets = included.filter((row) => row.segment === selectedSegment);
  const sampleTarget = segmentTargets[0] || included[0] || withSegment[0];
  const excludedCount = withSegment.length - included.length;
  const missingPhoneCount = withSegment.filter((row) => !row.phone).length;
  const consentCount = withSegment.filter((row) => row.phone && row.consent !== "동의").length;
  const isRunning = judgmentState === "running";
  const canHandoff = approved && hasRun && segmentTargets.length > 0 && !NO_SEND_SEGMENTS.has(selectedSegment) && selectedSegment !== "발송 제외";

  const toggleTarget = (row, checked) => {
    if (row.segment === "발송 제외") return;
    setIncludedIds((current) => checked ? Array.from(new Set([...current, row.id])) : current.filter((id) => id !== row.id));
    setApproved(false);
  };

  const runCampaign = () => {
    if (!included.length || isRunning) return;
    setJudgmentState("running");
    setHasRun(false);
    setApproved(false);
    setProgress(0);
    setCalledCount(0);
    let completed = 0;
    timerRef.current = window.setInterval(() => {
      completed += 1;
      setProgress(Math.min(100, Math.round((completed / included.length) * 100)));
      setCalledCount((count) => count + 1);
      if (completed >= included.length) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
        setJudgmentState(included.length > 8 ? "partial-error" : "success");
        setHasRun(true);
        const nextSegment = availableSegments[0] || "매도 의향";
        setActiveSegment(nextSegment);
        setDraft(defaultDraft(nextSegment, included.filter((row) => row.segment === nextSegment).length));
      }
    }, 120);
  };

  const requestCampaign = () => {
    if (included.length > PROTOTYPE_ASSUMPTIONS.campaign.batchWarningCount) {
      setSizeWarningOpen(true);
      return;
    }
    runCampaign();
  };

  const changeSegment = (value) => {
    setActiveSegment(value);
    setDraft(defaultDraft(value, included.filter((row) => row.segment === value).length));
    setApproved(false);
  };

  const changeRowSegment = (rowId, value) => {
    setManualSegments((current) => ({ ...current, [rowId]: value }));
    setApproved(false);
  };

  const excludeFromCampaign = (rowId) => {
    setCampaignExcludedIds((current) => Array.from(new Set([...current, rowId])));
    setApproved(false);
  };

  const approveDraft = () => setApproved(true);

  const handoff = () => {
    if (!canHandoff) return;
    onOpenComposer?.({
      mode: "mvp-copy-only",
      source: "F3 캠페인",
      campaignId: `CMP-${Date.now()}`,
      segment: selectedSegment,
      recipients: segmentTargets.map((row) => ({ id: row.id, title: `${row.owner || "성명 미입력"} · ${row.complex} ${row.building}동 ${row.unit}호`, phone: row.phone })),
      draft: sampleTarget ? replaceVariables(draft, sampleTarget) : draft,
    });
  };

  return (
    <section
      className="campaign-workspace"
      aria-labelledby="campaign-title"
      data-screen-id="F3-PG-010"
      data-requirement-ids="F3-BT-01~20, F3-GN-01~07, F1-MS-01, F1-MS-09~15"
    >
      <header className="campaign-workspace__header">
        <div>
          <span className="campaign-workspace__eyebrow">F3 · 사용자가 명시적으로 시작하는 배치 판단</span>
          <Title id="campaign-title" headingLevel="h1" size="xl">문자 캠페인 대상 판정</Title>
          <p>F1 선택 집합을 판정·제외·세그먼트로 검토한 뒤 F1 문자 작업으로 넘깁니다.</p>
        </div>
        <Button variant="secondary" icon={<ArrowLeftIcon />} onClick={onBack}>매물장으로 돌아가기</Button>
      </header>

      <Alert variant="info" isInline title="MVP에서는 실제 문자를 발송하지 않습니다">
        캠페인 결과는 대상·문안을 확정한 뒤 번호 목록을 복사하는 단계에서 끝납니다.
      </Alert>

      <section className="campaign-workspace__source" aria-labelledby="campaign-source-heading">
        <div className="campaign-workspace__section-heading">
          <div>
            <Title id="campaign-source-heading" headingLevel="h2" size="lg">대상 선정 방식</Title>
            <p>SQL 조건, F1 그리드 선택, 자연어 입력 중 하나로 원본 집합을 정합니다. 화면 진입만으로 판정하지 않습니다.</p>
          </div>
          <Label color="blue" variant="outline">원본 {sourceTargets.length}건</Label>
        </div>
        <div className="campaign-workspace__input-modes" role="tablist" aria-label="캠페인 대상 선정 방식">
          {INPUT_MODES.map(([value, label]) => (
            <Button key={value} variant={inputMode === value ? "primary" : "secondary"} role="tab" aria-selected={inputMode === value} onClick={() => setInputMode(value)}>
              {label}
            </Button>
          ))}
        </div>
        {inputMode === "filter" && (
          <Form className="campaign-workspace__source-form">
            <FormGroup label="단지" fieldId="campaign-filter-complex">
              <FormSelect id="campaign-filter-complex" value={filterComplex} onChange={(_event, value) => setFilterComplex(value)}>
                <FormSelectOption value="" label="전체 단지" />
                {Array.from(new Set(targets.map((row) => row.complex).filter(Boolean))).map((complex) => <FormSelectOption key={complex} value={complex} label={complex} />)}
              </FormSelect>
            </FormGroup>
            <FormGroup label="거래 유형" fieldId="campaign-filter-type">
              <FormSelect id="campaign-filter-type" value={filterListingType} onChange={(_event, value) => setFilterListingType(value)}>
                <FormSelectOption value="" label="전체 유형" />
                {Array.from(new Set(targets.map((row) => row.listingType).filter(Boolean))).map((type) => <FormSelectOption key={type} value={type} label={type} />)}
              </FormSelect>
            </FormGroup>
          </Form>
        )}
        {inputMode === "natural" && (
          <FormGroup label="자연어 조건" fieldId="campaign-natural-query" helperText="예: 원베일리 매매, 33평, 6개월 미접촉">
            <TextArea id="campaign-natural-query" value={naturalQuery} onChange={(_event, value) => setNaturalQuery(value)} placeholder="조건을 입력하세요" />
          </FormGroup>
        )}
      </section>

      <ol className="campaign-workspace__progress" aria-label="캠페인 진행 단계">
        <li className={hasRun ? "is-complete" : "is-current"}>
          <span>1</span><strong>대상 확인</strong>
        </li>
        <li className={isRunning ? "is-current" : hasRun ? "is-complete" : ""}>
          <span>2</span><strong>판정 {isRunning ? `${progress}%` : "· 세그먼트·문안"}</strong>
        </li>
        <li>
          <span>3</span><strong>번호 복사</strong>
        </li>
      </ol>

      <div className="campaign-workspace__metrics" role="status" aria-live="polite">
        <div><span>F1 선택</span><strong>{classified.length}건</strong></div>
        <div><span>판정 대상</span><strong>{included.length}건</strong></div>
        <div><span>제외</span><strong>{excludedCount}건</strong></div>
        <div><span>연락처 없음</span><strong>{missingPhoneCount}건</strong></div>
        <div><span>동의 확인</span><strong>{consentCount}건</strong></div>
        <div><span>실제 호출</span><strong>{calledCount}회</strong></div>
      </div>

      {judgmentState === "partial-error" && (
        <Alert variant="warning" isInline title="일부 대상 판정에 실패했습니다">
          완료된 세그먼트는 유지합니다. 실패한 대상은 판단 불가로 남기고 F1 대상 확인은 계속할 수 있습니다.
        </Alert>
      )}

      <div className="campaign-workspace__grid">
        <section className="campaign-workspace__card" aria-labelledby="campaign-targets-heading">
          <div className="campaign-workspace__section-heading">
            <div>
              <Title id="campaign-targets-heading" headingLevel="h2" size="lg">1. 대상 확인·제외</Title>
              <p>직접 선택한 원본은 유지하고, 이번 캠페인에서만 제외할 수 있습니다.</p>
            </div>
            <Label color="blue" variant="outline">직접 선택 {classified.length}건</Label>
          </div>
          <div className="campaign-workspace__target-list">
            {classified.map((row) => {
              const unavailable = row.segment === "발송 제외";
              return (
                <div className={`campaign-workspace__target${unavailable ? " is-excluded" : ""}`} key={row.id}>
                  <Checkbox
                    id={`campaign-target-${row.id}`}
                    isChecked={!unavailable && includedIds.includes(row.id)}
                    isDisabled={unavailable}
                    aria-label={`${row.owner || "성명 미입력"}, ${row.phone || "연락처 없음"}, ${unavailable ? row.reason : "캠페인 포함"}`}
                    onChange={(_event, checked) => toggleTarget(row, checked)}
                  />
                  <div>
                    <strong>{row.owner || "성명 미입력"}</strong>
                    <span>{row.complex} {row.building}동 {row.unit}호 · {row.phone || "연락처 없음"}</span>
                  </div>
                  <Label status={unavailable ? "warning" : "info"} isCompact>{row.reason}</Label>
                </div>
              );
            })}
          </div>
          <div className="campaign-workspace__card-action">
            <span>포함한 {included.length}건만 판정하며 F1 원본은 바뀌지 않습니다.</span>
            <Button icon={<FilterIcon />} onClick={requestCampaign} isDisabled={included.length === 0 || isRunning} isLoading={isRunning}>
              {isRunning ? `판정 중 ${progress}%` : "판정하기"}
            </Button>
          </div>
        </section>

        <section className={`campaign-workspace__card ${hasRun ? "is-ready" : "is-pending"}`} aria-labelledby="campaign-result-heading">
          <div className="campaign-workspace__section-heading">
            <div>
              <Title id="campaign-result-heading" headingLevel="h2" size="lg">2. 세그먼트·문안 검토</Title>
              <p>판정 결과는 제안이며 대상과 문안은 사용자가 확정합니다.</p>
            </div>
            {hasRun && <Label status="success" icon={<CheckCircleIcon />}>판정 완료</Label>}
          </div>

          {!hasRun ? (
            <div className="campaign-workspace__empty">
              <FilterIcon aria-hidden="true" />
              <strong>대상을 확인한 뒤 판정을 실행하세요</strong>
              <span>F1의 원본 데이터와 선택 집합은 변경되지 않습니다.</span>
            </div>
          ) : (
            <>
              <div className="campaign-workspace__segments" aria-label="캠페인 판정 세그먼트">
                {SEGMENTS.map((segment) => (
                  <button
                    type="button"
                    key={segment}
                    className={selectedSegment === segment ? "is-active" : ""}
                    onClick={() => changeSegment(segment)}
                  >
                    <span>{segment}</span>
                    <strong>{included.filter((row) => row.segment === segment).length}건</strong>
                  </button>
                ))}
                <button type="button" className="is-disabled" disabled aria-label="발송 제외 세그먼트">
                  <span>발송 제외</span>
                  <strong>{withSegment.filter((row) => row.segment === "발송 제외").length}건</strong>
                </button>
              </div>
              <label className="campaign-workspace__field" htmlFor="campaign-segment">
                <span>문자 작업 대상 세그먼트</span>
                <FormSelect id="campaign-segment" value={selectedSegment} onChange={(_event, value) => changeSegment(value)}>
                  {availableSegments.map((segment) => <FormSelectOption key={segment} value={segment} label={`${segment} · ${included.filter((row) => row.segment === segment).length}건`} />)}
                </FormSelect>
              </label>
              <label className="campaign-workspace__field" htmlFor="campaign-draft">
                <span>문안</span>
                <TextArea id="campaign-draft" value={draft} onChange={(_event, value) => { setDraft(value); setApproved(false); }} resizeOrientation="vertical" placeholder="{이름} {동} {호} {평형} 변수를 사용할 수 있습니다." />
              </label>
              <div className="campaign-workspace__preview" aria-live="polite">
                <div className="campaign-workspace__section-heading">
                  <strong>변수 치환 미리보기</strong>
                  <Label color="grey" variant="outline">대상 1건 기준</Label>
                </div>
                <p>{sampleTarget ? replaceVariables(draft, sampleTarget) : "미리볼 대상이 없습니다."}</p>
              </div>
              <div className="campaign-workspace__segment-edit" aria-label="세그먼트 대상 수정">
                <div className="campaign-workspace__section-heading">
                  <strong>세그먼트 대상 확인·수정</strong>
                  <span>이번 캠페인에만 적용됩니다.</span>
                </div>
                {segmentTargets.map((row) => (
                  <div className="campaign-workspace__segment-row" key={row.id}>
                    <span><strong>{row.owner || "성명 미입력"}</strong> · {row.complex} {row.building}동 {row.unit}호</span>
                    <FormSelect aria-label={`${row.owner || row.id} 세그먼트`} value={row.segment} onChange={(_event, value) => changeRowSegment(row.id, value)}>
                      {SEGMENTS.map((segment) => <FormSelectOption key={segment} value={segment} label={segment} />)}
                    </FormSelect>
                    <Button variant="link" onClick={() => excludeFromCampaign(row.id)}>이번 캠페인 제외</Button>
                  </div>
                ))}
              </div>
              {NO_SEND_SEGMENTS.has(selectedSegment) && (
                <Alert variant="warning" isInline title="발송 제외 세그먼트">
                  최근 거절·결정권 없음 대상은 로그 근거와 함께 표시되며 F1 문자 작업으로 넘길 수 없습니다.
                </Alert>
              )}
              <div className="campaign-workspace__card-action">
                <span>{approved ? "세그먼트 문안을 승인했습니다. F1에서 수신자와 문안을 다시 확인합니다." : "문안과 대상을 확인한 뒤 세그먼트별로 승인하세요."}</span>
                <div className="campaign-workspace__action-group">
                  <Button variant={approved ? "secondary" : "primary"} onClick={approveDraft} isDisabled={!segmentTargets.length || NO_SEND_SEGMENTS.has(selectedSegment)}>
                    {approved ? "승인 완료" : "세그먼트 문안 승인"}
                  </Button>
                  <Button icon={<CommentDotsIcon />} onClick={handoff} isDisabled={!canHandoff}>
                    F1 문자 작업으로 넘기기 · {segmentTargets.length}건
                  </Button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
      <Modal variant="small" isOpen={sizeWarningOpen} onClose={() => setSizeWarningOpen(false)} data-screen-id="F3-MOD-020" data-requirement-ids="F3-BT-04, F3-BT-23~24" aria-label="캠페인 규모 확인">
        <ModalHeader title="캠페인 규모 확인" description="많은 대상을 판정하면 처리 시간이 늘어날 수 있습니다." />
        <ModalBody>
          <p>현재 판정 대상은 {included.length.toLocaleString()}건입니다. 대상과 제외 규칙을 다시 확인한 뒤 계속하세요.</p>
          <Alert variant="info" isInline isPlain title="MVP 범위">배치와 교차 판정을 동시에 실행하는 고급 옵션은 제공하지 않습니다.</Alert>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={() => { setSizeWarningOpen(false); runCampaign(); }}>확인 후 판정</Button>
          <Button variant="link" onClick={() => setSizeWarningOpen(false)}>대상 다시 보기</Button>
        </ModalFooter>
      </Modal>
    </section>
  );
}

export default CampaignWorkspace;
