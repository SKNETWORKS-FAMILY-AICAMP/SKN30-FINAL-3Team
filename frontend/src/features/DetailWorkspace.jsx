import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  FileUpload,
  FormSelect,
  FormSelectOption,
  Label,
  Modal,
  ModalBody,
  ModalHeader,
  ProgressStep,
  ProgressStepper,
  TextArea,
  TextInput,
  Title,
} from "@patternfly/react-core";
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  FileAudioIcon,
  HistoryIcon,
  InfoCircleIcon,
  MicrophoneIcon,
  PauseIcon,
  PlayIcon,
  RedoIcon,
  SaveIcon,
  SearchIcon,
  StopIcon,
  TimesIcon,
  UploadIcon,
} from "@patternfly/react-icons";
import "@patternfly/react-core/dist/styles/base.css";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import "./DetailWorkspace.css";

const EMPTY_ROW = {
  id: "",
  complex: "",
  building: "",
  unit: "",
  saveState: "작성 중",
  aiState: "대기",
  householdState: "일반",
  area: "",
  listingType: "매매",
  price: "",
  deposit: "",
  rent: "",
  expiry: "",
  owner: "",
  relationship: "본인",
  tenant: "",
  phone: "",
  direction: "",
  floor: "",
  rooms: "",
  baths: "",
  lastContact: "",
  log: "",
  logPersonTarget: "",
  assignee: "",
  source: "",
  consent: "",
  memo: "",
  parking: "",
  moveIn: "",
  tax: "",
  duplicateCheck: false,
};

const F2_STATE_LABELS = {
  empty: "대기",
  recording: "녹음 중",
  sourceReady: "원본 준비",
  processing: "분석 중",
  review: "검토 필요",
  conflict: "충돌 확인",
  error: "분석 실패",
};

const PROCESS_STEPS = ["음성 업로드 중", "텍스트 변환 중", "장부 정보 분석 중", "분석 완료"];
const CIRCLED_PERSON_INDEXES = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"];

function splitRegisteredPeople(value) {
  return String(value || "")
    .split(/[·,\/\n]+/)
    .map((name) => name.trim())
    .filter(Boolean);
}

function buildPersonIndexOptions(draft) {
  return [
    ...splitRegisteredPeople(draft.owner).map((name, index) => ({
      key: `owner:${index}`,
      role: "임대인",
      name,
      position: index + 1,
      marker: CIRCLED_PERSON_INDEXES[index] || String(index + 1),
    })),
    ...splitRegisteredPeople(draft.tenant).map((name, index) => ({
      key: `tenant:${index}`,
      role: "임차인",
      name,
      position: index + 1,
      marker: CIRCLED_PERSON_INDEXES[index] || String(index + 1),
    })),
  ];
}

function stripLeadingPersonIndex(value) {
  return String(value || "").replace(/^[①-⑳]\s*/, "");
}

function normalizeRow(row) {
  const normalized = { ...EMPTY_ROW, ...(row || {}) };

  if (typeof row?.duplicateCheck !== "boolean") {
    normalized.duplicateCheck = Boolean(
      normalized.id &&
        !String(normalized.id).startsWith("DRAFT") &&
        normalized.complex &&
        normalized.building &&
        normalized.unit,
    );
  }

  return normalized;
}

function initialF2State(aiState) {
  if (aiState === "분석 실패") return "error";
  if (aiState === "분석 완료" || aiState === "검토 필요") return "review";
  return "empty";
}

