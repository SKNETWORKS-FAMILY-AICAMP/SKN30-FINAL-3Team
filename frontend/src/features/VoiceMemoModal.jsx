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
import { analyzeNewIntake, analyzeVoiceMemo, appendVoiceMemoToLog, LEDGER_LABEL } from "./f2/index.ts";

const STATES = {
  empty: "파일 없음",
  sourceReady: "파일 준비",
  processing: "분석 중",
  review: "분석 완료",
  error: "분석 실패",
};
const STEPS = ["음성 업로드", "텍스트 변환", "장부 정보 분석", "분석 완료"];
const MAX_AUDIO_BYTES = 25 * 1024 * 1024;

function formatSize(bytes) {
  if (!bytes) return "크기 확인 불가";
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

/*
 * 음성메모 분석 팝업.
 *
 * `ledgerType`이 "auto"면 장부가 정해지지 않은 신규 접수다. 상담 유형으로 장부를 판정하고
 * 반영 결과에 그 장부를 실어 보낸다. 그 외에는 열려 있는 상세의 장부를 그대로 쓴다.
 */
export default function VoiceMemoModal({ isOpen, draft, initialDraft, ledgerType = "property", appendTo, onClose, onApply, onDraftChange }) {
  const isIntake = ledgerType === "auto";
  const [state, setState] = useState(() => initialDraft?.state || "empty");
  const [source, setSource] = useState(() => initialDraft?.audioSource || null);
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [proposals, setProposals] = useState(() => initialDraft?.proposals || []);
  const [reviewComplete, setReviewComplete] = useState(() => Boolean(initialDraft?.reviewComplete));
  const [analysis, setAnalysis] = useState(() => initialDraft?.analysis || null);
  const [analysisError, setAnalysisError] = useState("");
  const audioRef = useRef(null);
  const objectUrlRef = useRef(null);
  const requestRef = useRef(null);

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
    setAnalysis(initialDraft?.analysis || null);
    setAnalysisError("");
  }, [isOpen]);

  const f2Draft = useMemo(() => ({
    state,
    audioSource: source,
    proposals,
    reviewComplete,
    privacyConfirmed: confirmed,
    analysis,
  }), [analysis, confirmed, proposals, reviewComplete, source, state]);

  useEffect(() => {
    if (isOpen) onDraftChange?.(f2Draft);
  }, [f2Draft, isOpen]);

  useEffect(() => () => {
    requestRef.current?.abort();
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

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
    if (nextFile.size > MAX_AUDIO_BYTES) {
      setFile(null); setSource(null); setFileError("25MB를 초과한 음성 파일은 분석할 수 없습니다."); return;
    }
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = URL.createObjectURL(nextFile);
    setFile(nextFile);
    setSource({ kind: "upload", name: nextFile.name, size: nextFile.size, type: nextFile.type, url: objectUrlRef.current });
    setFileError("");
    setState("sourceReady");
  };

  const clearSource = () => {
    requestRef.current?.abort();
    setPlaying(false); setFile(null); setSource(null); setFileError(""); setAnalysisError(""); setAnalysis(null); setStep(0); setState("empty"); setProposals([]); setReviewComplete(false);
  };

  const togglePlaying = () => {
    if (!audioRef.current || !file) { setPlaying((current) => !current); return; }
    if (playing) { audioRef.current.pause(); setPlaying(false); return; }
    audioRef.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  };

  const toggleProposal = (id, checked) => setProposals((current) => current.map((proposal) => proposal.id === id ? { ...proposal, selected: checked } : proposal));

  const startAnalysis = async () => {
    if (!file || !confirmed) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setStep(1);
    setState("processing");
    setAnalysisError("");
    try {
      const result = isIntake
        ? await analyzeNewIntake({ audio: file, signal: controller.signal })
        : await analyzeVoiceMemo({ audio: file, ledgerType, draft, signal: controller.signal });
      if (requestRef.current !== controller) return;
      setStep(STEPS.length - 1);
      setAnalysis(result);
      setProposals(result.proposals);
      setReviewComplete(false);
      setState("review");
    } catch (error) {
      if (error?.name === "AbortError") return;
      setAnalysisError(error?.message || "음성메모 분석을 완료하지 못했습니다.");
      setState("error");
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  };

  const cancelAnalysis = () => {
    requestRef.current?.abort();
    requestRef.current = null;
    setStep(0);
    setState("sourceReady");
  };

  const requestClose = () => {
    if (state === "processing") {
      const shouldCancel = window.confirm("진행 중인 음성 분석을 취소하고 닫을까요?");
      if (!shouldCancel) return;
      cancelAnalysis();
    }
    onClose?.();
  };

  const applySelected = () => {
    const selected = proposals.filter((proposal) => proposal.selected && proposal.fieldKey);
    const isAppendOnly = (proposal) => proposal.fieldKey === "log" || proposal.fieldKey === "content";
    /* 반영한 시각을 로그에 적으므로, 한 번에 함께 붙는 제안들은 같은 시각을 갖는다. */
    const appliedAt = new Date();
    const patch = selected.reduce((result, proposal) => {
      const current = result[proposal.fieldKey] ?? draft[proposal.fieldKey];
      return { ...result, [proposal.fieldKey]: isAppendOnly(proposal) ? appendVoiceMemoToLog(current, proposal.proposal, appliedAt) : proposal.proposal };
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
    onApply?.(patch, { ...f2Draft, state: "review", proposals: nextProposals, reviewComplete: true }, { replacements, ledgerType: analysis?.ledgerType ?? ledgerType });
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

  const intakeLedgerLabel = analysis?.ledgerType ? LEDGER_LABEL[analysis.ledgerType] : "";
  /*
   * 검토표 위에 붙는 안내.
   *
   * 신규 접수는 "어느 장부로 갔는가"가 사용자가 가장 먼저 확인할 내용이라 장부 판정을 먼저 알린다.
   * 상세에서 연 경우는 장부가 이미 정해져 있어 장부 불일치만 알리면 된다.
   */
  const reviewNotice = isIntake
    ? (analysis?.usedFallbackLedger
      ? <Alert variant="warning" isInline title={`${analysis.consultationType}으로 분류해 장부를 정하지 못했습니다`}>매도의뢰도 매수문의도 아니어서 {intakeLedgerLabel} 신규 행으로 추가합니다. 필드 제안 없이 상담 로그만 반영되며, 다른 장부가 맞으면 추가 후 직접 옮겨 주세요.</Alert>
      : <Alert variant="info" isInline title={`${analysis?.consultationType || "상담"} · ${intakeLedgerLabel} 신규 행`}>상담 유형으로 장부를 판정했습니다. 선택한 제안만 {intakeLedgerLabel}의 새 행에 채우고 저장은 하지 않습니다.</Alert>)
    : analysis?.ledgerMismatch
      ? <Alert variant="warning" isInline title="현재 장부와 상담 유형이 다릅니다">상담 유형은 {analysis.consultationType}입니다. 필드 제안은 만들지 않고 상담 로그만 검토할 수 있습니다.</Alert>
      : <Alert variant="info" isInline isPlain title={`${analysis?.consultationType || "상담"} 분석 결과`}>현재값과 다른 제안은 `변경` 상태로 표시되며 기본 선택되지 않습니다.</Alert>;

  const body = state === "empty" ? (
    <div className="f2-modal__empty">{renderUpload()}<p>브라우저에서 직접 녹음하지 않고 상담 후 만든 음성 파일을 업로드합니다.{isIntake ? " 분석이 끝나면 상담 유형에 맞는 장부를 알려 드립니다." : ""}</p></div>
  ) : state === "sourceReady" ? (
    <div className="f2-source-ready">
      <div className="f2-source-card"><FileAudioIcon aria-hidden="true" /><div><strong>{source?.name}</strong><span>{formatSize(source?.size)} · 업로드 파일</span></div><div className="f2-source-card__actions"><Button variant="link" icon={playing ? <PauseIcon /> : <PlayIcon />} onClick={togglePlaying}>{playing ? "재생 중지" : "재생"}</Button><Button variant="link" icon={<TimesIcon />} onClick={clearSource}>원본 제거</Button></div></div>
      {file && <audio ref={audioRef} src={source?.url} onEnded={() => setPlaying(false)} />}
      {renderUpload(true)}
      <div className="f2-actions f2-actions--end"><Button variant="primary" icon={<PlayIcon />} isDisabled={!confirmed || !file} onClick={startAnalysis}>분석 시작</Button></div>
    </div>
  ) : state === "processing" ? (
    <div className="f2-processing" aria-live="polite"><div className="f2-processing__heading"><div><strong>음성메모를 분석하고 있습니다</strong><span>RunPod Whisper 전사 후 Qwen이 장부 제안을 생성합니다.</span></div><Button variant="secondary" icon={<TimesIcon />} onClick={cancelAnalysis}>분석 취소</Button></div><ProgressStepper isCenterAligned>{STEPS.map((item, index) => <ProgressStep key={item} variant={index < step ? "success" : index === step ? "info" : "pending"} isCurrent={index === step}>{item}</ProgressStep>)}</ProgressStepper><p className="f2-processing__note">분석 실패 시에도 부모 상세의 작성값은 유지됩니다.</p></div>
  ) : state === "error" ? (
    <Alert variant="danger" isInline isLiveRegion title="음성메모 분석을 완료하지 못했습니다" actionLinks={<Button variant="link" icon={<RedoIcon />} onClick={() => setState("sourceReady")}>다시 분석</Button>}>{analysisError || "원본 파일을 그대로 유지한 채 다시 시도할 수 있습니다."}</Alert>
  ) : (
    <div className="f2-review">{reviewNotice}{analysis?.uncertainties?.length > 0 && <Alert variant="warning" isInline isPlain title="추가 확인이 필요한 내용"><ul>{analysis.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul></Alert>}<div className="f2-review__summary" role="status" aria-live="polite"><div><span>전체 제안</span><strong>{proposals.length}건</strong></div><div><span>선택</span><strong>{proposals.filter((item) => item.selected).length}건</strong></div><div><span>변경</span><strong>{proposals.filter((item) => item.status === "변경").length}건</strong></div></div><div className="f2-review-table-wrap"><table className="pf-v6-c-table pf-m-grid-md pf-m-compact f2-review-table" aria-label="음성메모 분석 제안"><thead><tr><th scope="col">반영</th><th scope="col">필드</th><th scope="col">현재값</th><th scope="col">제안</th><th scope="col">상태</th><th scope="col">근거</th></tr></thead><tbody>{proposals.map((proposal) => <tr key={proposal.id}><td><Checkbox id={`proposal-${proposal.id}`} aria-label={`${proposal.field} 제안 반영`} isChecked={proposal.selected} isDisabled={!proposal.fieldKey} onChange={(_event, checked) => toggleProposal(proposal.id, checked)} /></td><th scope="row">{proposal.field}</th><td>{proposal.current}</td><td>{proposal.proposal}</td><td><Label isCompact status={proposal.status === "반영됨" ? "success" : proposal.status === "변경" ? "warning" : "info"}>{proposal.status}</Label></td><td className="f2-review-table__evidence">{proposal.evidence}</td></tr>)}</tbody></table></div><div className="f2-review__action-bar"><span>{isIntake ? `선택한 항목만 ${intakeLedgerLabel} 신규 행에 채우고 저장하지 않습니다.` : "선택한 항목만 부모 상세의 작성값에 반영하고 저장하지 않습니다."}</span><Button variant="primary" icon={<CheckCircleIcon />} onClick={applySelected} isDisabled={!proposals.some((item) => item.selected && item.fieldKey)}>{isIntake ? `${intakeLedgerLabel}에 행 추가` : "선택 항목 반영"}</Button></div><div className="f2-review__footer"><Button variant="secondary" icon={<RedoIcon />} onClick={() => { setStep(0); setState("sourceReady"); }}>원본부터 다시 분석</Button>{reviewComplete && <Label status="success" icon={<CheckCircleIcon />}>검토 완료</Label>}</div></div>
  );

  return <Modal id="f2-modal" isOpen={isOpen} onClose={requestClose} appendTo={appendTo} variant="large" aria-label={isIntake ? "음성메모 신규 접수" : "음성메모·AI 제안 검토"} className="voice-memo-modal"><ModalHeader title={isIntake ? "음성메모 신규 접수" : "음성메모·AI 제안 검토"} description={isIntake ? "음성을 분석해 매도의뢰는 매물장, 매수문의는 구입장 신규 행으로 추가합니다. 저장은 상세에서 확인한 뒤 진행합니다." : "F1 상세 위에서 파일을 분석하고 선택한 제안만 작성값에 반영합니다."} /><ModalBody><div className="voice-memo-modal__content" data-screen-id="F2-MOD-010" data-requirement-ids="F1-ST-01~05, F1-ST-06~11, F1-ST-12~15, F1-ST-15~18, F2-LIST-01~04, F2-POP-03, F2-REV-01~04"><Alert variant="warning" isInline title="개인정보 포함 음성 주의"><div className="f2-privacy-copy">주민등록번호·계좌번호·비밀번호가 포함된 음성은 업로드하지 마세요. 패턴이 감지되어도 자동 마스킹하거나 저장을 차단하지 않으며, 사용자가 내용을 확인한 뒤 그대로 저장할 수 있습니다.</div><Checkbox id="f2-privacy-confirm" label="주의 문구를 확인했으며 상담 후 만든 음성 파일만 사용합니다." isChecked={confirmed} onChange={(_event, checked) => setConfirmed(checked)} /></Alert>{!confirmed && <Alert variant="info" isInline isPlain title="파일 선택 전 확인 필요">주의 문구 확인 후 파일 선택과 분석이 활성화됩니다.</Alert>}{body}</div></ModalBody><ModalFooter><Button variant="link" onClick={requestClose}>닫기</Button></ModalFooter></Modal>;
}
