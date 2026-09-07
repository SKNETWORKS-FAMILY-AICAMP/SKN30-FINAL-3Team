/**
 * 캘린더 일정 생성·수정 공용 폼.
 *
 * 종류는 F1-SC-05 권장 어휘(임장·계약·잔금·이사·기타) 중에서 고른다. 서버 계약은 임의 문자열을
 * 받지만, 화면에서 직접 입력까지 열면 콤보박스 컴포넌트가 새로 필요해 이번 범위를 넘는다 —
 * 필요해지면 후속 작업에서 다룬다.
 */

import { useEffect, useState } from "react";
import {
  Button,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  TextArea,
  TextInput,
} from "@patternfly/react-core";
import { describeForUser } from "./api/errors.ts";
import { DEFAULT_CALENDAR_CATEGORY, KNOWN_CALENDAR_CATEGORIES } from "./model/dto.ts";
import type { CalendarEventCreateInput, CalendarEventDto, CalendarEventUpdateInput } from "./model/dto.ts";

interface Draft {
  title: string;
  category: string;
  event_date: string;
  start_time: string;
  end_time: string;
  location: string;
  memo: string;
}

function draftFor(event: CalendarEventDto | null, fallbackDate: string): Draft {
  if (event == null) {
    return {
      title: "",
      category: DEFAULT_CALENDAR_CATEGORY,
      event_date: fallbackDate,
      start_time: "",
      end_time: "",
      location: "",
      memo: "",
    };
  }
  return {
    title: event.title,
    category: event.category,
    event_date: event.event_date,
    start_time: event.start_time?.slice(0, 5) ?? "",
    end_time: event.end_time?.slice(0, 5) ?? "",
    location: event.location ?? "",
    memo: event.memo ?? "",
  };
}

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export interface CalendarEventModalProps {
  isOpen: boolean;
  /** 새 일정을 만들 때 미리 채울 날짜. */
  fallbackDate: string;
  /** 있으면 수정, 없으면 생성. */
  event: CalendarEventDto | null;
  onClose: () => void;
  onCreate: (input: CalendarEventCreateInput) => Promise<CalendarEventDto>;
  onUpdate: (eventId: number, input: CalendarEventUpdateInput) => Promise<CalendarEventDto>;
  onDelete: (eventId: number, rowVersion: number) => Promise<void>;
}

export function CalendarEventModal({
  isOpen,
  fallbackDate,
  event,
  onClose,
  onCreate,
  onUpdate,
  onDelete,
}: CalendarEventModalProps) {
  const [draft, setDraft] = useState<Draft>(() => draftFor(event, fallbackDate));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setDraft(draftFor(event, fallbackDate));
      setError(null);
    }
  }, [isOpen, event, fallbackDate]);

  const update = <K extends keyof Draft>(field: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [field]: value }));

  function validate(): string | null {
    if (draft.title.trim() === "") return "제목을 입력해 주세요.";
    if (draft.event_date === "") return "날짜를 입력해 주세요.";
    if (draft.start_time !== "" && draft.end_time !== "" && draft.end_time < draft.start_time) {
      return "종료 시각은 시작 시각보다 빠를 수 없습니다.";
    }
    return null;
  }

  async function handleSubmit() {
    const validationError = validate();
    if (validationError != null) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        title: draft.title.trim(),
        category: draft.category,
        event_date: draft.event_date,
        start_time: orNull(draft.start_time),
        end_time: orNull(draft.end_time),
        location: orNull(draft.location),
        memo: orNull(draft.memo),
      };
      if (event == null) {
        await onCreate(payload);
      } else {
        await onUpdate(event.id, { ...payload, row_version: event.row_version });
      }
      onClose();
    } catch (cause) {
      setError(describeForUser(cause));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete() {
    if (event == null) return;
    setSubmitting(true);
    setError(null);
    try {
      await onDelete(event.id, event.row_version);
      onClose();
    } catch (cause) {
      setError(describeForUser(cause));
      setSubmitting(false);
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} variant="small" aria-label={event == null ? "일정 추가" : "일정 수정"}>
      <ModalHeader title={event == null ? "일정 추가" : "일정 수정"} />
      <ModalBody>
        <Form data-screen-id="F4-MOD-011" data-requirement-ids="F4-CAL-01~05">
          <FormGroup label="제목" isRequired fieldId="calendar-event-title">
            <TextInput
              id="calendar-event-title"
              value={draft.title}
              onChange={(_event, value) => update("title", value)}
              isRequired
            />
          </FormGroup>
          <FormGroup label="종류" fieldId="calendar-event-category">
            <FormSelect
              id="calendar-event-category"
              value={draft.category}
              onChange={(_event, value) => update("category", value)}
            >
              {KNOWN_CALENDAR_CATEGORIES.map((category) => (
                <FormSelectOption key={category} value={category} label={category} />
              ))}
            </FormSelect>
          </FormGroup>
          <FormGroup label="날짜" isRequired fieldId="calendar-event-date">
            <TextInput
              id="calendar-event-date"
              type="date"
              value={draft.event_date}
              onChange={(_event, value) => update("event_date", value)}
              isRequired
            />
          </FormGroup>
          <FormGroup label="시작 시각" fieldId="calendar-event-start">
            <TextInput
              id="calendar-event-start"
              type="time"
              value={draft.start_time}
              onChange={(_event, value) => update("start_time", value)}
            />
          </FormGroup>
          <FormGroup label="종료 시각" fieldId="calendar-event-end">
            <TextInput
              id="calendar-event-end"
              type="time"
              value={draft.end_time}
              onChange={(_event, value) => update("end_time", value)}
            />
          </FormGroup>
          <FormGroup label="장소" fieldId="calendar-event-location">
            <TextInput
              id="calendar-event-location"
              value={draft.location}
              onChange={(_event, value) => update("location", value)}
            />
          </FormGroup>
          <FormGroup label="메모" fieldId="calendar-event-memo">
            <TextArea
              id="calendar-event-memo"
              value={draft.memo}
              onChange={(_event, value) => update("memo", value)}
              rows={3}
            />
          </FormGroup>
        </Form>
        {error != null && (
          <p className="calendar__form-error" role="alert">
            {error}
          </p>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" onClick={handleSubmit} isDisabled={submitting} isLoading={submitting}>
          저장
        </Button>
        {event != null && (
          <Button variant="danger" onClick={handleDelete} isDisabled={submitting}>
            삭제
          </Button>
        )}
        <Button variant="link" onClick={onClose} isDisabled={submitting}>
          취소
        </Button>
      </ModalFooter>
    </Modal>
  );
}
