import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormSelect,
  FormSelectOption,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  TextArea,
  TextInput,
} from "@patternfly/react-core";
import { SaveIcon, SearchIcon, TimesIcon, TrashIcon } from "@patternfly/react-icons";
import VoiceMemoModal from "./VoiceMemoModal.jsx";
import { describeForUser } from "./ledger/index.ts";
import { nextPhoneInput } from "./ledger/model/phone.ts";
import "./DetailWorkspace.css";

const EMPTY_BUYER = {
  id: "",
  date: "",
  area: "",
  category: "매수",
  budget: "",
  complex: "",
  buyer: "",
  phone: "",
  brokerage: "",
  moveDate: "",
  content: "",
  stage: "",
  completion: "진행",
  assignee: "김이순",
  background: "",
  expiry: "",
  classification: "",
  memo: "",
  consent: "미확인",
  saveState: "임시저장",
  ledgerType: "buyer",
  rowKind: "buyer",
};

/** 거래 구분 선택지. 선택기와 저장 전 검증이 같은 목록을 본다. */
const DEMAND_TYPES = ["매수", "매도", "전세", "월세"];

function Field({ id, label, value, onChange, type = "text", inputMode, autoComplete, placeholder }) {
  return <label className="detail-field" htmlFor={id}><span className="detail-field__label">{label}</span><TextInput id={id} type={type} inputMode={inputMode} autoComplete={autoComplete} placeholder={placeholder} value={value || ""} onChange={(_event, next) => onChange(next)} /></label>;
}

function SelectField({ id, label, value, options, onChange }) {
  return <label className="detail-field" htmlFor={id}><span className="detail-field__label">{label}</span><FormSelect id={id} value={value} onChange={(_event, next) => onChange(next)}>{options.map((option) => <FormSelectOption key={option} value={option} label={option} />)}</FormSelect></label>;
}

