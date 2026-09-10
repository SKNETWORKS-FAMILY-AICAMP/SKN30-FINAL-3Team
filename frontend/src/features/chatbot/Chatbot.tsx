import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Alert, Button, Form, Label, Modal, ModalBody, ModalFooter, ModalHeader, Popover, Spinner, TextArea, Title } from "@patternfly/react-core";
import { ArrowDownIcon, ArrowRightIcon, CalendarAltIcon, ChevronRightIcon, CommentsIcon, MicrophoneIcon, ArrowUpIcon, SearchIcon, QuestionCircleIcon, TrashIcon, UsersIcon } from "@patternfly/react-icons";
import { chatbotTransport } from "./api/httpTransport.ts";
import { ChatbotController } from "./model/controller.ts";
import { filterLabels, formatChatTime, progressLabel } from "./model/presentation.ts";
import { isActive } from "./model/types.ts";
import type { ChatbotAction, ChatbotResult } from "./model/types.ts";
import { useChatScroll } from "./useChatScroll.ts";
import "./Chatbot.css";

export interface ChatbotProps {
  userKey: string;
  onAction: (action: ChatbotAction) => void;
  onSessionExpired: () => void;
  /** Existing modal and unsaved work have priority over this non-modal panel. */
  suspended?: boolean;
}
const EXAMPLES = [
  { category: "매물 찾기", question: "매매 15억 이하 매물 찾기", icon: SearchIcon },
  { category: "손님 찾기", question: "전세를 찾는 손님 보기", icon: UsersIcon },
  { category: "일정 확인", question: "이번 달 만기 일정 보기", icon: CalendarAltIcon },
];

