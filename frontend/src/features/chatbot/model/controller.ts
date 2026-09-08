import { ApiError } from "../../../shared/api/errors.ts";
import type { ChatbotTransport } from "../api/port.ts";
import { isActive } from "./types.ts";
import type { ChatbotConversation, ChatbotMessage, ChatbotRequest, ChatbotResult } from "./types.ts";

export interface ChatbotState {
  availability: "loading" | "enabled" | "disabled" | "error";
  conversation: ChatbotConversation | null;
  messages: ChatbotMessage[];
  nextCursor: number | null;
  request: ChatbotRequest | null;
  connection: "online" | "recovering" | "offline";
  busy: "sending" | "deleting" | "resetting" | "history" | "page" | "canceling" | null;
  pages: Record<string, ChatbotResult>;
  error: string | null;
  /** A failed admission has unknown outcome until a successful read; never auto POST it. */
  admissionUnknown: boolean;
}

function emptyState(): ChatbotState {
  return { availability: "loading", conversation: null, messages: [], nextCursor: null, request: null, connection: "online", busy: null, pages: {}, error: null, admissionUnknown: false };
}
export function mergeMessages(old: ChatbotMessage[], incoming: ChatbotMessage[]): ChatbotMessage[] {
  const unique = new Map(old.map((message) => [message.id, message]));
  for (const message of incoming) unique.set(message.id, message);
  return [...unique.values()].sort((a, b) => a.sequence_no - b.sequence_no);
}
export function acceptsSnapshot(current: ChatbotRequest | null, incoming: ChatbotRequest): boolean {
  if (current?.id !== incoming.id) return true;
  if (!isActive(current) && isActive(incoming)) return false;
  return incoming.revision > current.revision;
}
export function chatbotError(error: unknown): string {
  if (!(error instanceof ApiError)) return "응답을 확인하지 못했어요. 상태를 다시 확인해 주세요.";
  switch (error.kind) {
    case "unauthorized": return "로그인이 만료됐어요. 다시 로그인해 주세요.";
    case "forbidden": return "이 대화를 사용할 권한이 없어요. 로그인 상태를 확인해 주세요.";
    case "notFound": return "대화 또는 항목이 삭제되었어요. 상태를 다시 확인해 주세요.";
    case "conflict": return "다른 탭에서 대화가 변경되었거나 질문을 처리 중이에요. 최신 상태를 확인해 주세요.";
    case "validation": return "질문이나 조건을 확인해 주세요. 질문은 2,000자까지 입력할 수 있어요.";
    case "rateLimited": return "지금 다른 요청을 처리하고 있어요. 잠시 후 다시 전송해 주세요.";
    case "offline": return "연결이 끊겼어요. 서버의 처리 결과는 아직 알 수 없어요.";
    case "contract": return "응답 형식을 확인할 수 없어요. 상태를 다시 확인해 주세요.";
    default: return "지금은 답변을 준비할 수 없어요. 잠시 후 상태를 다시 확인해 주세요.";
  }
}

/** One controller per signed-in identity; only validated server state lives in memory.
 * Generation invalidates every in-flight read and SSE callback on delete or unmount.
 * No HTTP read, timer or reconnect calls submit().
 */
export class ChatbotController {
  private state = emptyState();
  private listeners = new Set<() => void>();
  private generation = 0;
  private readRevision = 0;
  private abort = new AbortController();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private closeStream: (() => void) | undefined;
  private streamId: string | null = null;
  private alive = false;
  private pollCount = 0;
  private polling = false;
  readonly transport: ChatbotTransport;
  private readonly expire: () => void;