export default function BuyerDetailWorkspace({ row, isOpen, onClose, onSave, onDiscard, onDelete, onOpenCrossMatch, isCrossMatchOpen = false, crossMatchPanel, focusF2Request = 0 }) {
  const [draft, setDraft] = useState(() => ({ ...EMPTY_BUYER, ...(row || {}) }));
  const [f2Open, setF2Open] = useState(false);
  const [closeDecision, setCloseDecision] = useState(false);
  const [deleteDecision, setDeleteDecision] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  /* 저장을 막은 사유. 제목과 항목으로 나눠 어느 칸을 고쳐야 하는지 그대로 읽히게 한다. */
  const [error, setError] = useState(null);
  const baselineRef = useRef(draft);
  const deleteTriggerRef = useRef(null);
  const errorRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    const next = { ...EMPTY_BUYER, ...(row || {}), saveState: row?.saveState === "저장 완료" ? "저장 완료" : "임시저장", ledgerType: "buyer", rowKind: "buyer" };
    setDraft(next);
    baselineRef.current = next;
    setF2Open(Boolean(focusF2Request));
    setCloseDecision(false);
    setDeleteDecision(false);
    setIsDeleting(false);
    setDeleteError("");
    setIsSaving(false);
    setError(null);
  }, [focusF2Request, isOpen, row]);

  useEffect(() => {
    if (error == null) return;
    errorRef.current?.scrollIntoView({ block: "nearest" });
    errorRef.current?.focus();
  }, [error]);

  /* 상세는 항상 맨 위에서 시작한다. 안쪽 패널이 스크롤을 가져가는 일이 있어 열릴 때 되돌린다. */
  useEffect(() => {
    if (!isOpen) return undefined;
    const frame = window.requestAnimationFrame(() => {
      document.querySelectorAll(".detail-workspace-modal .pf-v6-c-modal-box__body").forEach((node) => {
        node.scrollTop = 0;
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen, row?.id]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(baselineRef.current), [draft]);
  const changedFieldCount = Object.keys(draft).filter((key) => JSON.stringify(draft[key]) !== JSON.stringify(baselineRef.current[key])).length;
  const completionReady = Boolean(draft.buyer?.trim() && draft.category && (draft.complex?.trim() || draft.area?.trim()) && draft.budget?.trim());
  const consented = draft.consent === "동의";
  const update = (field, value) => setDraft((current) => ({ ...current, [field]: value }));

  /*
   * 저장을 막는 사유.
   *
   * "입력값을 확인해 주세요"만으로는 어느 칸을 봐야 하는지 알 수 없다.
   * 칸 이름과 무엇을 넣어야 하는지를 같이 적는다. 여기 있는 항목은 모두 요청 자체를
   * 만들 수 없게 하는 조건이며, 값이 모자라 임시저장으로 남는 것과는 다르다.
   */
  const saveBlockers = useMemo(() => {
    const blockers = [];
    if (draft.consent !== "동의") {
      blockers.push("개인정보 활용 동의: 아래 [개인정보 활용 동의를 확인했습니다]를 체크해 주세요. 동의 없이는 손님 레코드를 저장할 수 없습니다.");
    }
    if (!DEMAND_TYPES.includes(draft.category)) {
      blockers.push(`거래 구분: ${DEMAND_TYPES.join(" · ")} 중 하나를 골라 주세요.`);
    }
    /* 계약상 구입장은 인물이 있어야 만들 수 있는데 인물 등록 API가 아직 없다. 저장 전에 알린다. */
    if (draft.serverId == null && draft.partyId == null) {
      blockers.push("손님 인물 연결: 새 손님은 아직 서버에 등록할 수 없습니다. 인물 등록 기능이 준비될 때까지 이 행은 화면에만 남습니다.");
    }
    return blockers;
  }, [draft.category, draft.consent, draft.partyId, draft.serverId]);

  /* 저장은 되지만 [저장 완료]로 남지 않는 칸. 무엇을 더 채우면 되는지 함께 알려준다. */
  const completionGaps = useMemo(() => [
    ["이름·별칭", Boolean(draft.buyer?.trim())],
    ["거래 구분", Boolean(draft.category)],
    ["희망 단지·지역 또는 희망 평형", Boolean(draft.complex?.trim() || draft.area?.trim())],
    ["금액 조건", Boolean(draft.budget?.trim())],
  ].filter(([, filled]) => !filled).map(([label]) => label), [draft.area, draft.budget, draft.buyer, draft.category, draft.complex]);

  const save = async ({ closeAfter = false } = {}) => {
    if (isSaving) return;
    // 보낼 수 없는 요청은 만들지 않는다. 서버까지 갔다 와야 사유를 아는 것보다 지금 알려주는 편이 낫다.
    if (saveBlockers.length > 0) {
      // 닫기 확인에서 누른 저장이면 확인을 걷어낸다. 그 위에 사유를 띄우면 가려서 보이지 않는다.
      setCloseDecision(false);
      setError({ title: "저장할 수 없습니다", items: saveBlockers });
      return;
    }
    const next = { ...draft, saveState: completionReady ? "저장 완료" : "임시저장", ledgerType: "buyer", rowKind: "buyer" };
    setIsSaving(true);
    try {
      const persisted = await onSave?.(next);
      // 서버가 올린 row_version을 받아 둔다. 없으면 이 상세에서 두 번째 저장이 409가 된다.
      const saved = carrySavedIdentity(next, persisted);
      setDraft(saved);
      baselineRef.current = saved;
      setError(null);
      setCloseDecision(false);
      if (closeAfter) onClose?.();
    } catch (failure) {
      // 상세가 열린 채로 사유를 남긴다. 토스트만 띄우면 스크롤을 내린 사용자는 놓친다.
      setCloseDecision(false);
      setError({ title: "저장하지 못했습니다", items: [describeForUser(failure)] });
    } finally {
      setIsSaving(false);
    }
  };

  const closeDeleteDecision = () => {
    if (isDeleting) return;
    setDeleteDecision(false);
    window.requestAnimationFrame(() => deleteTriggerRef.current?.focus());
  };
  const requestClose = () => { if (isDeleting) return; if (deleteDecision) { closeDeleteDecision(); return; } if (dirty) setCloseDecision(true); else onClose?.(); };
  const discard = async () => { await onDiscard?.(baselineRef.current); setCloseDecision(false); onClose?.(); };
  const isUnsavedDraftRow = draft.serverId == null;
  const deleteTargetLabel = `${draft.buyer || "별칭 미입력"} · ${draft.category || "구분 미입력"}`;
  const requestDelete = () => { setDeleteError(""); setDeleteDecision(true); };
  const confirmDelete = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    setDeleteError("");
    try {
      await onDelete?.(draft);
      setDeleteDecision(false);
    } catch (deleteFailure) {
      setDeleteError(deleteFailure?.message || "삭제하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsDeleting(false);
    }
  };
  const handleF2Apply = (patch, f2Draft) => { setDraft((current) => ({ ...current, ...patch, f2Draft })); setF2Open(false); };
  const handleF2DraftChange = (nextF2Draft) => {
    const isUntouched = nextF2Draft?.state === "empty" && !nextF2Draft?.audioSource
      && !nextF2Draft?.privacyConfirmed && !nextF2Draft?.reviewComplete
      && (nextF2Draft?.proposals?.length || 0) === 0;
    if (isUntouched && !Object.keys(draft.f2Draft || {}).length) return;
    update("f2Draft", nextF2Draft);
  };

  return <Modal id="buyer-detail-workspace-modal" isOpen={isOpen} onClose={requestClose} disableFocusTrap={deleteDecision} variant="large" className="detail-workspace-modal" aria-label="손님 상세·상담 로그">
    <ModalHeader title="손님 상세 · 상담 로그" description={`${draft.buyer || "별칭 미입력"} · ${draft.category || "구분 미입력"} · ${draft.saveState}`} />
    <ModalBody className="detail-workspace__modal-body">
      <div className="buyer-detail-workspace" data-screen-id="F1-MOD-020 F1-MOD-130" data-requirement-ids="F1-DM-08~16, F1-LG-01~06, F1-LG-08~19, F1-LG-33~34, F1-TR-06, F2-POP-01~03">
        {error && <div ref={errorRef} tabIndex={-1} className="buyer-detail-workspace__error">
          <Alert variant="danger" isInline isLiveRegion title={error.title} data-screen-id="F1-MOD-140" data-requirement-ids="F1-SE-04, F1-DM-16">
            <ul>{error.items.map((item) => <li key={item}>{item}</li>)}</ul>
            {completionGaps.length > 0 && <p>{`저장하더라도 다음 칸이 비어 있으면 임시저장으로 남습니다 · ${completionGaps.join(", ")}`}</p>}
          </Alert>
        </div>}
        <div className="detail-info-grid">
          <section className="detail-info-column"><h3>손님과 접수</h3><Field id="buyer-name" label="이름·별칭" value={draft.buyer} onChange={(value) => update("buyer", value)} /><Field id="buyer-phone" label="전화번호" type="tel" inputMode="tel" autoComplete="tel" placeholder="010-0000-0000" value={draft.phone} onChange={(value) => update("phone", nextPhoneInput(draft.phone, value))} /><Field id="buyer-date" label="접수일" type="date" value={draft.date} onChange={(value) => update("date", value)} /><Field id="buyer-assignee" label="담당자" value={draft.assignee} onChange={(value) => update("assignee", value)} /></section>
          <section className="detail-info-column"><h3>희망 조건</h3><SelectField id="buyer-category" label="거래 구분" value={draft.category} options={DEMAND_TYPES} onChange={(value) => update("category", value)} /><Field id="buyer-complex" label="희망 단지·지역" value={draft.complex} onChange={(value) => update("complex", value)} /><Field id="buyer-area" label="희망 평형" value={draft.area} onChange={(value) => update("area", value)} /><Field id="buyer-budget" label="금액 조건" value={draft.budget} onChange={(value) => update("budget", value)} /><Field id="buyer-move-date" label="이사일" type="date" value={draft.moveDate} onChange={(value) => update("moveDate", value)} /></section>
          <section className="detail-info-column"><h3>진행 관리</h3><Field id="buyer-stage" label="진행 단계" value={draft.stage} onChange={(value) => update("stage", value)} /><SelectField id="buyer-completion" label="완료 여부" value={draft.completion} options={["진행", "완료"]} onChange={(value) => update("completion", value)} /><Field id="buyer-expiry" label="만기일" type="date" value={draft.expiry} onChange={(value) => update("expiry", value)} /><Field id="buyer-classification" label="분류" value={draft.classification} onChange={(value) => update("classification", value)} /><Field id="buyer-brokerage" label="관련 부동산" value={draft.brokerage} onChange={(value) => update("brokerage", value)} /></section>
        </div>
        <label className="detail-field" htmlFor="buyer-content"><span className="detail-field__label">상담 로그</span><TextArea id="buyer-content" value={draft.content} onChange={(_event, value) => update("content", value)} /></label>
        <label className="detail-field" htmlFor="buyer-memo"><span className="detail-field__label">비고</span><TextArea id="buyer-memo" value={draft.memo} onChange={(_event, value) => update("memo", value)} /></label>
        <Checkbox id="buyer-consent" label="개인정보 활용 동의를 확인했습니다" isChecked={consented} onChange={(_event, checked) => update("consent", checked ? "동의" : "미확인")} />
        {crossMatchPanel}
      </div>
      {closeDecision && <div className="detail-workspace__decision-layer"><section className="detail-workspace__decision-card" role="alertdialog" aria-modal="true" aria-labelledby="buyer-close-title"><h2 id="buyer-close-title">변경사항을 저장할까요?</h2><p>동의와 최소 조건을 충족하지 않으면 임시저장 상태로 남습니다.</p><div className="decision-card__actions"><Button variant="primary" onClick={() => save({ closeAfter: true })}>저장</Button><Button variant="danger" onClick={discard}>저장 안 함</Button><Button variant="secondary" onClick={() => setCloseDecision(false)}>취소</Button></div></section></div>}
    </ModalBody>
    <ModalFooter className="buyer-detail-workspace__footer">
      <div className="detail-workspace__action-row">
        <Button variant="primary" icon={<SaveIcon />} onClick={() => save()} isLoading={isSaving} isDisabled={isSaving}>저장</Button>
        <Button variant="secondary" icon={<TimesIcon />} onClick={requestClose}>상세 닫기</Button>
        <Button variant="secondary" icon={<SearchIcon />} onClick={() => onOpenCrossMatch?.(draft)} {...(isCrossMatchOpen ? { "aria-controls": "cross-match-panel" } : {})}>교차 판정</Button>
        <Button ref={deleteTriggerRef} variant="secondary" isDanger icon={<TrashIcon />} onClick={requestDelete} isDisabled={isSaving || isDeleting} aria-haspopup="dialog">삭제</Button>
      </div>
      <span className="buyer-detail-workspace__save-state" aria-live="polite">{dirty ? "저장하지 않은 변경 있음" : "모든 변경 저장됨"}</span>
    </ModalFooter>
    <VoiceMemoModal isOpen={f2Open} ledgerType="buyer" draft={draft} initialDraft={draft.f2Draft} onClose={() => setF2Open(false)} onApply={handleF2Apply} onDraftChange={handleF2DraftChange} />
    <Modal
      appendTo={() => document.getElementById("buyer-detail-workspace-modal")}
      variant="small"
      isOpen={deleteDecision}
      onClose={closeDeleteDecision}
      onEscapePress={(event) => { event.stopPropagation(); closeDeleteDecision(); }}
      elementToFocus="#buyer-detail-delete-cancel"
      aria-labelledby="buyer-delete-decision-title"
      aria-describedby="buyer-delete-decision-effect"
      className="detail-workspace__delete-modal"
    >
      <ModalHeader title="이 구입장 기록을 삭제할까요?" titleIconVariant="danger" labelId="buyer-delete-decision-title" />
      <ModalBody className="detail-workspace__delete-modal-body">
        <p id="buyer-delete-decision-effect">{isUnsavedDraftRow
          ? "아직 저장하지 않은 행이라 서버에 남는 기록 없이 화면에서만 없어집니다. 입력한 내용은 복구할 수 없습니다."
          : "구입장 목록과 검색에서 즉시 사라집니다. 데이터와 상담 로그는 서버에 남지만, 화면에서 되살리는 기능은 없어 관리자에게 요청해야 합니다."}</p>
        <dl className="decision-card__summary"><div><dt>삭제 대상</dt><dd>{deleteTargetLabel}</dd></div><div><dt>구입장 번호</dt><dd>{isUnsavedDraftRow ? "저장 전" : (draft.id || "미지정")}</dd></div><div><dt>되돌리기</dt><dd>{isUnsavedDraftRow ? "불가" : "관리자 요청 필요"}</dd></div></dl>
        {dirty && <p className="decision-card__unsaved" role="status">저장하지 않은 변경 {changedFieldCount}개도 함께 사라집니다.</p>}
        {deleteError && <Alert className="decision-card__error" variant="danger" isInline isLiveRegion title="삭제하지 못했습니다">{deleteError}</Alert>}
      </ModalBody>
      <ModalFooter>
        <Button variant="danger" icon={<TrashIcon />} onClick={confirmDelete} isLoading={isDeleting} isDisabled={isDeleting}>삭제</Button>
        <Button id="buyer-detail-delete-cancel" variant="secondary" onClick={closeDeleteDecision} isDisabled={isDeleting}>취소</Button>
      </ModalFooter>
    </Modal>
  </Modal>;
}
