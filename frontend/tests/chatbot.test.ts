import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError } from "../src/shared/api/errors.ts";
import { decodeAction, decodeEvent, decodeResult } from "../src/features/chatbot/model/decode.ts";
import { acceptsSnapshot, ChatbotController } from "../src/features/chatbot/model/controller.ts";
import { filterLabels, progressLabel } from "../src/features/chatbot/model/presentation.ts";
import type { ChatbotTransport } from "../src/features/chatbot/api/port.ts";
import type { ChatbotConversation, ChatbotMessage, ChatbotRequest, ChatbotResult, SubmitQuestion } from "../src/features/chatbot/model/types.ts";

const cid = "10000000-0000-4000-8000-000000000001";
const rid = "20000000-0000-4000-8000-000000000001";
const date = "2026-09-08T01:00:00Z";
const result: ChatbotResult = { kind: "properties", text: "매물 1건을 찾았어요.", filters: { transaction_type: "SALE" }, items: [{ id: "1", title: "합성 단지", subtitle: "매매", fields: [{ label: "가격", value: "10억원" }], action: { type: "open_property", target_id: 1, label: "상세 열기" } }], total: 1, offset: 0, limit: 10, as_of: date, actions: [] };
function req(status: ChatbotRequest["status"] = "RUNNING", revision = 1): ChatbotRequest {
  return { id: rid, conversation_id: cid, status, stage: "searching", revision, failure_code: null, answer: null, created_at: date, completed_at: status === "RUNNING" ? null : date };
}
function message(role: "user" | "assistant" = "user"): ChatbotMessage {
  return { id: role === "user" ? 1 : 2, request_id: rid, sequence_no: role === "user" ? 1 : 2, role, content: role === "user" ? "매매 찾아줘" : "매물 1건", result_payload: role === "user" ? null : result, created_at: date };
}
function conversation(active: ChatbotRequest | null = null): ChatbotConversation {
  return { id: cid, active_request: active, active_filters: {}, state_version: 1, created_at: date, updated_at: date };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((ok, no) => { resolve = ok; reject = no; });
  return { promise, resolve, reject };
}
const controllers: ChatbotController[] = [];
afterEach(() => { for (const controller of controllers.splice(0)) controller.dispose(); });
const tick = () => new Promise<void>((resolve) => setImmediate(resolve));

function fixture(initial: ChatbotRequest | null = null) {
  const db = { conversation: conversation(initial) as ChatbotConversation | null, request: initial ?? req(), messages: initial ? [message()] : [] as ChatbotMessage[] };
  const submissions: SubmitQuestion[] = [];
  let receive: (request: ChatbotRequest) => void = () => {};
  let disconnected: () => void = () => {};
  let closes = 0;
  const transport: ChatbotTransport = {
    discover: async () => ({ enabled: true, conversation: db.conversation }),
    create: async () => { db.conversation = conversation(); return db.conversation; },
    history: async () => ({ items: db.messages, next_cursor: null }),
    submit: async (_id, body) => { submissions.push(body); db.request = req(); db.conversation = conversation(db.request); db.messages = [message()]; return db.request; },
    status: async () => db.request,
    cancel: async () => { db.request = req("CANCELLED", 2); db.conversation = conversation(); return db.request; },
    reset: async () => conversation(), results: async () => result,
    remove: async () => { db.conversation = null; db.messages = []; },
    subscribe: (_id, handler, unavailable) => { receive = handler; disconnected = unavailable; return () => { closes += 1; }; },
  };
  let expired = 0;
  const controller = new ChatbotController(transport, () => { expired += 1; });
  controllers.push(controller);
  return { db, transport, controller, submissions, emit: (value: ChatbotRequest) => receive(value), disconnect: () => disconnected(), closed: () => closes, expired: () => expired };
}

test("actions and stream identities are checked before any navigation or display", () => {
  assert.throws(() => decodeAction({ type: "open_url", target_id: null, label: "주소 열기" }));
  assert.throws(() => decodeAction({ type: "open_property", target_id: null, label: "상세" }));
  assert.throws(() => decodeAction({ type: "open_f2", target_id: 20, label: "음성" }));
  assert.throws(() => decodeResult({ ...result, items: Array.from({ length: 11 }, () => result.items[0]) }));
  const body = { schema_version: 1, request_id: rid, revision: 1, occurred_at: date, type: "snapshot", payload: req() };
  assert.equal(decodeEvent(body, "snapshot", rid).status, "RUNNING");
  assert.throws(() => decodeEvent({ ...body, request_id: cid }, "snapshot", rid));
  assert.throws(() => decodeEvent({ ...body, revision: 4 }, "snapshot", rid));
  assert.throws(() => decodeEvent({ ...body, type: "completed" }, "completed", rid));
});

test("a terminal or newer snapshot never regresses from duplicate or stale events", async () => {
  const f = fixture(req()); f.controller.start(); await tick();
  f.emit(req("RUNNING", 3));
  f.emit(req("RUNNING", 2));
  assert.equal(f.controller.getSnapshot().request?.revision, 3);
  assert.equal(acceptsSnapshot(req("COMPLETED", 4), req("RUNNING", 99)), false);
  const completed = { ...req("COMPLETED", 4), answer: message("assistant") };
  f.db.request = completed; f.db.conversation = conversation(); f.db.messages.push(message("assistant"));
  f.emit(completed); await tick();
  assert.equal(f.controller.getSnapshot().request?.status, "COMPLETED");
  assert.equal(f.controller.getSnapshot().messages.length, 2);
  assert.ok(f.closed() > 0);
  assert.equal(f.submissions.length, 0);
});

