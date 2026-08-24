import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Checkbox, Divider, FormSelect, FormSelectOption, Label, Modal, ModalBody, ModalFooter, ModalHeader, TextArea, TextInput, Title } from "@patternfly/react-core";
import { CheckCircleIcon, InfoCircleIcon, SaveIcon, SearchIcon, TimesIcon, TrashIcon } from "@patternfly/react-icons";
import { PROTOTYPE_ASSUMPTIONS } from "../config/prototypeAssumptions.js";
import VoiceMemoModal from "./VoiceMemoModal.jsx";
import { DEAL_TYPE_CHOICES, dealTypePatch, dealTypeValue } from "./ledger/model/dealType.ts";
import { nextPhoneInput } from "./ledger/model/phone.ts";
import RelationEditModal from "./RelationEditModal.jsx";
import "@patternfly/react-core/dist/styles/base.css";
import "./DetailWorkspace.css";

const EMPTY_ROW = { id: "", complex: "", building: "", unit: "", saveState: "임시저장", aiState: "대기", householdState: "일반", area: "", listingType: "매매", price: "", deposit: "", rent: "", expiry: "", owner: "", relationship: "본인", tenant: "", phone: "", direction: "", floor: "", rooms: "", baths: "", lastContact: "", log: "", assignee: "", source: "", consent: "", memo: "", parking: "", moveIn: "", tax: "", duplicateCheck: false, people: [] };

function normalizeRow(row) { const normalized = { ...EMPTY_ROW, ...(row || {}) }; normalized.saveState = normalized.saveState === "저장 완료" ? "저장 완료" : "임시저장"; normalized.price = normalized.price || (normalized.listingType === "매매" ? normalized.salePrice : normalized.listingType === "전세" ? normalized.leaseDeposit : normalized.rentCondition) || ""; normalized.phone = normalized.phone || normalized.ownerPhone || ""; if (typeof normalized.duplicateCheck !== "boolean") normalized.duplicateCheck = Boolean(normalized.id && normalized.complex && normalized.building && normalized.unit); return normalized; }
function splitPeople(value) { return String(value || "").split(/[·,\/\n]+/).map((name) => name.trim()).filter(Boolean); }
function peopleForDraft(draft) { if (Array.isArray(draft.people) && draft.people.length) return draft.people; const owners = splitPeople(draft.owner).map((name, index) => ({ id: `owner-${index}`, name, role: "임대인", relationship: draft.relationship || "본인", position: index + 1, phone: index === 0 ? draft.phone : "", consent: draft.consent === "동의" ? "O" : "X", tag: "" })); const tenants = splitPeople(draft.tenant).map((name, index) => ({ id: `tenant-${index}`, name, role: "임차인", relationship: "본인", position: index + 1, phone: "", consent: "X", tag: "" })); return [...owners, ...tenants]; }
function statusForStorage(value) { return value === "저장 완료" ? "success" : "info"; }
/**
 * 단지 선택기.
 *
 * 네이티브 select는 항목 안에 버튼을 넣을 수 없어 직접 목록을 그린다.
 * 단지는 세대가 참조하는 마스터라 실수로 지우면 곤란하므로, x를 누르면 바로 지우지 않고
 * 그 자리에서 한 번 더 확인받는다.
 */
