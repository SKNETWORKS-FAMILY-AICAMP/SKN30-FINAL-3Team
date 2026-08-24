import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FileUpload,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  ProgressStep,
  ProgressStepper,
} from "@patternfly/react-core";
import {
  CheckCircleIcon,
  FileAudioIcon,
  InfoCircleIcon,
  PauseIcon,
  PlayIcon,
  RedoIcon,
  TimesIcon,
  UploadIcon,
} from "@patternfly/react-icons";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";

const STATES = {
  empty: "파일 없음",
  sourceReady: "파일 준비",
  processing: "분석 중",
  review: "분석 완료",
  error: "분석 실패",
};
const STEPS = ["음성 업로드", "텍스트 변환", "장부 정보 분석", "분석 완료"];

function buildProposals(draft, ledgerType) {
  const today = new Date();
  const expiry = new Date(today.getFullYear(), today.getMonth() + PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.expiryOffsetMonths, today.getDate())
    .toISOString().slice(0, 10);
  if (ledgerType === "buyer") {
    return [
      { id: "budget", field: "금액 조건", fieldKey: "budget", current: draft.budget || "미입력", proposal: "30억 이하", evidence: "음성메모에서 예산 상한을 언급한 구간", selected: !draft.budget },
      { id: "moveDate", field: "이사일", fieldKey: "moveDate", current: draft.moveDate || "미입력", proposal: expiry, evidence: "희망 입주 시점을 설명한 문장", selected: !draft.moveDate },
      { id: "buyer", field: "손님 이름·별칭", fieldKey: "buyer", current: draft.buyer || "미입력", proposal: "성명 확인 필요", evidence: "상담 상대를 식별한 문장", selected: !draft.buyer },
      { id: "content", field: "상담 로그", fieldKey: "content", current: draft.content || "미입력", proposal: PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.log, evidence: "음성메모의 상담 요약 전체", selected: !draft.content },
    ].map((proposal) => ({ ...proposal, status: proposal.current === "미입력" ? "신규" : proposal.proposal !== proposal.current ? "변경" : "확인" }));
  }
  return [
    { id: "price", field: "매매가", fieldKey: "price", current: draft.price || "미입력", proposal: PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.price, evidence: "음성메모에서 희망 매매가로 언급된 구간", selected: !draft.price },
    { id: "expiry", field: "계약 만기일", fieldKey: "expiry", current: draft.expiry || "미입력", proposal: expiry, evidence: "계약 종료 시점을 설명한 문장", selected: !draft.expiry },
    { id: "owner", field: "임대인", fieldKey: "owner", current: draft.owner || "미입력", proposal: PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.owner, evidence: "상담자가 소유 관계를 설명한 문장", selected: !draft.owner },
    { id: "log", field: "상담 로그", fieldKey: "log", current: draft.log || "미입력", proposal: PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.log, evidence: "음성메모의 상담 요약 전체", selected: !draft.log },
  ].map((proposal) => ({ ...proposal, status: proposal.current === "미입력" ? "신규" : proposal.proposal !== proposal.current ? "변경" : "확인" }));
}