test("delete retains visible history until success then discards late SSE and reads", async () => {
  const f = fixture(req()); f.controller.start(); await tick();
  const pending = deferred<void>();
  f.transport.remove = () => pending.promise;
  const removal = f.controller.remove();
  assert.equal(f.controller.getSnapshot().messages.length, 1);
  f.emit({ ...req("COMPLETED", 3), answer: message("assistant") });
  pending.resolve(); await removal;
  f.emit({ ...req("COMPLETED", 4), answer: message("assistant") });
  assert.equal(f.controller.getSnapshot().conversation, null);
  assert.equal(f.controller.getSnapshot().messages.length, 0);
});

test("failed deletion keeps history and resumes observation", async () => {
  const f = fixture(req()); f.controller.start(); await tick();
  f.transport.remove = async () => { throw new ApiError({ kind: "offline", message: "secret ignored" }); };
  assert.equal(await f.controller.remove(), false);
  assert.equal(f.controller.getSnapshot().messages.length, 1);
  assert.doesNotMatch(f.controller.getSnapshot().error ?? "", /secret/);
  f.emit(req("RUNNING", 4));
  assert.equal(f.controller.getSnapshot().request?.revision, 4);
});

test("disposing an identity prevents late reads from publishing its conversation", async () => {
  const f = fixture();
  const pending = deferred<{ enabled: boolean; conversation: ChatbotConversation }>();
  f.transport.discover = () => pending.promise;
  f.controller.start(); f.controller.dispose();
  pending.resolve({ enabled: true, conversation: conversation(req()) }); await tick();
  assert.equal(f.controller.getSnapshot().conversation, null);
});

test("an ambiguous POST is not repeated by refresh, reconnect, or a second click", async () => {
  const f = fixture(); f.controller.start(); await tick();
  f.transport.submit = async (_id, body) => { f.submissions.push(body); throw new ApiError({ kind: "offline", message: "lost" }); };
  assert.equal(await f.controller.send("매매 찾아줘"), false);
  assert.equal(f.controller.getSnapshot().admissionUnknown, true);
  await f.controller.send("매매 찾아줘");
  assert.equal(f.submissions.length, 1);
  await f.controller.refresh();
  assert.equal(f.submissions.length, 1);
  assert.equal(f.controller.getSnapshot().admissionUnknown, false);
});

test("interrupted requests restore after refresh and manual retry uses a new key", async () => {
  const f = fixture(req("INTERRUPTED", 2));
  f.db.conversation = conversation(); f.controller.start(); await tick();
  assert.equal(f.controller.getSnapshot().request?.status, "INTERRUPTED");
  await f.controller.send("매매 찾아줘");
  await f.controller.cancel(); await tick();
  await f.controller.send("매매 찾아줘");
  assert.equal(f.submissions.length, 2);
  assert.notEqual(f.submissions[0]?.client_request_id, f.submissions[1]?.client_request_id);
});

test("another tab deleting the conversation clears its cached messages and pages", async () => {
  const f = fixture(req()); f.controller.start(); await tick();
  f.db.conversation = null; f.db.messages = [];
  await f.controller.refresh();
  assert.equal(f.controller.getSnapshot().conversation, null);
  assert.deepEqual(f.controller.getSnapshot().messages, []);
  assert.equal(f.controller.getSnapshot().request, null);
});

test("expired session clears memory and signals parent once", async () => {
  const f = fixture(req()); f.controller.start(); await tick();
  f.transport.discover = async () => { throw new ApiError({ kind: "unauthorized", message: "denied" }); };
  await f.controller.refresh();
  assert.equal(f.expired(), 1);
  assert.equal(f.controller.getSnapshot().availability, "disabled");
  assert.deepEqual(f.controller.getSnapshot().messages, []);
});

test("filters show business labels and source units without internal normalized objects", () => {
  assert.deepEqual(filterLabels({ tool: "properties", transaction_type: "RENT", price_expression: "15억 이하", internal: "prompt", price_bounds: { minimum: 0 }, area_basis: "exclusive" }), ["조회 대상: 매물장", "거래: 월세", "금액: 15억 이하", "면적 기준: 전용"]);
});

test("terminal failures explain context limits, timeout and provider recovery safely", () => {
  const failed = req("FAILED", 2);
  assert.match(progressLabel({ ...failed, failure_code: "CHATBOT_CONTEXT_LIMIT" }), /입력 한도.*이력은 유지/);
  assert.match(progressLabel({ ...failed, failure_code: "CHATBOT_TIMEOUT" }), /시간이 초과/);
  assert.match(progressLabel({ ...failed, failure_code: "CHATBOT_BUSY" }), /다른 요청/);
  assert.match(progressLabel({ ...failed, failure_code: "CHATBOT_UNAVAILABLE" }), /장부 화면/);
  assert.doesNotMatch(progressLabel({ ...failed, failure_code: "secret-provider-error" }), /secret/);
});

test("history refresh restores a cursor after a gap larger than the latest page", async () => {
  const f = fixture(req()); f.controller.start(); await tick();
  const latest = { ...message(), id: 41, sequence_no: 41 };
  f.transport.history = async () => ({ items: [latest], next_cursor: 41 });
  await f.controller.refresh();
  assert.deepEqual(f.controller.getSnapshot().messages.map((entry) => entry.sequence_no), [41]);
  assert.equal(f.controller.getSnapshot().nextCursor, 41);
});