  constructor(transport: ChatbotTransport, onSessionExpired: () => void) {
    this.transport = transport;
    this.expire = onSessionExpired;
  }
  readonly getSnapshot = (): ChatbotState => this.state;
  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private patch(value: Partial<ChatbotState>): void {
    this.state = { ...this.state, ...value };
    for (const listener of this.listeners) listener();
  }
  private current(generation: number): boolean { return this.alive && generation === this.generation; }
  private invalidate(): void {
    this.generation += 1;
    this.readRevision += 1;
    this.abort.abort();
    this.abort = new AbortController();
    this.closeStream?.();
    this.closeStream = undefined;
    this.streamId = null;
  }
  start(): void {
    this.alive = true;
    void this.refresh();
    this.schedule();
  }
  dispose(): void {
    this.alive = false;
    this.invalidate();
    clearTimeout(this.timer);
  }
  private fail(error: unknown): void {
    if (error instanceof ApiError && error.kind === "canceled") return;
    if (error instanceof ApiError && error.kind === "unauthorized") {
      this.invalidate();
      this.patch({ ...emptyState(), availability: "disabled" });
      this.expire();
      return;
    }
    this.patch({ error: chatbotError(error), connection: error instanceof ApiError && error.kind === "offline" ? "offline" : this.state.connection });
  }
  private schedule(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { void this.poll().finally(() => { if (this.alive) this.schedule(); }); }, isActive(this.state.request) ? 2_000 : 10_000);
  }
  private async poll(): Promise<void> {
    if (!this.alive || this.polling || this.state.busy !== null || this.state.availability === "disabled") return;
    this.polling = true;
    const generation = this.generation;
    const request = this.state.request;
    try {
      if (request !== null && isActive(request)) {
        const next = await this.transport.status(request.id, this.abort.signal);
        if (!this.current(generation)) return;
        this.receive(next);
        this.pollCount += 1;
        if (this.pollCount % 5 === 0) await this.refresh();
      } else await this.refresh();
    } catch (error) {
      if (!this.current(generation)) return;
      this.fail(error);
      if (error instanceof ApiError && error.kind === "notFound") await this.refresh();
    } finally { this.polling = false; }
  }
  /** Restore together so an old history response cannot resurrect a deleted conversation. */
  async refresh(): Promise<void> {
    if (!this.alive || this.state.busy === "deleting") return;
    const generation = this.generation;
    const readRevision = ++this.readRevision;
    try {
      const response = await this.transport.discover(this.abort.signal);
      const conversation = response.conversation;
      const history = response.enabled && conversation ? await this.transport.history(conversation.id, null, this.abort.signal) : { items: [], next_cursor: null };
      const latestMessage = history.items.at(-1);
      const latestRequest = conversation?.active_request ?? (latestMessage ? await this.transport.status(latestMessage.request_id, this.abort.signal) : null);
      if (!this.current(generation) || readRevision !== this.readRevision) return;
      const sameConversation = conversation !== null && conversation.id === this.state.conversation?.id;
      // A stream may have already received a newer completion while these reads were running.
      const candidate = latestRequest;
      const retained = sameConversation && this.state.request && candidate?.id === this.state.request.id && !acceptsSnapshot(this.state.request, candidate) ? this.state.request : candidate;
      const merged = sameConversation ? mergeMessages(this.state.messages, history.items) : history.items;
      // A long absence can exceed one page. Do not silently display a gap as complete history.
      const gap = merged.some((message, i) => i > 0 && message.sequence_no > (merged[i - 1]?.sequence_no ?? 0) + 1);
      this.patch({ availability: response.enabled ? "enabled" : "disabled", conversation, messages: gap ? history.items : merged, nextCursor: sameConversation && this.state.messages.length > 0 && !gap ? this.state.nextCursor : history.next_cursor, request: retained, pages: sameConversation ? this.state.pages : {}, connection: "online", admissionUnknown: false, error: null });
      this.watch();
    } catch (error) {
      if (!this.current(generation) || readRevision !== this.readRevision) return;
      if (this.state.availability === "loading") this.patch({ availability: "error" });
      this.fail(error);
    }
  }
  private receive(request: ChatbotRequest): void {
    if (request.conversation_id !== this.state.conversation?.id) return;
    if (this.state.request && request.id !== this.state.request.id) return;
    this.patch({ connection: "online" });
    if (!acceptsSnapshot(this.state.request, request)) return;
    this.patch({ request, messages: request.answer ? mergeMessages(this.state.messages, [request.answer]) : this.state.messages });
    this.watch();
    if (!isActive(request)) void this.refresh();
  }
  private watch(): void {
    const active = this.state.request;
    const id = active && isActive(active) ? active.id : null;
    if (id === this.streamId) return;
    this.closeStream?.();
    this.closeStream = undefined;
    this.streamId = id;
    if (id === null) return;
    const generation = this.generation;
    this.closeStream = this.transport.subscribe(id, (request) => {
      if (this.current(generation) && this.streamId === id) this.receive(request);
    }, () => {
      if (this.current(generation) && this.streamId === id) {
        this.patch({ connection: "recovering" });
        void this.poll();
      }
    });
    this.schedule();
  }
  async send(question: string, referenceMessageId?: number): Promise<boolean> {
    const text = question.trim();
    if (!text || text.length > 2_000 || this.state.busy || isActive(this.state.request) || this.state.admissionUnknown || this.state.availability !== "enabled") return false;
    const generation = this.generation;
    this.readRevision += 1;
    this.patch({ busy: "sending", error: null });
    let submitted = false;
    try {
      const conversation = this.state.conversation ?? await this.transport.create(this.abort.signal);
      if (!this.current(generation)) return false;
      this.patch({ conversation });
      const request = await this.transport.submit(conversation.id, { question: text, client_request_id: crypto.randomUUID(), expected_version: conversation.state_version, ...(referenceMessageId === undefined ? {} : { reference_message_id: referenceMessageId }) }, this.abort.signal);
      if (!this.current(generation)) return false;
      submitted = true;
      this.patch({ request });
      this.watch();
      await this.refresh();
      return true;
    } catch (error) {
      if (this.current(generation)) {
        const ambiguous = error instanceof ApiError && ["offline", "server", "contract"].includes(error.kind);
        this.patch({ admissionUnknown: ambiguous });
        this.fail(error);
        // Reconcile only through GET; manual terminal retry creates a new key.
        if (error instanceof ApiError && ["conflict", "notFound"].includes(error.kind)) await this.refresh();
      }
      return submitted;
    } finally { if (this.current(generation)) this.patch({ busy: null }); }
  }
  async cancel(): Promise<void> {
    const active = this.state.request;
    if (!active || !isActive(active) || this.state.busy) return;
    const generation = this.generation;
    this.readRevision += 1;
    this.patch({ busy: "canceling", error: null });
    try {
      const result = await this.transport.cancel(active.id, this.abort.signal);
      if (this.current(generation)) this.receive(result);
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally { if (this.current(generation)) this.patch({ busy: null }); }
  }
  async resetFilters(): Promise<void> {
    const conversation = this.state.conversation;
    if (!conversation || this.state.busy || isActive(this.state.request)) return;
    const generation = this.generation;
    this.readRevision += 1;
    this.patch({ busy: "resetting", error: null });
    try {
      const result = await this.transport.reset(conversation.id, conversation.state_version, this.abort.signal);
      if (this.current(generation)) this.patch({ conversation: result });
    } catch (error) { if (this.current(generation)) { this.fail(error); if (error instanceof ApiError && error.kind === "conflict") await this.refresh(); } }
    finally { if (this.current(generation)) this.patch({ busy: null }); }
  }
  async remove(): Promise<boolean> {
    const conversation = this.state.conversation;
    if (!conversation || this.state.busy) return false;
    this.invalidate();
    const generation = this.generation;
    this.patch({ busy: "deleting", error: null });
    try {
      await this.transport.remove(conversation.id, this.abort.signal);
      if (!this.current(generation)) return false;
      this.patch({ ...emptyState(), availability: "enabled" });
      return true;
    } catch (error) {
      if (this.current(generation)) { this.fail(error); this.watch(); }
      return false;
    } finally { if (this.current(generation)) this.patch({ busy: null }); }
  }
  async loadOlder(): Promise<void> {
    const conversation = this.state.conversation;
    const before = this.state.nextCursor;
    if (!conversation || before === null || this.state.busy) return;
    const generation = this.generation;
    this.patch({ busy: "history", error: null });
    try {
      const history = await this.transport.history(conversation.id, before, this.abort.signal);
      if (this.current(generation)) this.patch({ messages: mergeMessages(history.items, this.state.messages), nextCursor: history.next_cursor });
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally { if (this.current(generation)) this.patch({ busy: null }); }
  }
  async page(requestId: string, offset: number): Promise<void> {
    if (this.state.busy || !this.state.messages.some((message) => message.request_id === requestId && message.result_payload !== null)) return;
    const generation = this.generation;
    this.patch({ busy: "page", error: null });
    try {
      const result = await this.transport.results(requestId, offset, this.abort.signal);
      if (this.current(generation)) this.patch({ pages: { ...this.state.pages, [requestId]: result } });
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally { if (this.current(generation)) this.patch({ busy: null }); }
  }
}