function ComplexPicker({ labelId, value, options = [], onSelect, onDelete }) {
  const [open, setOpen] = useState(false);
  const [pendingId, setPendingId] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const rootRef = useRef(null);

  const normalized = options.map((option) => (typeof option === "string" ? { id: option, name: option } : option));

  useEffect(() => {
    if (!open) return undefined;
    const handlePointer = (event) => { if (!rootRef.current?.contains(event.target)) setOpen(false); };
    const handleKey = (event) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  useEffect(() => { if (!open) { setPendingId(null); setError(""); } }, [open]);

  const removeComplex = async (option) => {
    setBusyId(option.id);
    setError("");
    try {
      await onDelete?.(option);
      setPendingId(null);
      if (option.name === value) onSelect?.("");
    } catch (cause) {
      setError(cause?.message || "단지를 삭제하지 못했습니다.");
    } finally {
      setBusyId(null);
    }
  };

  return <div className="complex-picker" ref={rootRef}>
    <button
      type="button"
      id="detail-complex"
      className="complex-picker__toggle"
      aria-haspopup="true"
      aria-expanded={open}
      aria-labelledby={`${labelId} detail-complex`}
      onClick={() => setOpen((current) => !current)}
    >
      <span>{value || "단지를 선택하세요"}</span>
      <span aria-hidden="true">▾</span>
    </button>
    {open && <div className="complex-picker__menu">
      <ul aria-label="단지 목록">
        {normalized.length === 0 && <li className="complex-picker__empty">등록된 단지가 없습니다.</li>}
        {normalized.map((option) => <li key={option.id} className={option.name === value ? "is-selected" : ""}>
          <button type="button" className="complex-picker__pick" onClick={() => { onSelect?.(option.name); setOpen(false); }}>
            {option.name}
          </button>
          {pendingId === option.id ? <span className="complex-picker__confirm">
            <span className="complex-picker__confirm-note">{`'${option.name}'을(를) 단지 목록에서 지웁니다. 세대가 등록돼 있으면 거절되며, 화면에서 되돌리는 기능은 없습니다.`}</span>
            <button type="button" onClick={() => removeComplex(option)} disabled={busyId === option.id}>삭제</button>
            <button type="button" onClick={() => setPendingId(null)} disabled={busyId === option.id}>취소</button>
          </span> : <button
            type="button"
            className="complex-picker__remove"
            aria-label={`${option.name} 단지 삭제`}
            onClick={() => { setError(""); setPendingId(option.id); }}
          >×</button>}
        </li>)}
      </ul>
      {error && <p className="complex-picker__error" role="alert">{error}</p>}
    </div>}
  </div>;
}

function DetailField({ id, label, value, onChange, type = "text", placeholder = "입력", span }) { return <div className="detail-field" data-span={span}><label className="detail-field__label" htmlFor={id}>{label}</label><TextInput id={id} type={type} value={value ?? ""} placeholder={placeholder} onChange={(_event, nextValue) => onChange(nextValue)} /></div>; }
/** 여러 줄로 적는 짧은 메모 칸. 스펙처럼 한 줄로는 모자란 항목에 쓴다. */
function DetailTextAreaField({ id, label, value, onChange, placeholder = "입력", className = "" }) { return <div className={`detail-field detail-field--area ${className}`.trim()}><label className="detail-field__label" htmlFor={id}>{label}</label><TextArea id={id} value={value ?? ""} placeholder={placeholder} resizeOrientation="vertical" onChange={(_event, nextValue) => onChange(nextValue)} /></div>; }
/**
 * 날짜와 자유 문구를 함께 받는 필드.
 *
 * 명도처럼 "즉시", "협의"로 적기도 하고 날짜로 적기도 하는 칸에 쓴다.
 * 글자는 그대로 두고, 옆의 달력에서 날짜를 고르면 그 날짜로 채운다.
 */
function DetailTextOrDateField({ id, label, value, onChange }) {
  const isIsoDate = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
  return <div className="detail-field">
    <label className="detail-field__label" htmlFor={id}>{label}</label>
    <div className="detail-field__text-or-date">
      <TextInput id={id} value={value ?? ""} placeholder="즉시·협의 또는 날짜" onChange={(_event, next) => onChange(next)} />
      <label className="detail-field__date-picker">
        <span className="pf-v6-screen-reader">{`${label} 날짜로 선택`}</span>
        <input type="date" value={isIsoDate ? value : ""} onChange={(event) => onChange(event.target.value)} />
      </label>
    </div>
  </div>;
}

/** 전화번호 필드. 형식 규칙은 features/ledger의 phone 모듈이 정본이다. */
function DetailPhoneField({ id, label, value, onChange }) {
  const current = value ?? "";
  return <div className="detail-field">
    <label className="detail-field__label" htmlFor={id}>{label}</label>
    <TextInput
      id={id}
      type="tel"
      inputMode="tel"
      autoComplete="tel"
      value={current}
      placeholder="010-0000-0000"
      onChange={(_event, next) => onChange(nextPhoneInput(current, next))}
    />
  </div>;
}

function DetailSelect({ id, label, value, options, onChange }) { return <div className="detail-field"><label className="detail-field__label" htmlFor={id}>{label}</label><FormSelect id={id} value={value || options[0]} onChange={(_event, nextValue) => onChange(nextValue)}>{options.map((option) => <FormSelectOption key={option} value={option} label={option} />)}</FormSelect></div>; }
function StateSummary({ label, value, status }) { return <div className="detail-workspace__state-item" aria-live="polite"><span>{label}</span><Label status={status} isCompact>{value}</Label></div>; }

export default function DetailWorkspace({ row, isOpen, onClose, onSave, onDiscard, onDelete, onDeleteComplex, onOpenCrossMatch, isCrossMatchOpen = false, crossMatchPanel, focusF2Request = 0, complexOptions = [], onCreateComplex }) {
  const [draft, setDraft] = useState(() => normalizeRow(row));
  const baselineRef = useRef(normalizeRow(row));
  const [f2Open, setF2Open] = useState(false);
  const [relationOpen, setRelationOpen] = useState(false);
  const [relationTarget, setRelationTarget] = useState(null);
  const [closeDecision, setCloseDecision] = useState(false);
  const [deleteDecision, setDeleteDecision] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [securityWarning, setSecurityWarning] = useState("");
  const [securityConfirmed, setSecurityConfirmed] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [complexQuickAddOpen, setComplexQuickAddOpen] = useState(false);
  const [newComplexName, setNewComplexName] = useState("");
  const [newComplexAddress, setNewComplexAddress] = useState("");
  const [complexQuickAddError, setComplexQuickAddError] = useState("");
  const [complexQuickAddStatus, setComplexQuickAddStatus] = useState("");
  const initializedOpenRef = useRef(false);
  const securityRef = useRef(null);
  const deleteTriggerRef = useRef(null);

  useEffect(() => { if (!isOpen) { initializedOpenRef.current = false; return; } if (initializedOpenRef.current) return; initializedOpenRef.current = true; const next = normalizeRow(row); setDraft(next); baselineRef.current = next; setF2Open(Boolean(focusF2Request)); setRelationOpen(false); setCloseDecision(false); setDeleteDecision(false); setIsDeleting(false); setDeleteError(""); setSecurityWarning(""); setSecurityConfirmed(false); setSaveError(""); setComplexQuickAddOpen(false); setComplexQuickAddError(""); setComplexQuickAddStatus(""); }, [focusF2Request, isOpen, row]);
  useEffect(() => { if (isOpen && focusF2Request) setF2Open(true); }, [focusF2Request, isOpen]);
  useEffect(() => { if (securityWarning) securityRef.current?.focus(); }, [securityWarning]);
  /*
   * 상세는 항상 맨 위(기본 정보)에서 시작한다.
   * 안쪽 패널이 열리며 스크롤을 가져가는 일이 있어 열릴 때 한 번 되돌린다.
   */
  useEffect(() => {
    if (!isOpen) return undefined;
    const frame = window.requestAnimationFrame(() => {
      document.querySelectorAll(".detail-workspace-modal .pf-v6-c-modal-box__body").forEach((node) => {
        node.scrollTop = 0;
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen, row?.id]);


  const stagePatch = (patch) => setDraft((current) => ({ ...current, ...patch }));
  const stageField = (field, value) => stagePatch({ [field]: value });
  /* 거래유형은 그리드와 같은 규칙을 쓴다. 여기만 단일 선택으로 두면 상세를 열고 저장하는 것만으로 다른 유형이 지워진다. */
  const stageListingType = (value) => {
    const patch = dealTypePatch(value);
    const typedPrice = patch.listingType === "매매"
      ? draft.salePrice
      : patch.listingType === "전세"
        ? draft.leaseDeposit
        : draft.rentCondition;
    stagePatch({ ...patch, price: typedPrice || draft.price || "" });
  };
  const stagePrimaryPrice = (value) => stagePatch({
    price: value,
    ...(draft.listingType === "매매" ? { salePrice: value } : {}),
    ...(draft.listingType === "전세" ? { leaseDeposit: value } : {}),
    ...(draft.listingType === "월세" ? { rentCondition: value } : {}),
  });
  const stageTypedPrice = (field, value, listingType) => stagePatch({ [field]: value, ...(draft.listingType === listingType ? { price: value } : {}) });
  const people = useMemo(() => peopleForDraft(draft), [draft]);
  /*
   * 임대인 전화.
   *
   * 인물 카드 첫 임대인의 연락처와 같은 값이라, 한쪽만 고치면 한 화면에 번호가 둘 보인다.
   * 인물 목록을 이미 손댄 뒤라면 첫 임대인의 번호까지 함께 맞춘다.
   * (목록을 손대기 전에는 peopleForDraft가 이 값을 그대로 읽어 가므로 둘 곳이 없다.)
   */
  const stageOwnerPhone = (value) => {
    if (!Array.isArray(draft.people) || !draft.people.length) { stageField("phone", value); return; }
    let applied = false;
    const nextPeople = draft.people.map((person) => { if (applied || person.role !== "임대인") return person; applied = true; return { ...person, phone: value }; });
    stagePatch({ phone: value, people: nextPeople });
  };
  const isDirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(baselineRef.current), [draft]);
  const completion = useMemo(() => ({ complex: Boolean(draft.complex?.trim()), building: Boolean(draft.building?.trim()), unit: Boolean(draft.unit?.trim()), duplicate: Boolean(draft.duplicateCheck) }), [draft.building, draft.complex, draft.duplicateCheck, draft.unit]);
  const canComplete = Object.values(completion).every(Boolean);
  const changedFieldCount = Object.keys(draft).filter((key) => JSON.stringify(draft[key]) !== JSON.stringify(baselineRef.current[key])).length;
  const unmet = [["complex", "단지"], ["building", "동"], ["unit", "호"], ["duplicate", "중복 검사"]].filter(([key]) => !completion[key]).map(([, label]) => label);

  // 저장에는 이름이 아니라 서버 id가 필요하다. 선택지에 id가 있으면 함께 싣는다.
  const complexIdOf = (name) => complexOptions.find((option) => typeof option !== "string" && option.name === name)?.id ?? null;
  const selectComplex = (value) => { if (value === "__new_complex__") { setComplexQuickAddOpen(true); return; } stagePatch({ complex: value, complexId: complexIdOf(value), duplicateCheck: value === draft.complex ? draft.duplicateCheck : false }); };
  const createComplex = async () => { const name = newComplexName.trim(); const address = newComplexAddress.trim(); if (!name) { setComplexQuickAddError("단지명을 입력해 주세요."); return; } const duplicate = complexOptions.find((option) => (typeof option === "string" ? option : option.name)?.toLocaleLowerCase("ko-KR") === name.toLocaleLowerCase("ko-KR")); if (duplicate) { setComplexQuickAddError(`이미 등록된 단지입니다: ${typeof duplicate === "string" ? duplicate : duplicate.name}`); return; } try { const created = await onCreateComplex?.({ name, address }); const selectedName = created?.name || name; stagePatch({ complex: selectedName, complexId: created?.id ?? null, duplicateCheck: false }); setComplexQuickAddOpen(false); setNewComplexName(""); setNewComplexAddress(""); setComplexQuickAddError(""); setComplexQuickAddStatus(`${selectedName} 단지를 추가하고 선택했습니다.`); } catch (error) { setComplexQuickAddError(error?.message || "단지를 추가하지 못했습니다."); } };

  const saveDraft = async ({ closeAfter = false, allowSensitive = false } = {}) => { const hasSensitivePattern = PROTOTYPE_ASSUMPTIONS.security.sensitivePattern.test(`${draft.memo || ""} ${draft.log || ""}`); if (hasSensitivePattern && !allowSensitive && !securityConfirmed) { setSecurityWarning("주민등록번호·계좌번호로 보이는 패턴이 있습니다. 내용을 확인한 뒤 그대로 저장할 수 있습니다."); return; } setSecurityWarning(""); setIsSaving(true); setSaveError(""); const nextDraft = { ...draft, saveState: canComplete ? "저장 완료" : "임시저장" }; try { await onSave?.(nextDraft); window.dispatchEvent(new CustomEvent("prototype:f1-row-saved", { detail: nextDraft })); setDraft(nextDraft); baselineRef.current = nextDraft; setSecurityConfirmed(false); setCloseDecision(false); if (closeAfter) onClose?.(); } catch (error) { setSaveError(error?.message || "저장하지 못했습니다. 잠시 후 다시 시도해 주세요."); } finally { setIsSaving(false); } };
  const closeDeleteDecision = () => {
    if (isDeleting) return;
    setDeleteDecision(false);
    window.requestAnimationFrame(() => deleteTriggerRef.current?.focus());
  };
  /* Esc와 닫기 버튼이 삭제 확인 위로 지나가면 상세가 통째로 닫혀 확인이 사라진다. 확인 중에는 확인만 닫는다. */
  const requestClose = () => { if (isDeleting) return; if (deleteDecision) { closeDeleteDecision(); return; } if (isDirty) setCloseDecision(true); else onClose?.(); };
  const discardAndClose = async () => { try { await onDiscard?.(baselineRef.current); setCloseDecision(false); onClose?.(); } catch (error) { setSaveError(error?.message || "변경 내용을 되돌리지 못했습니다."); } };

  /*
   * 세대 삭제.
   *
   * 지금 보고 있는 세대를 지우는 작업이라 버튼 한 번으로 실행하지 않는다.
   * 어떤 세대인지, 무엇이 사라지고 무엇이 남는지, 화면에서 되돌릴 수 있는지를 먼저 보여준 뒤
   * 확인을 받아야 실행하고, 처리 중에는 버튼을 잠가 같은 요청이 두 번 나가지 않게 한다.
   */
  const isUnsavedDraftRow = String(draft.id || "").startsWith("DRAFT-");
  const deleteTargetLabel = `${draft.complex || "단지 미입력"} ${draft.building || "-"}동 ${draft.unit || "-"}호`;
  const requestDelete = () => { setDeleteError(""); setDeleteDecision(true); };
  const confirmDelete = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    setDeleteError("");
    try {
      await onDelete?.(draft);
      setDeleteDecision(false);
    } catch (error) {
      setDeleteError(error?.message || "삭제하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsDeleting(false);
    }
  };
  const updatePeople = (nextPerson) => { const nextPeople = people.map((person) => person.id === nextPerson.id ? nextPerson : person); const owners = nextPeople.filter((person) => person.role === "임대인"); const tenants = nextPeople.filter((person) => person.role === "임차인"); stagePatch({ people: nextPeople, owner: owners.map((person) => person.name).join("·"), tenant: tenants.map((person) => person.name).join("·"), phone: owners[0]?.phone || draft.phone, consent: owners[0]?.consent === "O" ? "동의" : "확인 필요", relationship: owners[0]?.relationship || draft.relationship }); };
  const f2Draft = draft.f2Draft || {};
  const handleF2Apply = (patch, nextF2Draft) => {
    const typedPatch = patch.price ? (draft.listingType === "매매" ? { salePrice: patch.price } : draft.listingType === "전세" ? { leaseDeposit: patch.price } : { rentCondition: patch.price }) : {};
    stagePatch({ ...patch, ...typedPatch, f2Draft: nextF2Draft });
    setF2Open(false);
  };
  const handleF2DraftChange = (nextF2Draft) => {
    const isUntouched = nextF2Draft?.state === "empty" && !nextF2Draft?.audioSource
      && !nextF2Draft?.privacyConfirmed && !nextF2Draft?.reviewComplete
      && (nextF2Draft?.proposals?.length || 0) === 0;
    if (isUntouched && !Object.keys(f2Draft).length) return;
    stageField("f2Draft", nextF2Draft);
  };

  return <Modal id="detail-workspace-modal" isOpen={isOpen} onClose={requestClose} disableFocusTrap={deleteDecision} className="detail-workspace-modal" aria-label="세대 상세·상담 로그">
    <ModalHeader><div className="detail-workspace__header"><div className="detail-workspace__title-group"><Title headingLevel="h1" id="detail-workspace-title" size="xl">세대 상세 · 상담 로그</Title><span>{draft.complex || "단지 미입력"} {draft.building || "-"}동 {draft.unit || "-"}호 · {draft.id || "신규"}</span></div><div className="detail-workspace__state-summary"><StateSummary label="저장 상태" value={draft.saveState} status={statusForStorage(draft.saveState)} /></div></div></ModalHeader>
    <ModalBody className="detail-workspace__modal-body"><div className="detail-workspace__layout" data-screen-id="F1-MOD-010 F1-MOD-130" data-requirement-ids="F1-UD-01~28, F1-LG-01~06, F1-LG-08~34, F1-TR-01~05, F2-POP-01, F1-GR-32, F1-GR-35~36, F1-ST-18, F2-POP-02">
      <main className="detail-workspace__content">
        {securityWarning && <Alert ref={securityRef} tabIndex={-1} className="detail-workspace__save-error" variant="warning" isInline isLiveRegion title="개인정보 패턴을 확인해 주세요" data-screen-id="F1-MOD-140" data-requirement-ids="F1-SE-03~05, F1-DM-16, F1-ST-13"><p>{securityWarning}</p><Checkbox id="security-confirm" label="내용을 확인했으며 원문을 그대로 저장합니다." isChecked={securityConfirmed} onChange={(_event, checked) => setSecurityConfirmed(checked)} /><div className="f2-actions"><Button variant="primary" isDisabled={!securityConfirmed || isSaving} onClick={() => saveDraft({ allowSensitive: true })}>그대로 저장</Button><Button variant="link" onClick={() => { setSecurityWarning(""); setSecurityConfirmed(false); }}>돌아가기</Button></div></Alert>}
        {saveError && <Alert className="detail-workspace__save-error" variant="danger" isInline isLiveRegion title="저장하지 못했습니다">{saveError}</Alert>}
        <section className="detail-section" aria-labelledby="detail-overview-heading">
          <div className="detail-section__heading"><Title headingLevel="h2" id="detail-overview-heading" size="md">세대 정보</Title></div>
          <div className="detail-info-grid">
            <div className="detail-info-column detail-info-column--identity"><h3>세대 식별</h3><div className="detail-field detail-complex-field"><span className="detail-field__label" id="detail-complex-label">단지</span><ComplexPicker
              labelId="detail-complex-label"
              value={draft.complex}
              options={complexOptions}
              onSelect={selectComplex}
              onDelete={onDeleteComplex}
            />{String(draft.id).startsWith("DRAFT-") && <Button variant="link" isInline onClick={() => setComplexQuickAddOpen(true)}>새 단지 추가</Button>}{complexQuickAddOpen && <div className="detail-complex-quick-add"><strong>새 단지 빠른 추가</strong><label htmlFor="detail-new-complex-name">단지명</label><TextInput id="detail-new-complex-name" value={newComplexName} validated={complexQuickAddError ? "error" : "default"} onChange={(_event, value) => setNewComplexName(value)} /><label htmlFor="detail-new-complex-address">주소</label><TextInput id="detail-new-complex-address" value={newComplexAddress} onChange={(_event, value) => setNewComplexAddress(value)} />{complexQuickAddError && <span role="alert">{complexQuickAddError}</span>}<div className="f2-actions"><Button size="sm" onClick={createComplex}>추가 후 선택</Button><Button size="sm" variant="link" onClick={() => setComplexQuickAddOpen(false)}>취소</Button></div></div>}{complexQuickAddStatus && <span className="detail-complex-quick-add__status" role="status">{complexQuickAddStatus}</span>}</div><div className="detail-inline-fields"><DetailField id="detail-building" label="동" value={draft.building} onChange={(value) => stageField("building", value)} /><DetailField id="detail-unit" label="호" value={draft.unit} onChange={(value) => stageField("unit", value)} /></div><div className="detail-inline-fields"><DetailField id="detail-area" label="평형" value={draft.area} onChange={(value) => stageField("area", value)} /><DetailField id="detail-direction" label="향" value={draft.direction} onChange={(value) => stageField("direction", value)} /></div><DetailField id="detail-type" label="타입" value={draft.type} onChange={(value) => stageField("type", value)} /></div>

            <div className="detail-info-column"><h3>현재 임대차</h3><div className="detail-inline-fields"><DetailField id="detail-deposit" label="보증금(현)" value={draft.deposit} onChange={(value) => stageField("deposit", value)} /><DetailField id="detail-rent" label="차임(현)" value={draft.rent} onChange={(value) => stageField("rent", value)} /></div><DetailField id="detail-loan" label="융자" value={draft.loan} onChange={(value) => stageField("loan", value)} /><DetailField id="detail-expiry" label="계약 만기일" type="date" value={draft.expiry} onChange={(value) => stageField("expiry", value)} /><DetailTextOrDateField id="detail-clearance" label="명도" value={draft.clearance} onChange={(value) => stageField("clearance", value)} /></div>

            <div className="detail-info-column"><h3>업무 관리</h3><DetailSelect id="detail-household-state" label="업무 상태" value={draft.householdState} options={["일반", "매물화", "거래진행"]} onChange={(value) => stageField("householdState", value)} /><DetailField id="detail-assignee" label="담당자" span={2} value={draft.assignee} onChange={(value) => stageField("assignee", value)} /><DetailField id="detail-last-contact" label="최근 상담일" type="date" value={draft.lastContact} onChange={(value) => stageField("lastContact", value)} /><div className="detail-inline-fields"><DetailField id="detail-parking" label="주차" value={draft.parking} onChange={(value) => stageField("parking", value)} /><DetailField id="detail-tax" label="세금 메모" value={draft.tax} onChange={(value) => stageField("tax", value)} /></div></div>
          </div>
        </section>

        <section id="detail-section-ledger-fields" className="detail-section" aria-labelledby="detail-ledger-fields-heading">
          <div className="detail-section__heading"><Title headingLevel="h2" id="detail-ledger-fields-heading" size="md">매물 조건과 시설</Title></div>
          <div className="detail-info-grid">
            <div className="detail-info-column"><h3>거래 조건</h3><DetailSelect id="detail-listing-type" label="거래 유형" value={dealTypeValue(draft)} options={DEAL_TYPE_CHOICES} onChange={stageListingType} /><DetailField id="detail-received-at" label="접수일" type="date" value={draft.receivedAt} onChange={(value) => stageField("receivedAt", value)} /><DetailField id="detail-move-in" label="입주 가능일" type="date" value={draft.moveIn} onChange={(value) => stageField("moveIn", value)} /></div>

            <div className="detail-info-column"><h3>거래 금액</h3><DetailField id="detail-sale-price" label="매매가" value={draft.salePrice} onChange={(value) => stageTypedPrice("salePrice", value, "매매")} /><DetailField id="detail-lease-deposit" label="전세보증금" value={draft.leaseDeposit} onChange={(value) => stageTypedPrice("leaseDeposit", value, "전세")} /><DetailField id="detail-rent-condition" label="보증금 / 차임" value={draft.rentCondition} onChange={(value) => stageTypedPrice("rentCondition", value, "월세")} /></div>

            {/* 가장 길게 쓰는 상담 로그가 오른쪽 열을 세로로 다 쓰고, 시설과 비고는 그 아래 남는 두 칸을 가로로 채운다. */}
            <div className="detail-info-column detail-info-column--log" id="detail-section-log">
              <div className="detail-log-pane detail-log-pane--log"><h3><label htmlFor="detail-log">상담 로그</label><span>음성메모 제안 반영</span></h3><TextArea id="detail-log" aria-label="상담 로그" value={draft.log} placeholder="상담 내용, 다음 연락 일정, 요청사항을 기록하세요." resizeOrientation="vertical" onChange={(_event, value) => stageField("log", value)} /><div className="detail-log-meta"><span>유입 경로: {draft.source || "미입력"}</span><span>담당자: {draft.assignee || "미지정"}</span></div></div>
              <div className="detail-log-pane detail-log-pane--memo"><h3><label htmlFor="detail-memo">비고</label></h3><TextArea id="detail-memo" aria-label="세대 비고" value={draft.memo} placeholder="참고사항을 입력하세요." resizeOrientation="vertical" onChange={(_event, value) => stageField("memo", value)} /></div>
            </div>

            <div className="detail-info-column detail-info-column--facility"><h3>시설·연락 보조</h3><div className="detail-inline-fields"><DetailTextAreaField id="detail-spec" className="detail-field--spec" label="스펙" value={draft.spec} onChange={(value) => stageField("spec", value)} /><DetailField id="detail-built-in" label="붙박이" value={draft.builtIn} onChange={(value) => stageField("builtIn", value)} /><DetailField id="detail-facility-state" label="시설 상태" value={draft.facilityState} onChange={(value) => stageField("facilityState", value)} /><DetailField id="detail-brokerage" label="임대부동산" value={draft.brokerage} onChange={(value) => stageField("brokerage", value)} /><DetailPhoneField id="detail-owner-phone" label="임대인 전화" value={draft.phone} onChange={stageOwnerPhone} /><DetailPhoneField id="detail-tenant-phone" label="임차인 전화" value={draft.tenantPhone} onChange={(value) => stageField("tenantPhone", value)} /></div><div className="detail-people-card" aria-labelledby="detail-people-heading"><h4 id="detail-people-heading">연락 동의 인물<span>O/X, 값 없음은 X</span></h4><div className="detail-people-list">{people.map((person) => <div className="detail-person-row" key={person.id}><div><strong>{person.name || "성명 미입력"}</strong><span>{person.role} · {person.relationship || "관계 미입력"} · 등록 {person.position || 1}번</span></div><span className={`detail-consent-badge detail-consent-badge--${person.consent === "O" ? "yes" : "no"}`} aria-label={`연락 동의 ${person.consent === "O" ? "O" : "X"}`}>{person.consent === "O" ? "O" : "X"}</span><span>{person.phone || "연락처 없음"}{person.tag ? ` · ${person.tag}` : ""}</span><Button variant="link" aria-label={`${person.name || "인물"} 관계 수정`} onClick={() => { setRelationTarget(person); setRelationOpen(true); }}>수정</Button></div>)}{!people.length && <p className="detail-empty-state">등록된 인물이 없습니다.</p>}</div></div></div>
          </div>
        </section>
        {crossMatchPanel}
      </main>
      <aside className="detail-workspace__action-rail" aria-label="F1 상세 작업"><div className={`action-rail__dirty ${isDirty ? "is-dirty" : ""}`} aria-live="polite"><span>{isDirty ? "저장하지 않은 변경 있음" : "모든 변경 저장됨"}</span></div><div className="action-rail__primary"><span className="action-rail__eyebrow">주요 작업</span><div className={`detail-duplicate-check ${draft.duplicateCheck ? "is-complete" : ""}`}><Checkbox id="detail-duplicate-check" label="중복 검사 완료" isChecked={draft.duplicateCheck} onChange={(_event, checked) => stageField("duplicateCheck", checked)} /></div><Button variant="primary" icon={<SaveIcon />} onClick={() => saveDraft()} isLoading={isSaving} isDisabled={isSaving}>저장</Button><Button variant="secondary" icon={<TimesIcon />} onClick={requestClose}>상세 닫기</Button><Button variant="secondary" icon={<SearchIcon />} onClick={() => onOpenCrossMatch?.(draft)} aria-expanded={isCrossMatchOpen} aria-controls="cross-match-panel">교차 매칭</Button><Button ref={deleteTriggerRef} variant="secondary" isDanger icon={<TrashIcon />} onClick={requestDelete} isDisabled={isSaving || isDeleting} aria-haspopup="dialog">삭제</Button></div><Divider /><div className="action-rail__status"><div className="action-rail__status-heading"><strong>저장 완료 조건</strong><Label status={canComplete ? "success" : "warning"} isCompact>{Object.values(completion).filter(Boolean).length}/4</Label></div><ul>{[["complex", "단지"], ["building", "동"], ["unit", "호"], ["duplicate", "중복 검사"]].map(([key, label]) => <li className={completion[key] ? "is-complete" : ""} key={key}>{completion[key] ? <CheckCircleIcon aria-hidden="true" /> : <InfoCircleIcon aria-hidden="true" />}{label}</li>)}</ul>{!canComplete &&<p>조건 미충족 상태에서도 임시저장할 수 있습니다.</p>}</div></aside>
    </div>
    {closeDecision && <div className="detail-workspace__decision-layer" role="presentation"><section className="detail-workspace__decision-card" role="alertdialog" aria-modal="true" aria-labelledby="close-decision-title"><div className="decision-card__icon"><SaveIcon aria-hidden="true" /></div><Title headingLevel="h2" id="close-decision-title" size="lg">변경사항을 저장할까요?</Title><p>임시저장은 언제든 가능하며, 저장 완료는 단지·동·호·중복 검사 조건을 충족해야 합니다.</p><dl className="decision-card__summary"><div><dt>변경 항목</dt><dd>{changedFieldCount}개</dd></div><div><dt>저장 후 상태</dt><dd>{canComplete ? "저장 완료" : "임시저장"}</dd></div><div><dt>미충족 조건</dt><dd>{unmet.join(", ") || "없음"}</dd></div></dl>{saveError && <Alert className="decision-card__error" variant="danger" isInline title="저장하지 못했습니다">{saveError}</Alert>}<div className="decision-card__actions"><Button variant="primary" onClick={() => saveDraft({ closeAfter: true })} isLoading={isSaving}>저장</Button><Button variant="danger" onClick={discardAndClose} isDisabled={isSaving}>저장 안 함</Button><Button variant="secondary" onClick={() => setCloseDecision(false)} isDisabled={isSaving}>취소</Button></div></section></div>}
    </ModalBody>
    <VoiceMemoModal isOpen={f2Open} draft={draft} initialDraft={f2Draft} onClose={() => setF2Open(false)} onApply={handleF2Apply} onDraftChange={handleF2DraftChange} />
    <RelationEditModal isOpen={relationOpen} person={relationTarget} onClose={() => setRelationOpen(false)} onApply={updatePeople} />
    <Modal
      appendTo={() => document.getElementById("detail-workspace-modal")}
      variant="small"
      isOpen={deleteDecision}
      onClose={closeDeleteDecision}
      onEscapePress={(event) => { event.stopPropagation(); closeDeleteDecision(); }}
      elementToFocus="#detail-delete-cancel"
      aria-labelledby="delete-decision-title"
      aria-describedby="delete-decision-effect"
      className="detail-workspace__delete-modal"
    >
      <ModalHeader title="이 세대를 삭제할까요?" titleIconVariant="danger" labelId="delete-decision-title" />
      <ModalBody className="detail-workspace__delete-modal-body">
        <p id="delete-decision-effect">{isUnsavedDraftRow
          ? "아직 저장하지 않은 행이라 서버에 남는 기록 없이 화면에서만 없어집니다. 입력한 내용은 복구할 수 없습니다."
          : "장부 목록과 검색에서 즉시 사라집니다. 데이터는 서버에 남아 상담 로그와 매물 이력은 보존되지만, 화면에서 되살리는 기능은 없어 관리자에게 요청해야 합니다."}</p>
        <dl className="decision-card__summary"><div><dt>삭제 대상</dt><dd>{deleteTargetLabel}</dd></div><div><dt>세대 번호</dt><dd>{isUnsavedDraftRow ? "저장 전" : (draft.id || "미지정")}</dd></div><div><dt>되돌리기</dt><dd>{isUnsavedDraftRow ? "불가" : "관리자 요청 필요"}</dd></div></dl>
        {isDirty && <p className="decision-card__unsaved" role="status">저장하지 않은 변경 {changedFieldCount}개도 함께 사라집니다.</p>}
        {deleteError && <Alert className="decision-card__error" variant="danger" isInline isLiveRegion title="삭제하지 못했습니다">{deleteError}</Alert>}
      </ModalBody>
      <ModalFooter>
        <Button variant="danger" icon={<TrashIcon />} onClick={confirmDelete} isLoading={isDeleting} isDisabled={isDeleting}>삭제</Button>
        <Button id="detail-delete-cancel" variant="secondary" onClick={closeDeleteDecision} isDisabled={isDeleting}>취소</Button>
      </ModalFooter>
    </Modal>
  </Modal>;
}