function formatSeconds(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function statusForStorage(value) {
  if (value === "저장 완료") return "success";
  if (value === "검토 필요") return "warning";
  return "info";
}

function statusForAI(f2State, reviewComplete) {
  if (f2State === "error") return "danger";
  if (f2State === "review" && reviewComplete) return "success";
  if (f2State === "conflict" || f2State === "review") return "warning";
  if (f2State === "sourceReady") return "success";
  return "info";
}

function statusForHousehold(value) {
  if (value === "거래진행") return "success";
  if (value === "매물화") return "warning";
  return "info";
}

function buildProposals(draft) {
  const today = new Date();
  const suggestedExpiry = new Date(today.getFullYear(), today.getMonth() + PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.expiryOffsetMonths, today.getDate())
    .toISOString()
    .slice(0, 10);

  return [
    {
      id: "price",
      field: "매매가",
      fieldKey: "price",
      current: draft.price || "미입력",
      proposal: draft.price || PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.price,
      status: draft.price ? "확인" : "신규",
      evidence: "음성메모에서 희망 매매가로 언급된 구간",
      selected: !draft.price,
      resolution: null,
    },
    {
      id: "expiry",
      field: "계약 만기일",
      fieldKey: "expiry",
      current: draft.expiry || "미입력",
      proposal: draft.expiry || suggestedExpiry,
      status: draft.expiry ? "확인" : "신규",
      evidence: "계약 종료 시점을 설명한 문장",
      selected: !draft.expiry,
      resolution: null,
    },
    {
      id: "owner",
      field: "임대인",
      fieldKey: "owner",
      current: draft.owner || "미입력",
      proposal: draft.owner || PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.owner,
      status: draft.owner ? "확인" : "신규",
      evidence: "상담자가 소유 관계를 설명한 문장",
      selected: !draft.owner,
      resolution: null,
    },
    {
      id: "log",
      field: "상담 로그",
      fieldKey: "log",
      current: draft.log || "미입력",
      proposal: PROTOTYPE_ASSUMPTIONS.f2ProposalFixture.log,
      status: draft.log ? "충돌" : "신규",
      evidence: "음성메모의 상담 요약 전체",
      selected: !draft.log,
      resolution: null,
    },
  ];
}

function DetailField({ id, label, value, onChange, type = "text", placeholder = "입력" }) {
  return (
    <div className="detail-field">
      <label className="detail-field__label" htmlFor={id}>
        {label}
      </label>
      <TextInput
        id={id}
        type={type}
        value={value ?? ""}
        placeholder={placeholder}
        onChange={(_event, nextValue) => onChange(nextValue)}
      />
    </div>
  );
}

function DetailSelect({ id, label, value, options, onChange }) {
  return (
    <div className="detail-field">
      <label className="detail-field__label" htmlFor={id}>
        {label}
      </label>
      <FormSelect id={id} value={value} onChange={(_event, nextValue) => onChange(nextValue)}>
        {options.map((option) => (
          <FormSelectOption key={option} value={option} label={option} />
        ))}
      </FormSelect>
    </div>
  );
}

function StateSummary({ label, value, status }) {
  return (
    <div className="detail-workspace__state-item" aria-live="polite">
      <span>{label}</span>
      <Label status={status} isCompact>
        {value}
      </Label>
    </div>
  );
}

export default function DetailWorkspace({
  row,
  isOpen,
  onClose,
  onSave,
  onDiscard,
  onOpenCrossMatch,
  isCrossMatchOpen = false,
  crossMatchPanel,
  focusF2Request = 0,
  complexOptions = [],
  onCreateComplex,
}) {
  const [draft, setDraft] = useState(() => normalizeRow(row));
  const baselineRef = useRef(normalizeRow(row));
  const baselineF2Ref = useRef(null);
  const decisionRef = useRef(null);
  const decisionReturnFocusRef = useRef(null);
  const feedbackRef = useRef(null);
  const f2PanelRef = useRef(null);
  const f2HeadingRef = useRef(null);
  const [f2State, setF2State] = useState(() => initialF2State(row?.aiState));
  const [audioSource, setAudioSource] = useState(null);
  const audioSourceRef = useRef(null);
  const [audioFile, setAudioFile] = useState(null);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [fileError, setFileError] = useState("");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [recordingPaused, setRecordingPaused] = useState(false);
  const [processingStep, setProcessingStep] = useState(0);
  const [proposals, setProposals] = useState([]);
  const [reviewComplete, setReviewComplete] = useState(false);
  const [closeDecision, setCloseDecision] = useState(null);
  const [pendingConflictId, setPendingConflictId] = useState(null);
  const [securityWarning, setSecurityWarning] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [isComplexQuickAddOpen, setIsComplexQuickAddOpen] = useState(false);
  const [newComplexName, setNewComplexName] = useState("");
  const [newComplexAddress, setNewComplexAddress] = useState("");
  const [complexQuickAddError, setComplexQuickAddError] = useState("");
  const [complexQuickAddStatus, setComplexQuickAddStatus] = useState("");
  const initializedOpenRef = useRef(false);

  const focusF2Panel = () => {
    f2PanelRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    window.requestAnimationFrame(() => f2HeadingRef.current?.focus());
  };

  const focusDetailSection = (sectionId, headingId) => {
    const section = document.getElementById(sectionId);
    const heading = document.getElementById(headingId);
    section?.scrollIntoView({ block: "start", behavior: "smooth" });
    window.requestAnimationFrame(() => heading?.focus());
  };

  useEffect(() => {
    if (!isOpen || !focusF2Request) return undefined;
    const frame = window.requestAnimationFrame(focusF2Panel);
    return () => window.cancelAnimationFrame(frame);
  }, [focusF2Request, isOpen]);

  useEffect(() => {
    if (!isOpen) {
      initializedOpenRef.current = false;
      return;
    }
    if (initializedOpenRef.current) return;
    initializedOpenRef.current = true;

    const nextDraft = normalizeRow(row);
    setDraft(nextDraft);
    baselineRef.current = nextDraft;
    const restoredF2State = nextDraft.f2Draft?.state || initialF2State(nextDraft.aiState);
    const restoredAudioSource = nextDraft.f2Draft?.audioSource || null;
    const restoredProposals = nextDraft.f2Draft?.proposals || (nextDraft.aiState === "분석 완료" ? buildProposals(nextDraft) : []);
    const restoredReviewComplete = nextDraft.f2Draft?.reviewComplete ?? nextDraft.aiState === "분석 완료";
    setF2State(restoredF2State);
    setAudioSource(restoredAudioSource);
    audioSourceRef.current = restoredAudioSource;
    setAudioFile(null);
    setAudioPlaying(false);
    setFileError("");
    setRecordingSeconds(0);
    setRecordingPaused(false);
    setProcessingStep(0);
    setProposals(restoredProposals);
    setReviewComplete(restoredReviewComplete);
    baselineF2Ref.current = restoredAudioSource || restoredProposals.length || restoredF2State !== "empty"
      ? { audioSource: restoredAudioSource, proposals: restoredProposals, reviewComplete: restoredReviewComplete, state: restoredF2State }
      : null;
    setCloseDecision(null);
    setPendingConflictId(null);
    setSecurityWarning(null);
    setSaveError("");
    setIsComplexQuickAddOpen(false);
    setNewComplexName("");
    setNewComplexAddress("");
    setComplexQuickAddError("");
    setComplexQuickAddStatus("");
  }, [isOpen]);

  useEffect(() => {
    if (f2State !== "recording" || recordingPaused) return undefined;

    const interval = window.setInterval(() => {
      setRecordingSeconds((current) => current + 1);
    }, 1000);

    return () => window.clearInterval(interval);
  }, [f2State, recordingPaused]);

  useEffect(() => {
    if ((!closeDecision && !pendingConflictId) || !decisionRef.current) return undefined;

    decisionReturnFocusRef.current = document.activeElement;
    const dialog = decisionRef.current;
    const focusable = () => Array.from(
      dialog.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'),
    );
    focusable()[0]?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        if (pendingConflictId) setPendingConflictId(null);
        else setCloseDecision(null);
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = focusable();
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    dialog.addEventListener("keydown", handleKeyDown);
    return () => {
      dialog.removeEventListener("keydown", handleKeyDown);
      decisionReturnFocusRef.current?.focus?.();
    };
  }, [closeDecision, pendingConflictId]);

  useEffect(() => {
    if (!securityWarning && !saveError) return;
    feedbackRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    feedbackRef.current?.focus();
  }, [securityWarning, saveError]);

  useEffect(() => {
    if (f2State !== "processing") return undefined;

    const timer = window.setTimeout(() => {
      if (processingStep < PROCESS_STEPS.length - 1) {
        setProcessingStep((current) => current + 1);
        return;
      }

      if (audioSource?.name?.toLowerCase().includes("error")) {
        setF2State("error");
        return;
      }

      const nextProposals = buildProposals(draft);
      const nextDraft = { ...draft, aiState: "분석 완료" };
      setProposals(nextProposals);
      setReviewComplete(false);
      setDraft(nextDraft);
      setF2State("review");
    }, PROTOTYPE_ASSUMPTIONS.timing.f2ProcessingStepMs);

    return () => window.clearTimeout(timer);
  }, [audioSource, draft, f2State, processingStep]);

  const hasF2Work = Boolean(
    audioSource || proposals.length || ["recording", "sourceReady", "processing", "review", "conflict", "error"].includes(f2State),
  );
  const baselineF2 = baselineF2Ref.current;
  const currentF2 = hasF2Work ? { audioSource, proposals, reviewComplete, state: f2State } : null;
  const currentF2Ref = useRef(currentF2);
  currentF2Ref.current = currentF2;
  const isDirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(baselineRef.current) || JSON.stringify(currentF2) !== JSON.stringify(baselineF2),
    [baselineF2, currentF2, draft],
  );

  const completion = useMemo(
    () => ({
      complex: Boolean(draft.complex?.trim()),
      building: Boolean(draft.building?.trim()),
      unit: Boolean(draft.unit?.trim()),
      duplicate: Boolean(draft.duplicateCheck),
    }),
    [draft.building, draft.complex, draft.duplicateCheck, draft.unit],
  );

  const canComplete = Object.values(completion).every(Boolean);
  const changedFieldCount = Object.keys(draft).filter(
    (key) => JSON.stringify(draft[key]) !== JSON.stringify(baselineRef.current[key]),
  ).length + (JSON.stringify(currentF2) !== JSON.stringify(baselineF2) ? 1 : 0);
  const unmetCompletionLabels = [
    ["complex", "단지"],
    ["building", "동"],
    ["unit", "호"],
    ["duplicate", "중복 검사"],
  ].filter(([key]) => !completion[key]).map(([, label]) => label);
  const aiLabel =
    f2State === "review" && reviewComplete
      ? "분석 완료"
      : F2_STATE_LABELS[f2State] || draft.aiState || "대기";
  const personIndexOptions = useMemo(
    () => buildPersonIndexOptions(draft),
    [draft.owner, draft.tenant],
  );
  const selectedLogPerson = personIndexOptions.find((person) => person.key === draft.logPersonTarget) || null;

  const stagePatch = (patch) => {
    const nextDraft = { ...draft, ...patch };
    setDraft(nextDraft);
  };

  const stageField = (field, value) => stagePatch({ [field]: value });

  const selectLogPerson = (value) => {
    const selected = personIndexOptions.find((person) => person.key === value) || null;
    const currentLog = stripLeadingPersonIndex(draft.log);
    stagePatch({
      logPersonTarget: selected?.key || "",
      log: selected && currentLog ? `${selected.marker}${currentLog}` : currentLog,
    });
  };

  const updateLogText = (value) => {
    const plainText = stripLeadingPersonIndex(value);
    stageField("log", selectedLogPerson && plainText ? `${selectedLogPerson.marker}${plainText}` : plainText);
  };

  const indexedGeneratedLog = (value) => {
    const plainText = stripLeadingPersonIndex(value);
    return selectedLogPerson && plainText ? `${selectedLogPerson.marker}${plainText}` : plainText;
  };

  const selectComplex = (value) => {
    if (value === "__new_complex__") {
      setIsComplexQuickAddOpen(true);
      setComplexQuickAddError("");
      setComplexQuickAddStatus("");
      return;
    }
    stagePatch({ complex: value, duplicateCheck: value === draft.complex ? draft.duplicateCheck : false });
  };

  const createComplex = async () => {
    const name = newComplexName.trim();
    const address = newComplexAddress.trim();
    if (!name) {
      setComplexQuickAddError("단지명을 입력해 주세요.");
      return;
    }
    const duplicate = complexOptions.find((option) => {
      const optionName = typeof option === "string" ? option : option.name;
      const optionAddress = typeof option === "string" ? "" : option.address;
      return optionName?.toLocaleLowerCase("ko-KR") === name.toLocaleLowerCase("ko-KR")
        || (address && optionAddress && optionAddress === address);
    });
    if (duplicate) {
      setComplexQuickAddError(`이미 등록된 단지입니다: ${typeof duplicate === "string" ? duplicate : duplicate.name}`);
      return;
    }
    try {
      const created = await onCreateComplex?.({ name, address });
      const selectedName = created?.name || name;
      stagePatch({ complex: selectedName, duplicateCheck: false });
      setIsComplexQuickAddOpen(false);
      setNewComplexName("");
      setNewComplexAddress("");
      setComplexQuickAddError("");
      setComplexQuickAddStatus(`${selectedName} 단지를 추가하고 선택했습니다.`);
    } catch (error) {
      setComplexQuickAddError(error?.message || "단지를 추가하지 못했습니다.");
    }
  };

  const requestClose = () => {
    if (f2State === "processing") {
      setCloseDecision("processing");
      return;
    }
    if (isDirty) {
      setCloseDecision("dirty");
      return;
    }
    onClose?.();
  };

  const continueAfterAnalysisCancel = () => {
    setF2State(audioSource ? "sourceReady" : "empty");
    setProcessingStep(0);
    if (isDirty) {
      setCloseDecision("dirty");
      return;
    }
    setCloseDecision(null);
    onClose?.();
  };

  const deriveSaveState = () => {
    if ((f2State === "review" || f2State === "conflict") && !reviewComplete) {
      return "검토 필요";
    }
    return canComplete ? "저장 완료" : "작성 중";
  };

  const saveDraft = async ({ closeAfter = false } = {}) => {
    if (PROTOTYPE_ASSUMPTIONS.security.sensitivePattern.test(`${draft.memo || ""} ${draft.log || ""}`)) {
      setSecurityWarning("상담 로그 또는 비고에서 주민등록번호·계좌번호로 보이는 패턴을 찾았습니다. 마스킹한 뒤 다시 저장해 주세요.");
      return;
    }
    setSecurityWarning(null);
    setIsSaving(true);
    setSaveError("");
    const latestF2 = currentF2Ref.current;
    const latestAudioSource = audioSourceRef.current || latestF2?.audioSource || null;
    const nextF2Draft = latestAudioSource || latestF2
      ? { ...(latestF2 || {}), audioSource: latestAudioSource, state: latestF2?.state || f2State }
      : null;
    const nextDraft = { ...draft, saveState: deriveSaveState(), f2Draft: nextF2Draft };

    try {
      await onSave?.(nextDraft);
      window.dispatchEvent(new CustomEvent("prototype:f1-row-saved", { detail: nextDraft }));
      setDraft(nextDraft);
      baselineRef.current = nextDraft;
      baselineF2Ref.current = nextF2Draft;
      setCloseDecision(null);
      if (closeAfter) onClose?.();
    } catch (error) {
      setSaveError(error?.message || "저장하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsSaving(false);
    }
  };

  const discardAndClose = async () => {
    try {
      await onDiscard?.(baselineRef.current);
      setCloseDecision(null);
      onClose?.();
    } catch (error) {
      setSaveError(error?.message || "변경 내용을 되돌리지 못했습니다.");
      setCloseDecision(null);
    }
  };

  const startRecording = () => {
    setFileError("");
    setAudioPlaying(false);
    setRecordingSeconds(0);
    setRecordingPaused(false);
    setF2State("recording");
  };

  const stopRecording = () => {
    const duration = Math.max(recordingSeconds, PROTOTYPE_ASSUMPTIONS.audio.minimumRecordedSeconds);
    setAudioPlaying(false);
    const recordedSource = {
      kind: "recording",
      name: `상담 후 음성메모 ${formatSeconds(duration)}`,
      duration,
    };
    audioSourceRef.current = recordedSource;
    setAudioSource(recordedSource);
    setRecordingPaused(false);
    setF2State("sourceReady");
  };

  const handleFileInput = (_event, file) => {
    const extension = file?.name?.split(".").pop()?.toLowerCase();
    setAudioPlaying(false);
    if (!file || !["wav", "mp3", "m4a"].includes(extension)) {
      setAudioFile(null);
      setAudioSource(null);
      audioSourceRef.current = null;
      setFileError("WAV, MP3, M4A 형식의 음성 파일만 사용할 수 있습니다.");
      return;
    }
    if (file.size === 0) {
      setAudioFile(null);
      setAudioSource(null);
      audioSourceRef.current = null;
      setFileError("내용이 없는 음성 파일은 분석할 수 없습니다. 다시 녹음하거나 다른 파일을 선택해 주세요.");
      return;
    }
    if (
      PROTOTYPE_ASSUMPTIONS.audio.maxBytes &&
      file.size > PROTOTYPE_ASSUMPTIONS.audio.maxBytes
    ) {
      setAudioFile(null);
      setAudioSource(null);
      audioSourceRef.current = null;
      setFileError(`프로토타입 임시 상한 ${PROTOTYPE_ASSUMPTIONS.audio.maxLabel}을 초과했습니다. 실제 상한은 PO·보안 검토 후 확정합니다.`);
      return;
    }

    setFileError("");
    setAudioFile(file);
    const uploadedSource = { kind: "upload", name: file.name, size: file.size };
    audioSourceRef.current = uploadedSource;
    setAudioSource(uploadedSource);
    setF2State("sourceReady");
  };

  const clearAudioSource = () => {
    setAudioFile(null);
    setAudioSource(null);
    audioSourceRef.current = null;
    setAudioPlaying(false);
    setFileError("");
    setProcessingStep(0);
    setF2State("empty");
  };

  const startProcessing = () => {
    if (!audioSource) return;
    setAudioPlaying(false);
    setProcessingStep(0);
    setReviewComplete(false);
    setF2State("processing");
  };

  const toggleProposal = (proposalId, checked) => {
    setProposals((current) =>
      current.map((proposal) =>
        proposal.id === proposalId ? { ...proposal, selected: checked } : proposal,
      ),
    );
  };

  const applySelectedProposals = () => {
    const selected = proposals.filter((proposal) => proposal.selected);
    const unresolvedConflict = selected.find(
      (proposal) => proposal.status === "충돌" && !proposal.resolution,
    );

    if (unresolvedConflict) {
      setF2State("conflict");
      setPendingConflictId(unresolvedConflict.id);
      return;
    }

    const patch = selected.reduce((accumulator, proposal) => {
      if (proposal.fieldKey === "log") {
        const proposedLog = indexedGeneratedLog(proposal.proposal);
        accumulator.log = draft.log && proposedLog !== draft.log ? `${draft.log}\n${proposedLog}` : proposedLog;
        accumulator.logPersonTarget = selectedLogPerson?.key || "";
      } else {
        accumulator[proposal.fieldKey] = proposal.proposal;
      }
      return accumulator;
    }, {});

    if (selected.length > 0) stagePatch(patch);
    setProposals((current) =>
      current.map((proposal) =>
        proposal.selected ? { ...proposal, selected: false, status: "반영됨" } : proposal,
      ),
    );
    setReviewComplete(true);
  };

  const resolveConflict = (proposalId, resolution) => {
    setProposals((current) => {
      const next = current.map((proposal) => {
        if (proposal.id !== proposalId) return proposal;
        return {
          ...proposal,
          selected: resolution === "proposal",
          resolution,
          status: resolution === "proposal" ? "제안 선택" : "기존값 유지",
        };
      });

      const hasUnresolved = next.some(
        (proposal) => proposal.status === "충돌" && !proposal.resolution,
      );
      if (!hasUnresolved) setF2State("review");
      setPendingConflictId(null);
      return next;
    });
  };

  const renderUpload = (isReplacement = false) => (
    <div className="f2-upload">
      <div className="f2-upload__heading">
        <UploadIcon aria-hidden="true" />
        <div>
          <strong>{isReplacement ? "다른 파일로 교체" : "음성 파일 업로드"}</strong>
          <span>WAV, MP3, M4A · {PROTOTYPE_ASSUMPTIONS.audio.maxLabel ? `임시 상한 ${PROTOTYPE_ASSUMPTIONS.audio.maxLabel} (PO·보안 확정 필요)` : "업로드 상한 PO·보안 결정 대기"}</span>
        </div>
      </div>
      <FileUpload
        id={isReplacement ? "f2-audio-replacement" : "f2-audio-upload"}
        filename={audioFile?.name || ""}
        filenamePlaceholder="파일을 선택하거나 놓아주세요"
        filenameAriaLabel="선택한 음성 파일"
        browseButtonText="파일 선택"
        clearButtonText="지우기"
        value={audioFile || ""}
        hideDefaultPreview
        dropzoneProps={{
          accept: { "audio/*": [".wav", ".mp3", ".m4a"] },
          maxFiles: PROTOTYPE_ASSUMPTIONS.audio.oneSourcePerAnalysis ? 1 : undefined,
        }}
        onFileInputChange={handleFileInput}
        onClearClick={clearAudioSource}
        validated={fileError ? "error" : "default"}
      />
      {fileError && <p className="f2-upload__error" role="alert">{fileError}</p>}
    </div>
  );

  const renderReviewTable = () => (
    <div className="f2-review-table-wrap">
      <table className="pf-v6-c-table pf-m-grid-md pf-m-compact f2-review-table" aria-label="음성메모 분석 제안">
        <thead>
          <tr>
            <th scope="col">반영</th>
            <th scope="col">필드</th>
            <th scope="col">현재값</th>
            <th scope="col">제안</th>
            <th scope="col">상태</th>
            <th scope="col">근거</th>
          </tr>
        </thead>
        <tbody>
          {proposals.map((proposal) => (
            <tr key={proposal.id} className={proposal.selected ? "is-selected" : ""}>
              <td data-label="반영">
                <Checkbox
                  id={`proposal-${proposal.id}`}
                  aria-label={`${proposal.field} 제안 반영`}
                  isChecked={proposal.selected}
                  isDisabled={proposal.status === "반영됨"}
                  onChange={(_event, checked) => toggleProposal(proposal.id, checked)}
                />
              </td>
              <th scope="row" data-label="필드">
                {proposal.field}
              </th>
              <td data-label="현재값">{proposal.current}</td>
              <td data-label="제안">{proposal.fieldKey === "log" ? indexedGeneratedLog(proposal.proposal) : proposal.proposal}</td>
              <td data-label="상태">
                <Label
                  isCompact
                  status={
                    proposal.status === "충돌"
                      ? "warning"
                      : proposal.status === "반영됨"
                        ? "success"
                        : "info"
                  }
                >
                  {proposal.status}
                </Label>
                {f2State === "conflict" && proposal.status === "충돌" && (
                  <Button variant="link" size="sm" onClick={() => setPendingConflictId(proposal.id)}>
                    F1에서 결정
                  </Button>
                )}
              </td>
              <td data-label="근거" className="f2-review-table__evidence">
                {proposal.evidence}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderF2Body = () => {
    if (f2State === "recording") {
      return (
        <div className="f2-recording" role="status" aria-live="polite">
          <div className="f2-recording__indicator">
            <MicrophoneIcon aria-hidden="true" />
          </div>
          <div className="f2-recording__copy">
            <strong>{recordingPaused ? "녹음 일시정지" : "음성메모 녹음 중"}</strong>
            <span>{formatSeconds(recordingSeconds)}</span>
            <p>상담 종료 후 필요한 내용을 메모로 남기는 중입니다.</p>
          </div>
          <div className="f2-actions">
            <Button
              variant="secondary"
              icon={recordingPaused ? <PlayIcon /> : <PauseIcon />}
              onClick={() => setRecordingPaused((current) => !current)}
            >
              {recordingPaused ? "계속 녹음" : "일시정지"}
            </Button>
            <Button variant="primary" icon={<StopIcon />} onClick={stopRecording}>
              녹음 종료
            </Button>
          </div>
        </div>
      );
    }

    if (f2State === "sourceReady") {
      return (
        <div className="f2-source-ready">
          <div className="f2-source-card">
            <FileAudioIcon aria-hidden="true" />
            <div>
              <strong>{audioSource?.name}</strong>
              <span>{audioSource?.kind === "recording" ? "녹음한 음성메모" : "업로드한 음성 파일"}</span>
            </div>
            <div className="f2-source-card__actions">
              <Button variant="link" icon={audioPlaying ? <PauseIcon /> : <PlayIcon />} onClick={() => setAudioPlaying((current) => !current)}>
                {audioPlaying ? "재생 중지" : "미리 듣기"}
              </Button>
              <Button variant="link" icon={<TimesIcon />} onClick={clearAudioSource}>
                원본 제거
              </Button>
            </div>
          </div>
          <div className="f2-source-ready__grid">
            <div className="f2-guidance">
              <InfoCircleIcon aria-hidden="true" />
              <div>
                <strong>분석 전 확인</strong>
                <p>분석 결과는 F1 필드에 바로 저장되지 않습니다. 검토 표에서 선택한 항목만 작성값으로 반영됩니다.</p>
              </div>
            </div>
            {renderUpload(true)}
          </div>
          <div className="f2-actions f2-actions--end">
            <Button variant="primary" icon={<PlayIcon />} onClick={startProcessing}>
              분석 시작
            </Button>
          </div>
        </div>
      );
    }

    if (f2State === "processing") {
      return (
        <div className="f2-processing" aria-live="polite">
          <div className="f2-processing__heading">
            <div>
              <strong>음성메모를 분석하고 있습니다</strong>
              <span>상세 정보는 계속 확인할 수 있습니다.</span>
            </div>
            <Button
              variant="secondary"
              icon={<TimesIcon />}
              onClick={() => {
                setF2State("sourceReady");
                setProcessingStep(0);
              }}
            >
              분석 취소
            </Button>
          </div>
          <ProgressStepper isCenterAligned>
            {PROCESS_STEPS.map((step, index) => (
              <ProgressStep
                key={step}
                variant={index < processingStep ? "success" : index === processingStep ? "info" : "pending"}
                isCurrent={index === processingStep}
                aria-label={`${step} ${index < processingStep ? "완료" : index === processingStep ? "진행 중" : "대기"}`}
              >
                {step}
              </ProgressStep>
            ))}
          </ProgressStepper>
          <p className="f2-processing__note">분석이 실패해도 F1 작성값과 저장 기능에는 영향이 없습니다.</p>
        </div>
      );
    }

    if (f2State === "error") {
      return (
        <div className="f2-error">
          <Alert
            variant="danger"
            isInline
            isLiveRegion
            title="음성메모 분석을 완료하지 못했습니다"
            actionLinks={
              <Button variant="link" icon={<RedoIcon />} onClick={audioSource ? startProcessing : clearAudioSource}>
                {audioSource ? "다시 분석" : "새 원본 준비"}
              </Button>
            }
          >
            F1 데이터는 그대로 유지되며 저장할 수 있습니다. 원본이 있으면 다시 시도하거나 새 파일을 준비해 주세요.
          </Alert>
          {!audioSource && renderUpload(false)}
        </div>
      );
    }

    if (f2State === "review" || f2State === "conflict") {
      const selectedCount = proposals.filter((proposal) => proposal.selected).length;
      const conflictCount = proposals.filter((proposal) => proposal.status === "충돌" && !proposal.resolution).length;
      const appliedCount = proposals.filter((proposal) => proposal.status === "반영됨").length;
      return (
        <div className="f2-review">
          <Alert variant="info" isInline isPlain title="프로토타입 예시 분석 결과">
            아래 값과 근거 문구는 상태 검증용 fixture이며 실제 음성에서 추출한 값이 아닙니다.
          </Alert>
          <div className="f2-review__classification">
            <Label color="blue" variant="outline">상담 유형 · 매도의뢰</Label>
            <span>현재 장부: 매물장 · 장부 불일치 없음</span>
          </div>
          <div className="f2-review__summary" role="status" aria-live="polite">
            <div><span>전체 제안</span><strong>{proposals.length}건</strong></div>
            <div><span>선택</span><strong>{selectedCount}건</strong></div>
            <div className={conflictCount ? "is-warning" : ""}><span>결정 필요</span><strong>{conflictCount}건</strong></div>
            <div><span>반영 완료</span><strong>{appliedCount}건</strong></div>
          </div>
          {f2State === "conflict" && (
            <Alert variant="warning" isInline title="현재값과 다른 제안이 선택되었습니다">
              충돌 항목마다 기존값 유지 또는 제안 적용을 먼저 결정해 주세요.
            </Alert>
          )}
          <div className="f2-review__heading">
            <div>
              <strong>필드 제안 검토</strong>
              <span>현재값과 제안값을 비교한 뒤 반영할 항목만 선택하세요. 저장은 우측 F1 작업에서 별도로 실행합니다.</span>
            </div>
          </div>
          {renderReviewTable()}
          <div className="f2-review__action-bar">
            <span>{selectedCount ? `${selectedCount}건을 F1 작성값에 반영합니다` : "반영할 제안을 선택하세요"}</span>
            <Button
              variant="primary"
              icon={<CheckCircleIcon />}
              onClick={applySelectedProposals}
              isDisabled={!selectedCount}
            >
              선택 항목 반영 · {selectedCount}건
            </Button>
          </div>
          <div className="f2-review__footer">
            <div className="f2-actions">
              <Button variant="secondary" icon={<RedoIcon />} onClick={() => setF2State(audioSource ? "sourceReady" : "empty")}>
                원본부터 다시 분석
              </Button>
              {!reviewComplete && (
                <Button variant="link" icon={<CheckCircleIcon />} onClick={() => setReviewComplete(true)}>
                  변경 없이 검토 완료
                </Button>
              )}
            </div>
            {reviewComplete && (
              <Label status="success" icon={<CheckCircleIcon />}>
                검토 완료
              </Label>
            )}
          </div>
        </div>
      );
    }

    return (
      <div className="f2-empty">
        <button className="f2-record-choice" type="button" onClick={startRecording}>
          <span className="f2-record-choice__icon">
            <MicrophoneIcon aria-hidden="true" />
          </span>
          <strong>상담 후 음성메모 녹음</strong>
          <span>상담이 끝난 뒤 기억할 내용을 직접 남깁니다.</span>
        </button>
        {renderUpload(false)}
      </div>
    );
  };

  return (
    <Modal
      isOpen={isOpen}
      variant="large"
      className="detail-workspace-modal"
      aria-labelledby="detail-workspace-title"
      onEscapePress={requestClose}
    >
      <ModalHeader labelId="detail-workspace-title">
        <div className="detail-workspace__header">
          <div className="detail-workspace__title-group">
            <Title headingLevel="h1" id="detail-workspace-title" size="xl">
              세대 상세
            </Title>
            <span>
              {draft.complex || "단지 미입력"} · {draft.building || "동 미입력"} · {draft.unit || "호 미입력"}
            </span>
          </div>
          <Button className="detail-workspace__voice-entry" variant="secondary" icon={<MicrophoneIcon />} aria-controls="f2-panel" onClick={focusF2Panel}>
            음성메모 입력
          </Button>
          <div className="detail-workspace__state-summary" aria-label="상세 상태">
            <StateSummary label="저장 상태" value={draft.saveState} status={statusForStorage(draft.saveState)} />
            <StateSummary label="AI 상태" value={aiLabel} status={statusForAI(f2State, reviewComplete)} />
            <StateSummary
              label="업무 상태"
              value={draft.householdState}
              status={statusForHousehold(draft.householdState)}
            />
          </div>
        </div>
      </ModalHeader>

      <ModalBody className="detail-workspace__modal-body">
        <div className="detail-workspace__layout" data-screen-id="F1-MOD-010 F1-MOD-130" data-requirement-ids="F1-UD-01~26, F1-MD-08, F1-LG-01~06, F1-LG-08~34, F1-TR-01~05, F2-POP-01, F2-SAVE-01~03, F2-SAVE-05~06, F2-SAVE-08; F1-GR-32, F1-GR-35~36, F1-ST-18, F2-POP-02, F2-SAVE-07">
          <main className="detail-workspace__content">
            {securityWarning && (
              <Alert ref={feedbackRef} tabIndex={-1} className="detail-workspace__save-error" variant="danger" isInline isLiveRegion title="개인정보 패턴을 확인해 주세요" data-screen-id="F1-MOD-140" data-requirement-ids="F1-SE-03~05, F1-DM-16, F1-ST-13, F2-SEC-06">
                {securityWarning}
              </Alert>
            )}
            {saveError && (
              <Alert ref={feedbackRef} tabIndex={-1} className="detail-workspace__save-error" variant="danger" isInline isLiveRegion title="저장 오류">
                {saveError}
              </Alert>
            )}

            <nav className="detail-section-nav" aria-label="세대 상세 구역">
              <button type="button" onClick={() => focusDetailSection("detail-section-basic", "detail-basic-heading")}>세대·거래</button>
              <button type="button" onClick={() => focusDetailSection("detail-section-memo", "detail-memo-heading")}>비고</button>
              <button type="button" onClick={() => focusDetailSection("detail-section-people", "detail-people-heading")}>인물</button>
              <button type="button" onClick={focusF2Panel}>음성메모</button>
              <button type="button" onClick={() => focusDetailSection("detail-section-log", "detail-log-heading")}>상담 로그</button>
              {isCrossMatchOpen && <button type="button" onClick={() => focusDetailSection("cross-match-panel", "cross-match-panel-title")}>교차 판정</button>}
            </nav>

            <section id="detail-section-basic" className="detail-section" aria-labelledby="detail-basic-heading">
              <div className="detail-section__heading">
                <Title headingLevel="h2" id="detail-basic-heading" size="md" tabIndex={-1}>
                  세대 및 거래 정보
                </Title>
                <span>불완전한 정보도 작성 중 상태로 보존할 수 있습니다.</span>
              </div>
              <div className="detail-info-grid">
                <div className="detail-info-column">
                  <h3>세대 식별</h3>
                  <div className="detail-field detail-complex-field">
                    <label className="detail-field__label" htmlFor="detail-complex">단지</label>
                    <FormSelect id="detail-complex" value={draft.complex} onChange={(_event, value) => selectComplex(value)}>
                      <FormSelectOption value="" label="단지를 선택하세요" isDisabled />
                      {complexOptions.map((option) => {
                        const name = typeof option === "string" ? option : option.name;
                        return <FormSelectOption key={name} value={name} label={name} />;
                      })}
                      {draft.complex && !complexOptions.some((option) => (typeof option === "string" ? option : option.name) === draft.complex) && <FormSelectOption value={draft.complex} label={draft.complex} />}
                      {String(draft.id).startsWith("DRAFT-") && <FormSelectOption value="__new_complex__" label="＋ 새 단지 추가" />}
                    </FormSelect>
                    {String(draft.id).startsWith("DRAFT-") && <Button variant="link" isInline onClick={() => setIsComplexQuickAddOpen(true)}>새 단지 추가</Button>}
                    {isComplexQuickAddOpen && (
                      <div className="detail-complex-quick-add" aria-labelledby="detail-complex-quick-add-title">
                        <strong id="detail-complex-quick-add-title">새 단지 빠른 추가</strong>
                        <span>프로토타입 임시 기준: 단지명 필수 · 주소 선택</span>
                        <label htmlFor="detail-new-complex-name">단지명</label>
                        <TextInput id="detail-new-complex-name" value={newComplexName} validated={complexQuickAddError ? "error" : "default"} aria-invalid={Boolean(complexQuickAddError)} aria-describedby={complexQuickAddError ? "detail-complex-quick-add-error" : undefined} onChange={(_event, value) => setNewComplexName(value)} />
                        <label htmlFor="detail-new-complex-address">주소</label>
                        <TextInput id="detail-new-complex-address" value={newComplexAddress} onChange={(_event, value) => setNewComplexAddress(value)} />
                        {complexQuickAddError && <span id="detail-complex-quick-add-error" role="alert">{complexQuickAddError}</span>}
                        <div className="f2-actions">
                          <Button size="sm" onClick={createComplex}>추가 후 선택</Button>
                          <Button size="sm" variant="link" onClick={() => { setIsComplexQuickAddOpen(false); setComplexQuickAddError(""); }}>취소</Button>
                        </div>
                      </div>
                    )}
                    {complexQuickAddStatus && <span className="detail-complex-quick-add__status" role="status" aria-live="polite">{complexQuickAddStatus}</span>}
                  </div>
                  <div className="detail-inline-fields">
                    <DetailField id="detail-building" label="동" value={draft.building} onChange={(value) => stageField("building", value)} />
                    <DetailField id="detail-unit" label="호" value={draft.unit} onChange={(value) => stageField("unit", value)} />
                  </div>
                  <div className="detail-inline-fields">
                    <DetailField id="detail-area" label="평형" value={draft.area} onChange={(value) => stageField("area", value)} />
                    <DetailField id="detail-direction" label="향" value={draft.direction} onChange={(value) => stageField("direction", value)} />
                  </div>
                  <DetailField id="detail-expiry" label="계약 만기일" type="date" value={draft.expiry} onChange={(value) => stageField("expiry", value)} />
                </div>

                <div className="detail-info-column">
                  <h3>거래 조건</h3>
                  <DetailSelect id="detail-listing-type" label="거래 유형" value={draft.listingType} options={["매매", "전세", "월세"]} onChange={(value) => stageField("listingType", value)} />
                  <DetailField id="detail-price" label="매매가" value={draft.price} onChange={(value) => stageField("price", value)} placeholder="예: 12억 8,000만 원" />
                  <div className="detail-inline-fields">
                    <DetailField id="detail-deposit" label="보증금" value={draft.deposit} onChange={(value) => stageField("deposit", value)} />
                    <DetailField id="detail-rent" label="월세" value={draft.rent} onChange={(value) => stageField("rent", value)} />
                  </div>
                  <DetailField id="detail-move-in" label="입주 가능일" type="date" value={draft.moveIn} onChange={(value) => stageField("moveIn", value)} />
                </div>

                <div className="detail-info-column">
                  <h3>업무 관리</h3>
                  <DetailSelect id="detail-household-state" label="업무 상태" value={draft.householdState} options={["일반", "매물화", "거래진행"]} onChange={(value) => stageField("householdState", value)} />
                  <DetailField id="detail-assignee" label="담당자" value={draft.assignee} onChange={(value) => stageField("assignee", value)} />
                  <DetailField id="detail-last-contact" label="최근 상담일" type="date" value={draft.lastContact} onChange={(value) => stageField("lastContact", value)} />
                  <div className="detail-inline-fields">
                    <DetailField id="detail-parking" label="주차" value={draft.parking} onChange={(value) => stageField("parking", value)} />
                    <DetailField id="detail-tax" label="세금 메모" value={draft.tax} onChange={(value) => stageField("tax", value)} />
                  </div>
                  <div className={`detail-duplicate-check ${draft.duplicateCheck ? "is-complete" : ""}`}>
                    <Checkbox
                      id="detail-duplicate-check"
                      label="중복 검사 완료"
                      isChecked={draft.duplicateCheck}
                      onChange={(_event, checked) => stageField("duplicateCheck", checked)}
                    />
                    <span>저장 완료 전환에 필요한 확인입니다.</span>
                  </div>
                </div>
              </div>
            </section>

            <section id="detail-section-memo" className="detail-section" aria-labelledby="detail-memo-heading">
              <div className="detail-section__heading">
                <Title headingLevel="h2" id="detail-memo-heading" size="md" tabIndex={-1}>
                  비고
                </Title>
              </div>
              <TextArea
                id="detail-memo"
                aria-label="세대 비고"
                value={draft.memo}
                placeholder="세대 관리에 필요한 참고사항을 입력하세요."
                resizeOrientation="vertical"
                onChange={(_event, value) => stageField("memo", value)}
              />
            </section>

            <section id="detail-section-people" className="detail-section" aria-labelledby="detail-people-heading">
              <div className="detail-section__heading">
                <Title headingLevel="h2" id="detail-people-heading" size="md" tabIndex={-1}>
                  임대인 · 관계 · 임차인
                </Title>
              </div>
              <div className="detail-people-grid">
                <div className="detail-person-card">
                  <h3>임대인</h3>
                  <DetailField id="detail-owner" label="성명" value={draft.owner} onChange={(value) => stageField("owner", value)} />
                </div>
                <div className="detail-person-card">
                  <h3>관계 및 연락</h3>
                  <DetailSelect id="detail-relationship" label="통화자 관계" value={draft.relationship} options={["본인", "배우자", "가족", "대리인", "기타"]} onChange={(value) => stageField("relationship", value)} />
                  <DetailField id="detail-phone" label="연락처" type="tel" value={draft.phone} onChange={(value) => stageField("phone", value)} placeholder="번호 입력" />
                </div>
                <div className="detail-person-card">
                  <h3>임차인</h3>
                  <DetailField id="detail-tenant" label="성명" value={draft.tenant} onChange={(value) => stageField("tenant", value)} />
                  <DetailField id="detail-consent" label="연락 동의 기록" value={draft.consent} onChange={(value) => stageField("consent", value)} />
                </div>
              </div>
            </section>

            <section ref={f2PanelRef} id="f2-panel" className="detail-section detail-section--f2" aria-labelledby="f2-heading" data-screen-id="F2-PNL-010 F2-PNL-020" data-requirement-ids="F2-REC-01~06, F2-STT-01~05, F2-SEC-01, F1-ST-01~05, F1-ST-12~15; F2-ANL-02~06, F2-ANL-08, F2-REV-01~04, F2-SAVE-05, F2-SAVE-08, F2-SEC-06, F1-LG-33~34">
              <div className="f2-panel__header">
                <div ref={f2HeadingRef} tabIndex={-1}>
                  <span className="detail-section__eyebrow">F2 · 상세 내부 기능</span>
                  <Title headingLevel="h2" id="f2-heading" size="lg">
                    상담 후 음성메모 입력
                  </Title>
                  <p>녹음한 메모 또는 업로드한 음성 파일에서 F1 필드 후보를 제안합니다.</p>
                </div>
                <Label status={statusForAI(f2State, reviewComplete)}>{aiLabel}</Label>
              </div>
              <Alert className="f2-security-note" variant="warning" isInline isPlain title="민감정보는 입력하지 마세요">
                상담 종료 후 메모만 사용하며 주민등록번호·계좌번호·비밀번호는 녹음하거나 업로드하지 마세요. 원본 접근과 분석 이력은 업무 권한에 따라 관리합니다.
              </Alert>
              <div className="f2-panel__body">{renderF2Body()}</div>
            </section>

            <section id="detail-section-log" className="detail-section" aria-labelledby="detail-log-heading">
              <div className="detail-section__heading">
                <div>
                  <Title headingLevel="h2" id="detail-log-heading" size="md" tabIndex={-1}>
                    상담 로그
                  </Title>
                  <span>AI 제안 반영 시 기존 로그 아래에 요약이 추가됩니다.</span>
                </div>
                <HistoryIcon aria-hidden="true" />
              </div>
              <div className="detail-log-person-index">
                <label htmlFor="detail-log-person">상담 상대 인물</label>
                <FormSelect id="detail-log-person" value={draft.logPersonTarget || ""} onChange={(_event, value) => selectLogPerson(value)}>
                  <FormSelectOption value="" label="미지정 · 1번 인물로 추정하지 않음" />
                  {personIndexOptions.map((person) => (
                    <FormSelectOption key={person.key} value={person.key} label={`${person.role} ${person.marker} · ${person.name}`} />
                  ))}
                </FormSelect>
                <div className="detail-log-person-index__status" role="status" aria-live="polite">
                  <Label status={selectedLogPerson ? "success" : "warning"} isCompact>
                    {selectedLogPerson ? `자동 표기 ${selectedLogPerson.marker}` : "상대 미지정"}
                  </Label>
                  <span>{selectedLogPerson ? `${selectedLogPerson.role} 등록 ${selectedLogPerson.position}번 · ${selectedLogPerson.name}` : "①②③은 통화 회차나 발신·수신이 아니라 같은 역할의 인물 등록 순서입니다."}</span>
                </div>
              </div>
              <TextArea
                id="detail-log"
                aria-label="상담 로그"
                value={draft.log}
                placeholder="상담 내용, 다음 연락 일정, 요청사항을 기록하세요."
                resizeOrientation="vertical"
                onChange={(_event, value) => updateLogText(value)}
              />
              <div className="detail-log-meta">
                <span>유입 경로: {draft.source || "미입력"}</span>
                <span>담당자: {draft.assignee || "미지정"}</span>
              </div>
            </section>

            {crossMatchPanel}
          </main>

          <aside className="detail-workspace__action-rail" aria-label="F1 상세 작업">
            <div className={`action-rail__dirty ${isDirty ? "is-dirty" : ""}`} aria-live="polite">
              <span>{isDirty ? "저장하지 않은 변경 있음" : "모든 변경 저장됨"}</span>
            </div>

            <div className="action-rail__primary">
              <span className="action-rail__eyebrow">주요 작업</span>
              <Button variant="primary" icon={<SaveIcon />} onClick={() => saveDraft()} isLoading={isSaving} isDisabled={isSaving}>
                저장
              </Button>
              <Button variant="secondary" icon={<TimesIcon />} onClick={requestClose}>
                상세 닫기
              </Button>
              <Button variant="secondary" icon={<SearchIcon />} onClick={() => onOpenCrossMatch?.(draft)} aria-expanded={isCrossMatchOpen} aria-controls="cross-match-panel">
                교차 매칭
              </Button>
            </div>

            <Divider />

            <div className="action-rail__status">
              <div className="action-rail__status-heading">
                <strong>저장 완료 조건</strong>
                <Label status={canComplete ? "success" : "warning"} isCompact>
                  {Object.values(completion).filter(Boolean).length}/4
                </Label>
              </div>
              <ul>
                <li className={completion.complex ? "is-complete" : ""}>
                  {completion.complex ? <CheckCircleIcon aria-hidden="true" /> : <InfoCircleIcon aria-hidden="true" />}
                  단지
                </li>
                <li className={completion.building ? "is-complete" : ""}>
                  {completion.building ? <CheckCircleIcon aria-hidden="true" /> : <InfoCircleIcon aria-hidden="true" />}
                  동
                </li>
                <li className={completion.unit ? "is-complete" : ""}>
                  {completion.unit ? <CheckCircleIcon aria-hidden="true" /> : <InfoCircleIcon aria-hidden="true" />}
                  호
                </li>
                <li className={completion.duplicate ? "is-complete" : ""}>
                  {completion.duplicate ? <CheckCircleIcon aria-hidden="true" /> : <InfoCircleIcon aria-hidden="true" />}
                  중복 검사
                </li>
              </ul>
              {!canComplete && <p>조건 미충족 상태에서도 작성 중으로 저장할 수 있습니다.</p>}
            </div>

          </aside>
        </div>

        {pendingConflictId && (
          <div className="detail-workspace__decision-layer" role="presentation" data-screen-id="F1-MOD-145" data-requirement-ids="F1-ST-06~07, F2-REV-02, F2-ANL-08">
            <section ref={decisionRef} className="detail-workspace__decision-card" role="alertdialog" aria-modal="true" aria-labelledby="conflict-decision-title">
              <div className="decision-card__icon decision-card__icon--warning"><ExclamationTriangleIcon aria-hidden="true" /></div>
              <Title headingLevel="h2" id="conflict-decision-title" size="lg">AI 제안과 기존 값 중 유지할 값을 선택하세요</Title>
              <p>이 결정은 F1 상세이 소유하며, 로그 제안은 기존 로그에 추가됩니다.</p>
              <div className="decision-card__actions">
                <Button variant="primary" onClick={() => resolveConflict(pendingConflictId, "current")}>기존값 유지</Button>
                <Button variant="secondary" onClick={() => resolveConflict(pendingConflictId, "proposal")}>제안 적용</Button>
                <Button variant="link" onClick={() => setPendingConflictId(null)}>취소</Button>
              </div>
            </section>
          </div>
        )}

        {closeDecision && (
          <div className="detail-workspace__decision-layer" role="presentation">
            <section
              ref={decisionRef}
              className="detail-workspace__decision-card"
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="close-decision-title"
              aria-describedby="close-decision-description"
            >
              {closeDecision === "processing" ? (
                <>
                  <div className="decision-card__icon decision-card__icon--warning">
                    <ExclamationTriangleIcon aria-hidden="true" />
                  </div>
                  <Title headingLevel="h2" id="close-decision-title" size="lg">
                    진행 중인 분석을 취소할까요?
                  </Title>
                  <p id="close-decision-description">
                    분석만 취소됩니다. 이후 저장하지 않은 F1 변경사항이 있으면 저장 여부를 다시 확인합니다.
                  </p>
                  <div className="decision-card__actions">
                    <Button variant="primary" onClick={continueAfterAnalysisCancel}>
                      분석 취소하고 닫기 계속
                    </Button>
                    <Button variant="secondary" onClick={() => setCloseDecision(null)}>
                      분석 계속
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="decision-card__icon">
                    <SaveIcon aria-hidden="true" />
                  </div>
                  <Title headingLevel="h2" id="close-decision-title" size="lg">
                    변경사항을 저장할까요?
                  </Title>
                  <p id="close-decision-description">
                    불완전한 데이터도 작성 중으로 저장할 수 있습니다. 저장 완료는 단지, 동, 호, 중복 검사 조건을 충족해야 합니다.
                  </p>
                  <dl className="decision-card__summary">
                    <div><dt>변경 항목</dt><dd>{changedFieldCount}개</dd></div>
                    <div><dt>저장 후 상태</dt><dd>{deriveSaveState()}</dd></div>
                    <div><dt>미충족 조건</dt><dd>{unmetCompletionLabels.join(", ") || "없음"}</dd></div>
                  </dl>
                  {saveError && (
                    <Alert className="decision-card__error" variant="danger" isInline title="저장하지 못했습니다">
                      {saveError}
                    </Alert>
                  )}
                  <div className="decision-card__actions">
                    <Button variant="primary" onClick={() => saveDraft({ closeAfter: true })} isLoading={isSaving} isDisabled={isSaving}>
                      저장
                    </Button>
                    <Button variant="danger" onClick={discardAndClose} isDisabled={isSaving}>
                      저장 안 함
                    </Button>
                    <Button variant="secondary" onClick={() => setCloseDecision(null)} isDisabled={isSaving}>
                      취소
                    </Button>
                  </div>
                </>
              )}
            </section>
          </div>
        )}
      </ModalBody>
    </Modal>
  );
}