function ResultView({ result, busy, onAction, onPage }: { result: ChatbotResult; busy: boolean; onAction: (action: ChatbotAction) => void; onPage: (offset: number) => void }) {
  const searchable = ["properties", "buyers", "agenda"].includes(result.kind);
  const labels = filterLabels(result.filters);
  return <div className="chatbot__result">
    {searchable && <div className="chatbot__result-summary"><strong>전체 {result.total.toLocaleString("ko-KR")}건</strong><span className="chatbot__meta">{result.items.length ? `${result.offset + 1}–${result.offset + result.items.length}건 표시` : "표시할 결과 없음"}</span></div>}
    {searchable && <p className="chatbot__meta">{formatChatTime(result.as_of)} 기준</p>}
    {labels.length > 0 && <ul className="chatbot__filters" aria-label="이 답변의 검색 조건">{labels.map((label) => <li key={label}><Label>{label}</Label></li>)}</ul>}
    {searchable && result.total === 0 && <p className="chatbot__empty">조건에 맞는 결과가 없어요. 가격·기간을 넓히거나 검색 조건을 초기화해 보세요.</p>}
    {result.items.length > 0 && <ol className="chatbot__results" start={result.offset + 1}>
      {result.items.map((item) => <li key={item.id}>
        <strong>{item.title}</strong>{item.subtitle && <p className="chatbot__meta">{item.subtitle}</p>}
        <dl>{item.fields.map((field, index) => <div key={`${field.label}-${index}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
        {item.action && <Button variant="link" isInline icon={<ArrowRightIcon />} iconPosition="right" onClick={() => item.action && onAction(item.action)}>{item.action.label}</Button>}
      </li>)}
    </ol>}
    {result.actions.map((action, index) => <Button key={`${action.type}-${index}`} variant="secondary" onClick={() => onAction(action)}>{action.label}</Button>)}
    {searchable && (result.offset > 0 || result.total > result.limit) && <nav aria-label="챗봇 결과 페이지" className="chatbot__actions">
      <Button variant="secondary" isDisabled={busy || result.offset === 0} onClick={() => onPage(Math.max(0, result.offset - result.limit))}>이전 결과</Button>
      <span className="chatbot__meta">{Math.floor(result.offset / result.limit) + 1} / {Math.ceil(result.total / result.limit)}</span>
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
  const [helpOpen, setHelpOpen] = useState(false);
  const [referenceId, setReferenceId] = useState<number | undefined>();
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const previousConversationId = useRef<string | null>(null);
  const scroll = useChatScroll(open, state.conversation?.id, state.messages);
  const active = isActive(state.request);
  const locked = state.busy !== null || active || state.admissionUnknown || state.availability !== "enabled";
  const draftLocked = state.busy === "sending" || state.busy === "deleting" || state.availability !== "enabled";
  const searchingFilters = active ? state.request?.search_filters : null;
  const filters = filterLabels(searchingFilters ?? state.conversation?.active_filters ?? {});
  const failed = state.request && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(state.request.status);
  const lastQuestion = state.messages.find((message) => message.request_id === state.request?.id && message.role === "user")?.content;
  const referenceableIds = state.messages.filter((message) => message.role === "assistant").slice(-2).map((message) => message.id);

  useEffect(() => { controller.start(); return () => controller.dispose(); }, [controller]);
  useEffect(() => {
    if (suspended) { setOpen(false); setConfirmDelete(false); setHelpOpen(false); }
  }, [suspended]);
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    void controller.refresh();
  }, [open, controller]);
  useEffect(() => {
    const id = state.conversation?.id ?? null;
    const eligible = state.messages.filter((message) => message.role === "assistant").slice(-2);
    if (id !== previousConversationId.current || (referenceId !== undefined && !eligible.some((message) => message.id === referenceId))) setReferenceId(undefined);
    previousConversationId.current = id;
  }, [state.conversation?.id, state.messages, referenceId]);

  useLayoutEffect(() => {
    if (!input.current || !open) return;
    input.current.style.height = "auto";
    input.current.style.height = `${input.current.scrollHeight}px`;
  }, [question, open]);

  function close() {
    setOpen(false);
    requestAnimationFrame(() => trigger.current?.focus());
  }
  function action(value: ChatbotAction) {
    setOpen(false);
    onAction(value);
  }
  async function send(value = question, retry = false) {
    if (locked || !value.trim()) return;
    scroll.latest();
    // A retry refers to the failed question, never to a separately selected answer.
    if (await controller.send(value, retry ? undefined : referenceId)) {
      if (!retry) { setQuestion(""); setReferenceId(undefined); }
      requestAnimationFrame(() => {
        // Do not steal focus if the reader moved to another control while sending.
        if (document.activeElement === document.body || document.activeElement?.closest(".chatbot__composer")) input.current?.focus();
      });
    }
  }

  if (suspended || state.availability === "disabled" || state.availability === "loading") return null;
  return <>
    <div className="chatbot" onKeyDown={(event) => { if (event.key === "Escape" && open && !confirmDelete && !helpOpen && !(event.target instanceof Element && event.target.closest(".pf-v6-c-popover"))) { event.stopPropagation(); close(); } }}>
      {open && <section id="chatbot-panel" className="chatbot__panel" aria-labelledby="chatbot-title">
        <header className="chatbot__header">
          <div className="chatbot__identity"><span className="chatbot__avatar" aria-hidden="true"><CommentsIcon /></span><div><Title headingLevel="h2" size="lg" id="chatbot-title">업무 챗봇</Title><p className="chatbot__meta">매물 · 손님 · 일정 조회</p></div></div>
          <div className="chatbot__actions">
            <Button variant="plain" icon={<TrashIcon />} aria-label="전체 삭제" title="대화 전체 삭제" isDisabled={!state.conversation || state.busy !== null} onClick={() => setConfirmDelete(true)} />
            <Popover position="bottom-end" headerContent="대화 저장·기억 안내" headerComponent="h3" closeBtnAriaLabel="도움말 닫기" onShow={() => setHelpOpen(true)} onHide={() => setHelpOpen(false)} bodyContent={<div className="chatbot__help-content">
              {state.request?.status === "COMPLETED" && <p>답변을 저장했어요.</p>}
              <p>질문과 답변은 저장되며, 다시 접속해도 대화를 이어서 볼 수 있어요.</p>
              <p>답변에는 현재 검색 조건과 직전 2회 질문·답변을 참고해요.</p>
              <p>접어도 진행 중인 요청은 계속돼요. 전체 삭제 시 저장된 대화는 복구할 수 없어요.</p>
              <p>Enter로 전송 · Shift+Enter로 줄바꿈<br />질문은 2,000자까지 입력할 수 있어요.</p>
            </div>}>
              <Button variant="plain" icon={<QuestionCircleIcon />} aria-label="대화 도움말" />
            </Popover>
            <Button variant="plain" icon={<ChevronRightIcon />} onClick={close} aria-label="업무 챗봇 접기" title="업무 챗봇 접기" />
          </div>
        </header>
        {filters.length > 0 && <div className="chatbot__context">
          <span className="chatbot__context-title">검색 조건</span>
          <ul className="chatbot__filters" tabIndex={0} aria-label={searchingFilters ? "검색 중인 조건" : "현재 검색 조건"}>{filters.map((label) => <li key={label}><Label>{label}</Label></li>)}</ul>
          <Button variant="link" isInline aria-label="검색 조건 초기화" isDisabled={locked} onClick={() => { void controller.resetFilters(); }}>초기화</Button>
        </div>}
        <div className="chatbot__history-wrap">
          <div className="chatbot__history" ref={scroll.history} onScroll={scroll.update} aria-label="대화 이력" tabIndex={0}>
            <div ref={scroll.content}>
              {state.nextCursor !== null && <Button className="chatbot__older" variant="link" isLoading={state.busy === "history"} isDisabled={state.busy !== null} onClick={() => { scroll.remember(); void controller.loadOlder(); }}>이전 대화 이력 보기</Button>}
              {state.messages.length === 0 && <div className="chatbot__intro">
                <div className="chatbot__welcome"><Title headingLevel="h3" size="xl">어떤 업무를 도와드릴까요?</Title><p className="chatbot__meta">찾고 싶은 조건을 말해 주세요.<br />장부와 일정을 조회하고 상세 화면으로 연결해 드려요.</p></div>
                <Title headingLevel="h3" size="md">이런 걸 물어보세요</Title>
                {EXAMPLES.map(({ category, question: example, icon: Icon }) => <Button className="chatbot__suggestion" key={example} variant="plain" isBlock aria-label={example} isDisabled={draftLocked} onClick={() => { setQuestion(example); input.current?.focus(); }}><span className="chatbot__suggestion-content"><Icon aria-hidden="true" /><span><strong>{category}</strong><span className="chatbot__meta">{example}</span></span><ArrowRightIcon aria-hidden="true" /></span></Button>)}
                <Button className="chatbot__voice" variant="link" icon={<MicrophoneIcon />} onClick={() => action({ type: "open_f2", target_id: null, label: "음성메모 입력 열기" })}>음성메모로 장부 작성하기</Button>
              </div>}
              <ol className="chatbot__messages">
                {state.messages.map((message) => <li key={message.id} data-message-id={message.id} className={`chatbot__message chatbot__message--${message.role}`}>
                  <p className="chatbot__speaker"><span>{message.role === "user" ? "나" : "업무 챗봇"}</span><time dateTime={message.created_at}>{formatChatTime(message.created_at)}</time></p>
                  <p className="chatbot__message-text">{message.role === "assistant" ? state.pages[message.request_id]?.text ?? message.content : message.content}</p>
                  {message.result_payload && <>
                    <ResultView result={state.pages[message.request_id] ?? message.result_payload} busy={state.busy !== null} onAction={action} onPage={(offset) => { if (referenceId === message.id) setReferenceId(undefined); void controller.page(message.request_id, offset); }} />
                    {message.result_payload.items.length > 0 && <Button className="chatbot__reference-action" variant="link" isInline isDisabled={locked || !referenceableIds.includes(message.id) || Boolean(state.pages[message.request_id])} onClick={() => { setReferenceId(message.id); input.current?.focus(); }}>이 답변을 참고하여 질문</Button>}
                    {state.pages[message.request_id] && <p className="chatbot__meta">새로 조회한 결과는 각 항목의 상세 버튼으로 열어 주세요.</p>}
                  </>}
                </li>)}
              </ol>
            </div>
          </div>
          {scroll.showLatest && <div className="chatbot__latest"><Button variant="secondary" icon={<ArrowDownIcon />} onClick={() => { scroll.latest(); input.current?.focus(); }}>최신 대화로 이동</Button></div>}
        </div>
        <div className="chatbot__footer">
          {state.error && <Alert variant="warning" isInline title={state.error} />}
          {(state.connection !== "online" || state.error || state.admissionUnknown) && <div className="chatbot__connection">
            <p role="status">{state.connection === "recovering" ? "연결 상태를 확인하고 있어요. 서버 처리는 계속돼요." : state.admissionUnknown ? "전송 결과를 먼저 확인해 주세요. 질문을 자동으로 다시 보내지 않아요." : "상태를 확인한 후 다시 시도할 수 있어요."}</p>
            <Button variant="secondary" isDisabled={state.busy !== null} onClick={() => { void controller.refresh(); }}>상태 다시 확인</Button>
          </div>}
          <div className={`chatbot__request-state${!active && !failed ? " chatbot__request-state--quiet" : ""}`}>
            <div role="status" aria-live="polite" aria-atomic="true" className="chatbot__progress">{active && <Spinner size="sm" aria-hidden="true" />}{state.request ? progressLabel(state.request) : ""}</div>
            {active && <Button variant="secondary" size="sm" isDisabled={state.busy !== null} onClick={() => { void controller.cancel(); }}>요청 중지</Button>}
          </div>
          {failed && lastQuestion && <Button variant="secondary" isDisabled={locked} onClick={() => { void send(lastQuestion, true); }}>이 질문 다시 시도</Button>}
          {referenceId !== undefined && <div className="chatbot__reference"><p className="chatbot__meta">선택한 답변을 참고해요.</p><Button variant="link" isInline isDisabled={locked} onClick={() => setReferenceId(undefined)}>선택 해제</Button></div>}
          <Form className="chatbot__composer" onSubmit={(event) => { event.preventDefault(); void send(); }}>
              <TextArea className="chatbot__input" aria-label="질문" id="chatbot-question" ref={input} value={question} onChange={(_event, value) => setQuestion(value)} placeholder={active ? "다음 질문을 미리 작성해 두세요" : "예: 매매 15억 이하 매물을 찾아줘"} resizeOrientation="none" rows={1} maxLength={2000} isDisabled={draftLocked} aria-describedby="chatbot-input-help" onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); void send(); }
              }} />
            <div className="chatbot__composer-actions">
              <span id="chatbot-input-help" className="pf-v6-screen-reader">Enter로 전송, Shift+Enter로 줄바꿈. 최대 2,000자.{active && " 답변이 끝나면 전송할 수 있어요."}</span>
              {question.length >= 1800 && <span className="chatbot__meta">{question.length.toLocaleString("ko-KR")}/2,000</span>}
              <Button className="chatbot__send" type="submit" variant="primary" isCircle aria-label="전송" title="전송" icon={<ArrowUpIcon />} isDisabled={locked || !question.trim()} isLoading={state.busy === "sending"} />
            </div>
          </Form>
        </div>
      </section>}
      <Button ref={trigger} className="chatbot__trigger" variant="primary" icon={<CommentsIcon />} aria-expanded={open} aria-controls={open ? "chatbot-panel" : undefined} aria-label={open ? "업무 챗봇 접기" : `업무 챗봇 열기${active ? " · 처리 중" : ""}`} onClick={() => open ? close() : setOpen(true)}>업무 챗봇{active ? " · 처리 중" : ""}</Button>
    </div>
    <Modal isOpen={confirmDelete} onClose={() => { if (state.busy !== "deleting") setConfirmDelete(false); }} variant="small" aria-label="대화 전체 삭제">
      <ModalHeader title="대화 전체를 삭제할까요?" />
      <ModalBody><p>저장된 질문·답변과 요청 기록을 즉시 삭제해요. 진행 중인 답변도 저장되지 않으며 되돌릴 수 없어요. 장부 데이터에는 영향을 주지 않아요.</p>{state.error && <Alert variant="warning" isInline title={state.error} />}</ModalBody>
      <ModalFooter><Button variant="danger" isLoading={state.busy === "deleting"} isDisabled={state.busy !== null} onClick={() => { void controller.remove().then((removed) => { if (removed) { setConfirmDelete(false); setQuestion(""); setReferenceId(undefined); requestAnimationFrame(() => input.current?.focus()); } }); }}>대화 전체 삭제</Button><Button variant="link" isDisabled={state.busy === "deleting"} onClick={() => setConfirmDelete(false)}>삭제 취소</Button></ModalFooter>
    </Modal>
  </>;
}
