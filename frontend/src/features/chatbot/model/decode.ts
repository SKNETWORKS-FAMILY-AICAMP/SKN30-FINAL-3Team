import { asArray, asBoolean, asNullableString, asNumber, asRecord, asString, DecodeError } from "../../../shared/decode/index.ts";
import type { ChatbotAction, ChatbotConversation, ChatbotMessage, ChatbotRequest, ChatbotResult, ConversationResponse, HistoryPage } from "./types.ts";

function integer(value: unknown, path: string, minimum = 0): number {
  const n = asNumber(value, path);
  if (!Number.isSafeInteger(n) || n < minimum) throw new DecodeError(path, "유효한 정수가 필요합니다.");
  return n;
}
function choice<const T extends readonly string[]>(value: unknown, options: T, path: string): T[number] {
  const text = asString(value, path);
  if (!options.includes(text)) throw new DecodeError(path, "허용되지 않은 값입니다.");
  return text;
}
function timestamp(value: unknown, path: string): string {
  const text = asString(value, path);
  if (!Number.isFinite(Date.parse(text))) throw new DecodeError(path, "유효한 시각이 필요합니다.");
  return text;
}
function identifier(value: unknown, path: string): string {
  const text = asString(value, path);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(text)) {
    throw new DecodeError(path, "유효한 식별자가 필요합니다.");
  }
  return text;
}
export function decodeAction(value: unknown, path = "action"): ChatbotAction {
  const r = asRecord(value, path);
  const type = choice(r.type, ["open_f2", "open_property", "open_buyer", "open_calendar"] as const, `${path}.type`);
  const target = r.target_id === null ? null : integer(r.target_id, `${path}.target_id`, 1);
  if ((type === "open_f2" && target !== null) || (type !== "open_f2" && target === null)) {
    throw new DecodeError(path, "이동 대상이 동작과 일치하지 않습니다.");
  }
  return { type, target_id: target, label: asString(r.label, `${path}.label`) };
}
export function decodeResult(value: unknown, path = "result"): ChatbotResult {
  const r = asRecord(value, path);
  const result: ChatbotResult = {
    kind: choice(r.kind, ["properties", "buyers", "agenda", "help", "clarification", "unsupported", "action"] as const, `${path}.kind`),
    text: asString(r.text, `${path}.text`),
    filters: asRecord(r.filters, `${path}.filters`),
    items: asArray(r.items, `${path}.items`).map((value, i) => {
      const p = `${path}.items[${i}]`;
      const item = asRecord(value, p);
      return {
        id: asString(item.id, `${p}.id`), title: asString(item.title, `${p}.title`), subtitle: asString(item.subtitle, `${p}.subtitle`),
        fields: asArray(item.fields, `${p}.fields`).map((entry, j) => {
          const field = asRecord(entry, `${p}.fields[${j}]`);
          return { label: asString(field.label, `${p}.fields[${j}].label`), value: asString(field.value, `${p}.fields[${j}].value`) };
        }),
        action: item.action === null ? null : decodeAction(item.action, `${p}.action`),
      };
    }),
    total: integer(r.total, `${path}.total`), offset: integer(r.offset, `${path}.offset`),
    limit: integer(r.limit, `${path}.limit`, 1), as_of: timestamp(r.as_of, `${path}.as_of`),
    actions: asArray(r.actions, `${path}.actions`).map((action, i) => decodeAction(action, `${path}.actions[${i}]`)),
  };
  if (result.limit !== 10 || result.items.length > result.limit || result.items.length > result.total) {
    throw new DecodeError(path, "결과 개수와 페이지 정보가 일치하지 않습니다.");
  }
  return result;
}
export function decodeMessage(value: unknown, path = "message"): ChatbotMessage {
  const r = asRecord(value, path);
  return {
    id: integer(r.id, `${path}.id`, 1), request_id: identifier(r.request_id, `${path}.request_id`),
    sequence_no: integer(r.sequence_no, `${path}.sequence_no`, 1),
    role: choice(r.role, ["user", "assistant"] as const, `${path}.role`),
    content: asString(r.content, `${path}.content`),
    result_payload: r.result_payload === null ? null : decodeResult(r.result_payload, `${path}.result_payload`),
    created_at: timestamp(r.created_at, `${path}.created_at`),
  };
}
export function decodeRequest(value: unknown, path = "request"): ChatbotRequest {
  const r = asRecord(value, path);
  const answer = r.answer === null ? null : decodeMessage(r.answer, `${path}.answer`);
  const id = identifier(r.id, `${path}.id`);
  if (answer !== null && (answer.request_id !== id || answer.role !== "assistant")) throw new DecodeError(path, "답변이 요청과 일치하지 않습니다.");
  return {
    id, conversation_id: identifier(r.conversation_id, `${path}.conversation_id`),
    status: choice(r.status, ["ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"] as const, `${path}.status`),
    stage: asString(r.stage, `${path}.stage`), revision: integer(r.revision, `${path}.revision`),
    failure_code: asNullableString(r.failure_code, `${path}.failure_code`), answer,
    search_filters: r.search_filters === null || r.search_filters === undefined ? null : asRecord(r.search_filters, `${path}.search_filters`),
    created_at: timestamp(r.created_at, `${path}.created_at`),
    completed_at: r.completed_at === null ? null : timestamp(r.completed_at, `${path}.completed_at`),
  };
}
export function decodeConversation(value: unknown, path = "conversation"): ChatbotConversation {
  const r = asRecord(value, path);
  const id = identifier(r.id, `${path}.id`);
  const active = r.active_request === null ? null : decodeRequest(r.active_request, `${path}.active_request`);
  if (active !== null && active.conversation_id !== id) throw new DecodeError(path, "활성 요청이 대화와 일치하지 않습니다.");
  return {
    id, state_version: integer(r.state_version, `${path}.state_version`),
    active_filters: asRecord(r.active_filters, `${path}.active_filters`), active_request: active,
    created_at: timestamp(r.created_at, `${path}.created_at`), updated_at: timestamp(r.updated_at, `${path}.updated_at`),
  };
}
export function decodeConversationResponse(value: unknown): ConversationResponse {
  const r = asRecord(value, "response");
  return { enabled: asBoolean(r.enabled, "response.enabled"), conversation: r.conversation === null ? null : decodeConversation(r.conversation) };
}
export function decodeHistory(value: unknown): HistoryPage {
  const r = asRecord(value, "history");
  return {
    items: asArray(r.items, "history.items").map((item, i) => decodeMessage(item, `history.items[${i}]`)),
    next_cursor: r.next_cursor === null ? null : integer(r.next_cursor, "history.next_cursor", 1),
  };
}
/** Both EventSource's event name and the body must agree before applying a snapshot. */
export function decodeEvent(value: unknown, eventType: string, requestId: string): ChatbotRequest {
  const r = asRecord(value, "event");
  if (r.schema_version !== 1 || r.type !== eventType || r.request_id !== requestId) throw new DecodeError("event", "이벤트 식별자가 일치하지 않습니다.");
  timestamp(r.occurred_at, "event.occurred_at");
  const request = decodeRequest(r.payload, "event.payload");
  if (request.id !== requestId || request.revision !== integer(r.revision, "event.revision")) throw new DecodeError("event", "이벤트 버전이 일치하지 않습니다.");
  const terminal: Record<string, string> = { completed: "COMPLETED", failed: "FAILED", cancelled: "CANCELLED", interrupted: "INTERRUPTED" };
  if (terminal[eventType] && terminal[eventType] !== request.status) throw new DecodeError("event", "이벤트 상태가 일치하지 않습니다.");
  return request;
}
