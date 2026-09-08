import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Alert, Button, Form, FormGroup, Label, Modal, ModalBody, ModalFooter, ModalHeader, TextArea, Title } from "@patternfly/react-core";
import { chatbotTransport } from "./api/httpTransport.ts";
import { ChatbotController } from "./model/controller.ts";
import { filterLabels, formatChatTime, progressLabel } from "./model/presentation.ts";
import { isActive } from "./model/types.ts";
import type { ChatbotAction, ChatbotResult } from "./model/types.ts";
import "./Chatbot.css";

export interface ChatbotProps {
  userKey: string;
  onAction: (action: ChatbotAction) => void;
  onSessionExpired: () => void;
  /** Existing modal and unsaved work have priority over this non-modal panel. */
  suspended?: boolean;
}
const EXAMPLES = ["매매 15억 이하 매물 찾기", "전세를 찾는 손님 보기", "이번 달 만기 일정 보기"];

function ResultView({ result, busy, onAction, onPage }: { result: ChatbotResult; busy: boolean; onAction: (action: ChatbotAction) => void; onPage: (offset: number) => void }) {
  const searchable = ["properties", "buyers", "agenda"].includes(result.kind);
  return <div className="chatbot__result">
    {searchable && <p className="chatbot__meta">전체 {result.total.toLocaleString("ko-KR")}건 · {result.items.length ? `${result.offset + 1}–${result.offset + result.items.length}건 표시` : "표시할 결과 없음"}<br />{formatChatTime(result.as_of)} 기준</p>}
    {filterLabels(result.filters).length > 0 && <ul className="chatbot__filters" aria-label="이 답변의 검색 조건">{filterLabels(result.filters).map((label) => <li key={label}><Label>{label}</Label></li>)}</ul>}
    {result.items.length > 0 && <ol className="chatbot__results" start={result.offset + 1}>
      {result.items.map((item) => <li key={item.id}>
        <strong>{item.title}</strong>{item.subtitle && <p>{item.subtitle}</p>}
        <dl>{item.fields.map((field, index) => <div key={`${field.label}-${index}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
        {item.action && <Button variant="link" isInline onClick={() => item.action && onAction(item.action)}>{item.action.label}</Button>}
      </li>)}
    </ol>}
    {result.actions.map((action, index) => <Button key={`${action.type}-${index}`} variant="secondary" onClick={() => onAction(action)}>{action.label}</Button>)}
    {searchable && (result.offset > 0 || result.total > result.limit) && <nav aria-label="챗봇 결과 페이지" className="chatbot__actions">
      <Button variant="secondary" isDisabled={busy || result.offset === 0} onClick={() => onPage(Math.max(0, result.offset - result.limit))}>이전 결과</Button>
      <Button variant="secondary" isDisabled={busy || result.offset + result.items.length >= result.total} onClick={() => onPage(result.offset + result.limit)}>다음 결과</Button>
    </nav>}
  </div>;
}

/** Keying the inner view also removes drafts and confirmation UI on account change. */
export function Chatbot(props: ChatbotProps) { return <ChatbotForUser key={props.userKey} {...props} />; }

function ChatbotForUser({ onAction, onSessionExpired, suspended = false }: ChatbotProps) {
  const expire = useRef(onSessionExpired);
  expire.current = onSessionExpired;
  const controller = useMemo(() => new ChatbotController(chatbotTransport, () => expire.current()), []);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [referenceId, setReferenceId] = useState<number | undefined>();
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const history = useRef<HTMLDivElement>(null);
  const followBottom = useRef(true);
  const previousConversationId = useRef<string | null>(null);
  const active = isActive(state.request);
  const locked = state.busy !== null || active || state.admissionUnknown || state.availability !== "enabled";
  const searchingFilters = active ? state.request?.search_filters : null;
  const filters = filterLabels(searchingFilters ?? state.conversation?.active_filters ?? {});
  const failed = state.request && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(state.request.status);
  const lastQuestion = state.messages.find((message) => message.request_id === state.request?.id && message.role === "user")?.content;
  const referenceableIds = state.messages.filter((message) => message.role === "assistant").slice(-2).map((message) => message.id);

  useEffect(() => { controller.start(); return () => controller.dispose(); }, [controller]);
  useEffect(() => {
    if (suspended) { setOpen(false); setConfirmDelete(false); }
  }, [suspended]);
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    void controller.refresh();
  }, [open, controller]);
  useEffect(() => {
    if (followBottom.current && history.current) history.current.scrollTop = history.current.scrollHeight;
  }, [state.messages, open]);
  useEffect(() => {
    const id = state.conversation?.id ?? null;
    const eligible = state.messages.filter((message) => message.role === "assistant").slice(-2);
    if (id !== previousConversationId.current || (referenceId !== undefined && !eligible.some((message) => message.id === referenceId))) setReferenceId(undefined);
    previousConversationId.current = id;
  }, [state.conversation?.id, state.messages, referenceId]);

  function close() {
    setOpen(false);
    requestAnimationFrame(() => trigger.current?.focus());
  }
  function action(value: ChatbotAction) {
    setOpen(false);
    onAction(value);
  }
  async function send(value = question) {
    followBottom.current = true;
    if (await controller.send(value, referenceId)) { setQuestion(""); setReferenceId(undefined); }
  }

  if (suspended || state.availability === "disabled" || state.availability === "loading") return null;
  return <>
    <div className="chatbot" onKeyDown={(event) => { if (event.key === "Escape" && open && !confirmDelete) { event.stopPropagation(); close(); } }}>
      {open && <section id="chatbot-panel" className="chatbot__panel" aria-labelledby="chatbot-title">
        <header className="chatbot__header">
          <Title headingLevel="h2" size="lg" id="chatbot-title">업무 챗봇</Title>
          <div className="chatbot__actions">
            <Button variant="link" isInline isDisabled={!state.conversation || state.busy !== null} onClick={() => setConfirmDelete(true)}>전체 삭제</Button>
            <Button variant="plain" onClick={close} aria-label="업무 챗봇 접기">접기</Button>
          </div>
        </header>
        <div className="chatbot__history" ref={history} onScroll={() => { if (history.current) followBottom.current = history.current.scrollHeight - history.current.scrollTop - history.current.clientHeight < 48; }} aria-label="대화 이력" tabIndex={0}>
          {state.nextCursor !== null && <Button variant="link" isDisabled={state.busy !== null} onClick={() => { followBottom.current = false; void controller.loadOlder(); }}>이전 대화 이력 보기</Button>}
          {state.messages.length === 0 && <div className="chatbot__intro">
            <p>장부 조건을 찾고 음성메모 입력을 도와드려요.</p>
            <Title headingLevel="h3" size="md">이런 걸 물어보세요</Title>
            {EXAMPLES.map((example) => <Button key={example} variant="secondary" isDisabled={locked} onClick={() => { setQuestion(example); input.current?.focus(); }}>{example}</Button>)}
            <Button variant="secondary" onClick={() => action({ type: "open_f2", target_id: null, label: "음성메모 입력 열기" })}>음성메모로 장부 작성하기</Button>
          </div>}
          <ol className="chatbot__messages">
            {state.messages.map((message) => <li key={message.id} className={`chatbot__message chatbot__message--${message.role}`}>
              <p className="chatbot__speaker">{message.role === "user" ? "나" : "업무 챗봇"} <time dateTime={message.created_at}>{formatChatTime(message.created_at)}</time></p>
              <p className="chatbot__message-text">{message.role === "assistant" ? state.pages[message.request_id]?.text ?? message.content : message.content}</p>
              {message.result_payload && <>
                <ResultView result={state.pages[message.request_id] ?? message.result_payload} busy={state.busy !== null} onAction={action} onPage={(offset) => { if (referenceId === message.id) setReferenceId(undefined); void controller.page(message.request_id, offset); }} />
                {message.result_payload.items.length > 0 && <Button variant="link" isInline isDisabled={locked || !referenceableIds.includes(message.id) || Boolean(state.pages[message.request_id])} onClick={() => { setReferenceId(message.id); input.current?.focus(); }}>이 답변을 참고하여 질문</Button>}
                {state.pages[message.request_id] && <p className="chatbot__meta">새로 조회한 결과는 각 항목의 상세 버튼으로 열어 주세요.</p>}
              </>}
            </li>)}
          </ol>
        </div>
        <div className="chatbot__footer">
          {state.error && <Alert variant="warning" isInline title={state.error} />}
          {(state.connection !== "online" || state.error || state.admissionUnknown) && <div className="chatbot__connection">
            <p role="status">{state.connection === "recovering" ? "연결 상태를 확인하고 있어요. 서버 처리는 계속돼요." : state.admissionUnknown ? "전송 결과를 먼저 확인해 주세요. 질문을 자동으로 다시 보내지 않아요." : "상태를 확인한 후 다시 시도할 수 있어요."}</p>
            <Button variant="secondary" isDisabled={state.busy !== null} onClick={() => { void controller.refresh(); }}>상태 다시 확인</Button>
          </div>}
          <div role="status" aria-live="polite" aria-atomic="true" className="chatbot__progress">{progressLabel(state.request)}</div>
          {active && <Button variant="secondary" isDisabled={state.busy !== null} onClick={() => { void controller.cancel(); }}>요청 중지</Button>}
          {failed && lastQuestion && <Button variant="secondary" isDisabled={locked} onClick={() => { void send(lastQuestion); }}>이 질문 다시 시도</Button>}
          {filters.length > 0 && <div>
            <ul className="chatbot__filters" aria-label={searchingFilters ? "검색 중인 조건" : "현재 검색 조건"}>{filters.map((label) => <li key={label}><Label>{label}</Label></li>)}</ul>
            <Button variant="link" isInline isDisabled={locked} onClick={() => { void controller.resetFilters(); }}>검색 조건 초기화</Button>
          </div>}
          <p id="chatbot-memory" className="chatbot__meta">대화 이력은 저장돼요. 답변에는 현재 검색 조건과 직전 2회 질문·답변을 참고해요.</p>
          {referenceId !== undefined && <p className="chatbot__meta">선택한 답변을 참고해요. <Button variant="link" isInline isDisabled={locked} onClick={() => setReferenceId(undefined)}>선택 해제</Button></p>}
          <Form onSubmit={(event) => { event.preventDefault(); void send(); }}>
            <FormGroup label="질문" fieldId="chatbot-question">
              <TextArea id="chatbot-question" ref={input} value={question} onChange={(_event, value) => setQuestion(value)} resizeOrientation="vertical" rows={2} maxLength={2000} isDisabled={locked} aria-describedby="chatbot-memory chatbot-input-help" onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); void send(); }
              }} />
            </FormGroup>
            <div className="chatbot__composer-actions"><span id="chatbot-input-help" className="chatbot__meta">{question.length}/2,000 · Shift+Enter 줄바꿈</span><Button type="submit" variant="primary" isDisabled={locked || !question.trim()} isLoading={state.busy === "sending"}>전송</Button></div>
          </Form>
        </div>
      </section>}
      <Button ref={trigger} className="chatbot__trigger" variant="primary" aria-expanded={open} aria-controls={open ? "chatbot-panel" : undefined} aria-label={open ? "업무 챗봇 접기" : `업무 챗봇 열기${active ? " · 처리 중" : ""}`} onClick={() => open ? close() : setOpen(true)}>업무 챗봇{active ? " · 처리 중" : ""}</Button>
    </div>
    <Modal isOpen={confirmDelete} onClose={() => { if (state.busy !== "deleting") setConfirmDelete(false); }} variant="small" aria-label="대화 전체 삭제">
      <ModalHeader title="대화 전체를 삭제할까요?" />
      <ModalBody><p>저장된 질문·답변과 요청 기록을 즉시 삭제해요. 진행 중인 답변도 저장되지 않으며 되돌릴 수 없어요. 장부 데이터에는 영향을 주지 않아요.</p>{state.error && <Alert variant="warning" isInline title={state.error} />}</ModalBody>
      <ModalFooter><Button variant="danger" isLoading={state.busy === "deleting"} isDisabled={state.busy !== null} onClick={() => { void controller.remove().then((removed) => { if (removed) { setConfirmDelete(false); setQuestion(""); setReferenceId(undefined); requestAnimationFrame(() => input.current?.focus()); } }); }}>대화 전체 삭제</Button><Button variant="link" isDisabled={state.busy === "deleting"} onClick={() => setConfirmDelete(false)}>삭제 취소</Button></ModalFooter>
    </Modal>
  </>;
}
