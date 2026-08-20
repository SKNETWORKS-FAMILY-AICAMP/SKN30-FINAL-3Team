import { useEffect, useState } from "react";
import { Button, FormSelect, FormSelectOption, Modal, ModalBody, ModalFooter, ModalHeader, TextInput } from "@patternfly/react-core";
import { nextPhoneInput } from "./ledger/model/phone.ts";

export default function RelationEditModal({ isOpen, person, onClose, onApply }) {
  const [draft, setDraft] = useState(person || {});

  useEffect(() => { if (isOpen) setDraft(person || {}); }, [isOpen, person]);

  const update = (field, value) => setDraft((current) => ({ ...current, [field]: value }));

  return (
    <Modal isOpen={isOpen} onClose={onClose} variant="medium" aria-label="관계 수정" className="relation-edit-modal">
      <ModalHeader title="관계 수정" description="부모 세대 상세의 미저장 입력값으로 반영합니다." />
      <ModalBody>
        <div className="relation-edit-modal__content" data-screen-id="F1-MOD-125" data-requirement-ids="F1-UD-10, F1-UD-12~13, F1-UD-27, F1-LG-33">
          <div className="relation-edit-modal__field"><label htmlFor="relation-role">역할</label><FormSelect id="relation-role" value={draft.role || "임대인"} onChange={(_event, value) => update("role", value)}><FormSelectOption value="임대인" label="임대인" /><FormSelectOption value="임차인" label="임차인" /></FormSelect></div>
          <div className="relation-edit-modal__field"><label htmlFor="relation-value">관계</label><FormSelect id="relation-value" value={draft.relationship || "본인"} onChange={(_event, value) => update("relationship", value)}>{["본인", "배우자", "가족", "대리인", "중개", "기타"].map((value) => <FormSelectOption key={value} value={value} label={value} />)}</FormSelect></div>
          <div className="relation-edit-modal__field"><label htmlFor="relation-position">등록 순번</label><TextInput id="relation-position" type="number" min="1" value={draft.position || 1} onChange={(_event, value) => update("position", value)} /></div>
          <div className="relation-edit-modal__field"><label htmlFor="relation-phone">연락처</label><TextInput id="relation-phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="010-0000-0000" value={draft.phone || ""} onChange={(_event, value) => update("phone", nextPhoneInput(draft.phone, value))} /></div>
          <div className="relation-edit-modal__field"><label htmlFor="relation-tag">연락처 태그</label><TextInput id="relation-tag" value={draft.tag || ""} placeholder="예: 주, 남, ☎" onChange={(_event, value) => update("tag", value)} /></div>
          <div className="relation-edit-modal__field"><label htmlFor="relation-consent">연락 동의</label><FormSelect id="relation-consent" value={draft.consent || "X"} onChange={(_event, value) => update("consent", value)}><FormSelectOption value="O" label="O · 동의" /><FormSelectOption value="X" label="X · 미동의 또는 값 없음" /></FormSelect></div>
        </div>
      </ModalBody>
      <ModalFooter><Button variant="primary" onClick={() => { onApply?.(draft); onClose?.(); }}>부모 상세에 반영</Button><Button variant="link" onClick={onClose}>취소</Button></ModalFooter>
    </Modal>
  );
}
