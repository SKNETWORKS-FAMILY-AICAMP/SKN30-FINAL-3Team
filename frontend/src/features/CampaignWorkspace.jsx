import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormSelect,
  FormSelectOption,
  Label,
  TextArea,
  Title,
} from "@patternfly/react-core";
import {
  ArrowLeftIcon,
  CheckCircleIcon,
  CommentDotsIcon,
  FilterIcon,
} from "@patternfly/react-icons";
import "./CampaignWorkspace.css";

const SEGMENTS = ["매도 의향", "만기 임박", "후속 확인", "판단 보류"];

function classifyTarget(row) {
  if (!row.phone) return { segment: "제외", reason: "연락처 없음" };
  if (row.consent !== "동의") return { segment: "제외", reason: "연락 동의 확인 필요" };
  if (row.listingType) return { segment: "매도 의향", reason: `${row.listingType} 조건 보유` };
  if (row.expiry) return { segment: "만기 임박", reason: `만기 ${row.expiry}` };
  if (row.lastContact) return { segment: "후속 확인", reason: `최근 상담 ${row.lastContact}` };
  return { segment: "판단 보류", reason: "판단 근거 부족" };
}

function defaultDraft(segment, count) {
  if (segment === "만기 임박") return `안녕하세요. 계약 만기와 향후 계획을 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
  if (segment === "후속 확인") return `안녕하세요. 이전 상담 이후 조건 변동이 있는지 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
  if (segment === "판단 보류") return `안녕하세요. 보유 세대의 향후 계획을 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
  return `안녕하세요. 보유 세대의 매도 조건을 확인드리려고 연락드립니다. 편한 시간을 알려주세요. (대상 ${count}명)`;
}

export function CampaignWorkspace({ targets = [], onBack, onOpenComposer }) {
  const classified = useMemo(
    () => targets.map((row) => ({ ...row, ...classifyTarget(row) })),
    [targets],
  );
  const initiallyEligible = useMemo(
    () => classified.filter((row) => row.segment !== "제외").map((row) => row.id),
    [classified],
  );
  const [includedIds, setIncludedIds] = useState(initiallyEligible);
  const [hasRun, setHasRun] = useState(false);
  const [activeSegment, setActiveSegment] = useState("매도 의향");
  const [draft, setDraft] = useState(() => defaultDraft("매도 의향", initiallyEligible.length));

  const included = classified.filter((row) => includedIds.includes(row.id));
  const availableSegments = SEGMENTS.filter((segment) => included.some((row) => row.segment === segment));
  const selectedSegment = availableSegments.includes(activeSegment)
    ? activeSegment
    : availableSegments[0] || "매도 의향";
  const segmentTargets = included.filter((row) => row.segment === selectedSegment);
  const excludedCount = classified.length - included.length;
  const missingPhoneCount = classified.filter((row) => !row.phone).length;
  const consentCount = classified.filter((row) => row.phone && row.consent !== "동의").length;

  const toggleTarget = (row, checked) => {
    if (row.segment === "제외") return;
    setIncludedIds((current) => checked
      ? Array.from(new Set([...current, row.id]))
      : current.filter((id) => id !== row.id));
  };

  const runCampaign = () => {
    setHasRun(true);
    const nextSegment = availableSegments[0] || "매도 의향";
    setActiveSegment(nextSegment);
    setDraft(defaultDraft(nextSegment, included.filter((row) => row.segment === nextSegment).length));
  };

  const changeSegment = (value) => {
    setActiveSegment(value);
    setDraft(defaultDraft(value, included.filter((row) => row.segment === value).length));
  };

  const handoff = () => {
    onOpenComposer?.({
      mode: "mvp-copy-only",
      source: "F3 캠페인",
      campaignId: `CMP-${Date.now()}`,
      segment: selectedSegment,
      recipients: segmentTargets.map((row) => ({
        id: row.id,
        title: `${row.owner || "성명 미입력"} · ${row.complex} ${row.building}동 ${row.unit}호`,
        phone: row.phone,
      })),
      draft,
    });
  };

  return (
    <section
      className="campaign-workspace"
      aria-labelledby="campaign-title"
      data-screen-id="F3-PG-010"
      data-requirement-ids="F3-BT-01~20, F1-MS-01~17"
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

      <ol className="campaign-workspace__progress" aria-label="캠페인 진행 단계">
        <li className={hasRun ? "is-complete" : "is-current"}>
          <span>1</span><strong>대상 확인</strong>
        </li>
        <li className={hasRun ? "is-current" : ""}>
          <span>2</span><strong>세그먼트·문안</strong>
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
      </div>

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
              const unavailable = row.segment === "제외";
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
            <Button icon={<FilterIcon />} onClick={runCampaign} isDisabled={included.length === 0}>선택 대상 판정</Button>
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
              </div>
              <label className="campaign-workspace__field" htmlFor="campaign-segment">
                <span>문자 작업 대상 세그먼트</span>
                <FormSelect id="campaign-segment" value={selectedSegment} onChange={(_event, value) => changeSegment(value)}>
                  {availableSegments.map((segment) => <FormSelectOption key={segment} value={segment} label={`${segment} · ${included.filter((row) => row.segment === segment).length}건`} />)}
                </FormSelect>
              </label>
              <label className="campaign-workspace__field" htmlFor="campaign-draft">
                <span>문안</span>
                <TextArea id="campaign-draft" value={draft} onChange={(_event, value) => setDraft(value)} resizeOrientation="vertical" />
              </label>
              <div className="campaign-workspace__card-action">
                <span>넘긴 뒤 문자 작업에서 수신자와 문안을 한 번 더 확인합니다.</span>
                <Button icon={<CommentDotsIcon />} onClick={handoff} isDisabled={segmentTargets.length === 0}>
                  F1 문자 작업으로 넘기기 · {segmentTargets.length}건
                </Button>
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}

export default CampaignWorkspace;