function formatSize(bytes) {
  if (!bytes) return "크기 확인 불가";
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export default function VoiceMemoModal({ isOpen, draft, initialDraft, ledgerType = "property", appendTo, onClose, onApply, onDraftChange }) {
  const [state, setState] = useState(() => initialDraft?.state || "empty");
  const [source, setSource] = useState(() => initialDraft?.audioSource || null);
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [proposals, setProposals] = useState(() => initialDraft?.proposals || []);
  const [reviewComplete, setReviewComplete] = useState(() => Boolean(initialDraft?.reviewComplete));
  const audioRef = useRef(null);
  const objectUrlRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    setState(initialDraft?.state || "empty");
    setSource(initialDraft?.audioSource || null);
    setFile(null);
    setFileError("");
    setStep(0);
    setPlaying(false);
    setConfirmed(Boolean(initialDraft?.privacyConfirmed));
    setProposals(initialDraft?.proposals || []);
    setReviewComplete(Boolean(initialDraft?.reviewComplete));
  }, [isOpen]);

  const f2Draft = useMemo(() => ({
    state,
    audioSource: source,
    proposals,
    reviewComplete,
    privacyConfirmed: confirmed,
  }), [confirmed, proposals, reviewComplete, source, state]);

  useEffect(() => {
    if (isOpen) onDraftChange?.(f2Draft);
  }, [f2Draft, isOpen]);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  useEffect(() => {
    if (state !== "processing") return undefined;
    const timer = window.setTimeout(() => {
      if (step < STEPS.length - 1) {
        setStep((current) => current + 1);
        return;
      }
      if (source?.name?.toLowerCase().includes("error")) {
        setState("error");
        return;
      }
      setProposals(buildProposals(draft, ledgerType));
      setReviewComplete(false);
      setState("review");
    }, PROTOTYPE_ASSUMPTIONS.timing.f2ProcessingStepMs);
    return () => window.clearTimeout(timer);
  }, [draft, ledgerType, source, state, step]);

  const handleFileInput = (_event, nextFile) => {
    const extension = nextFile?.name?.split(".").pop()?.toLowerCase();
    setPlaying(false);
    if (!confirmed) {
      setFileError("주의 문구를 확인한 뒤 파일을 선택할 수 있습니다.");
      return;
    }
    if (!nextFile || !["wav", "mp3", "m4a"].includes(extension)) {
      setFile(null); setSource(null); setFileError("WAV, MP3, M4A 형식의 음성 파일만 사용할 수 있습니다."); return;
    }
    if (nextFile.size === 0) {
      setFile(null); setSource(null); setFileError("내용이 없는 음성 파일은 분석할 수 없습니다."); return;
    }
    if (PROTOTYPE_ASSUMPTIONS.audio.maxBytes && nextFile.size > PROTOTYPE_ASSUMPTIONS.audio.maxBytes) {
      setFile(null); setSource(null); setFileError(`프로토타입 임시 상한 ${PROTOTYPE_ASSUMPTIONS.audio.maxLabel}을 초과했습니다.`); return;
    }
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = URL.createObjectURL(nextFile);
    setFile(nextFile);
    setSource({ kind: "upload", name: nextFile.name, size: nextFile.size, type: nextFile.type, url: objectUrlRef.current });
    setFileError("");
    setState("sourceReady");
  };

  const clearSource = () => {
    setPlaying(false); setFile(null); setSource(null); setFileError(""); setStep(0); setState("empty"); setProposals([]); setReviewComplete(false);
  };

  const togglePlaying = () => {
    if (!audioRef.current || !file) { setPlaying((current) => !current); return; }
    if (playing) { audioRef.current.pause(); setPlaying(false); return; }
    audioRef.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  };

  const toggleProposal = (id, checked) => setProposals((current) => current.map((proposal) => proposal.id === id ? { ...proposal, selected: checked } : proposal));

  const applySelected = () => {
    const selected = proposals.filter((proposal) => proposal.selected);
    const isAppendOnly = (proposal) => proposal.fieldKey === "log" || proposal.fieldKey === "content";
    const patch = selected.reduce((result, proposal) => {
      const current = draft[proposal.fieldKey];
      return { ...result, [proposal.fieldKey]: isAppendOnly(proposal) && current ? `${current}\n${proposal.proposal}` : proposal.proposal };
    }, {});
    /*
     * 기존 값을 지우는 칸만 따로 알린다.
     *
     * 어떤 제안이 기존 값을 덮어쓰는지는 여기서만 정확히 안다. 상담 로그는
     * 이어 붙이므로 값이 있어도 사라지는 것이 없고, 빈 칸은 채우기일 뿐이다.
     * 부모가 patch만 보고 되짚으려면 이 구분을 다시 추측해야 한다.
     */
    const replacements = selected
      .filter((proposal) => !isAppendOnly(proposal) && String(draft[proposal.fieldKey] ?? "").trim())
      .map((proposal) => ({ fieldKey: proposal.fieldKey, field: proposal.field, current: String(draft[proposal.fieldKey]), next: proposal.proposal }));
    const nextProposals = proposals.map((proposal) => proposal.selected ? { ...proposal, selected: false, status: "반영됨" } : proposal);
    setProposals(nextProposals);
    setReviewComplete(true);
    onApply?.(patch, { ...f2Draft, state: "review", proposals: nextProposals, reviewComplete: true }, { replacements });
    onClose?.();
  };

  const renderUpload = (replacement = false) => (
    <div className="f2-upload">
      <div className="f2-upload__heading"><UploadIcon aria-hidden="true" /><div><strong>{replacement ? "다른 파일로 교체" : "음성 파일 업로드"}</strong><span>WAV, MP3, M4A</span></div></div>
      <FileUpload
        id={replacement ? "f2-audio-replacement" : "f2-audio-upload"}
        filename={file?.name || ""}
        filenamePlaceholder="파일을 선택하거나 놓아주세요"
        filenameAriaLabel="선택한 음성 파일"
        browseButtonText="파일 선택"
        clearButtonText="지우기"
        value={file || ""}
        hideDefaultPreview
        isDisabled={!confirmed}
        dropzoneProps={{ accept: { "audio/*": [".wav", ".mp3", ".m4a"] }, maxFiles: 1 }}
        onFileInputChange={handleFileInput}
        onClearClick={clearSource}
        validated={fileError ? "error" : "default"}
      />
      {fileError && <p className="f2-upload__error" role="alert">{fileError}</p>}
    </div>
  );

  const body = state === "empty" ? (
    <div className="f2-modal__empty">{renderUpload()}<p>브라우저에서 직접 녹음하지 않고 상담 후 만든 음성 파일을 업로드합니다.</p></div>
  ) : state === "sourceReady" ? (
    <div className="f2-source-ready">
      <div className="f2-source-card"><FileAudioIcon aria-hidden="true" /><div><strong>{source?.name}</strong><span>{formatSize(source?.size)} · 업로드 파일</span></div><div className="f2-source-card__actions"><Button variant="link" icon={playing ? <PauseIcon /> : <PlayIcon />} onClick={togglePlaying}>{playing ? "재생 중지" : "재생"}</Button><Button variant="link" icon={<TimesIcon />} onClick={clearSource}>원본 제거</Button></div></div>
      {file && <audio ref={audioRef} src={source?.url} onEnded={() => setPlaying(false)} />}
      {renderUpload(true)}
      <div className="f2-actions f2-actions--end"><Button variant="primary" icon={<PlayIcon />} isDisabled={!confirmed} onClick={() => { setStep(0); setState("processing"); }}>분석 시작</Button></div>
    </div>
  ) : state === "processing" ? (
    <div className="f2-processing" aria-live="polite"><div className="f2-processing__heading"><div><strong>음성메모를 분석하고 있습니다</strong><span>상세 정보는 계속 확인할 수 있습니다.</span></div><Button variant="secondary" icon={<TimesIcon />} onClick={() => { setStep(0); setState("sourceReady"); }}>분석 취소</Button></div><ProgressStepper isCenterAligned>{STEPS.map((item, index) => <ProgressStep key={item} variant={index < step ? "success" : index === step ? "info" : "pending"} isCurrent={index === step}>{item}</ProgressStep>)}</ProgressStepper><p className="f2-processing__note">분석 실패 시에도 부모 상세의 작성값은 유지됩니다.</p></div>
  ) : state === "error" ? (
    <Alert variant="danger" isInline isLiveRegion title="음성메모 분석을 완료하지 못했습니다" actionLinks={<Button variant="link" icon={<RedoIcon />} onClick={() => setState("sourceReady")}>다시 분석</Button>}>원본 파일을 그대로 유지한 채 다시 시도할 수 있습니다.</Alert>
  ) : (
    <div className="f2-review"><Alert variant="info" isInline isPlain title="프로토타입 예시 분석 결과">현재값과 다른 제안은 `변경` 상태로 표시되며 기본 선택되지 않습니다.</Alert><div className="f2-review__summary" role="status" aria-live="polite"><div><span>전체 제안</span><strong>{proposals.length}건</strong></div><div><span>선택</span><strong>{proposals.filter((item) => item.selected).length}건</strong></div><div><span>변경</span><strong>{proposals.filter((item) => item.status === "변경").length}건</strong></div></div><div className="f2-review-table-wrap"><table className="pf-v6-c-table pf-m-grid-md pf-m-compact f2-review-table" aria-label="음성메모 분석 제안"><thead><tr><th scope="col">반영</th><th scope="col">필드</th><th scope="col">현재값</th><th scope="col">제안</th><th scope="col">상태</th><th scope="col">근거</th></tr></thead><tbody>{proposals.map((proposal) => <tr key={proposal.id}><td><Checkbox id={`proposal-${proposal.id}`} aria-label={`${proposal.field} 제안 반영`} isChecked={proposal.selected} onChange={(_event, checked) => toggleProposal(proposal.id, checked)} /></td><th scope="row">{proposal.field}</th><td>{proposal.current}</td><td>{proposal.proposal}</td><td><Label isCompact status={proposal.status === "반영됨" ? "success" : proposal.status === "변경" ? "warning" : "info"}>{proposal.status}</Label></td><td className="f2-review-table__evidence">{proposal.evidence}</td></tr>)}</tbody></table></div><div className="f2-review__action-bar"><span>선택한 항목만 부모 상세의 작성값에 반영하고 저장하지 않습니다.</span><Button variant="primary" icon={<CheckCircleIcon />} onClick={applySelected} isDisabled={!proposals.some((item) => item.selected)}>선택 항목 반영</Button></div><div className="f2-review__footer"><Button variant="secondary" icon={<RedoIcon />} onClick={() => { setStep(0); setState("sourceReady"); }}>원본부터 다시 분석</Button>{reviewComplete && <Label status="success" icon={<CheckCircleIcon />}>검토 완료</Label>}</div></div>
  );

  return <Modal id="f2-modal" isOpen={isOpen} onClose={onClose} appendTo={appendTo} variant="large" aria-label="음성메모·AI 제안 검토" className="voice-memo-modal"><ModalHeader title="음성메모·AI 제안 검토" description="F1 상세 위에서 파일을 분석하고 선택한 제안만 작성값에 반영합니다." /><ModalBody><div className="voice-memo-modal__content" data-screen-id="F2-MOD-010" data-requirement-ids="F1-ST-01~05, F1-ST-06~11, F1-ST-12~15, F1-ST-15~18, F2-LIST-01~04, F2-POP-03, F2-REV-01~04"><Alert variant="warning" isInline title="개인정보 포함 음성 주의"><div className="f2-privacy-copy">주민등록번호·계좌번호·비밀번호가 포함된 음성은 업로드하지 마세요. 패턴이 감지되어도 자동 마스킹하거나 저장을 차단하지 않으며, 사용자가 내용을 확인한 뒤 그대로 저장할 수 있습니다.</div><Checkbox id="f2-privacy-confirm" label="주의 문구를 확인했으며 상담 후 만든 음성 파일만 사용합니다." isChecked={confirmed} onChange={(_event, checked) => setConfirmed(checked)} /></Alert>{!confirmed && <Alert variant="info" isInline isPlain title="파일 선택 전 확인 필요">주의 문구 확인 후 파일 선택과 분석이 활성화됩니다.</Alert>}{body}</div></ModalBody><ModalFooter><Button variant="link" onClick={onClose}>닫기</Button></ModalFooter></Modal>;
}
