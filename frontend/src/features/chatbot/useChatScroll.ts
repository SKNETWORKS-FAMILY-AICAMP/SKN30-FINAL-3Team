import { useLayoutEffect, useRef, useState } from "react";
import type { ChatbotMessage } from "./model/types.ts";

/** Keep the reader's place when history is prepended or a result changes height. */
export function useChatScroll(open: boolean, conversationId: string | undefined, messages: ChatbotMessage[]) {
  const history = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const anchor = useRef<{ id: string; top: number } | null>(null);
  const previousConversation = useRef(conversationId);
  const previousMessage = useRef<number | undefined>(undefined);
  const savedScrollTop = useRef(0);
  const [showLatest, setShowLatest] = useState(false);
  const hasMessages = messages.length > 0;

  function update() {
    const element = history.current;
    if (!element) return;
    savedScrollTop.current = element.scrollTop;
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    following.current = atBottom;
    setShowLatest(hasMessages && !atBottom);
  }
  function latest() {
    following.current = true;
    anchor.current = null;
    if (history.current) history.current.scrollTop = hasMessages ? history.current.scrollHeight : 0;
    setShowLatest(false);
  }
  function remember() {
    const element = history.current;
    if (!element) return;
    following.current = false;
    const top = element.getBoundingClientRect().top;
    const visible = [...element.querySelectorAll<HTMLElement>("[data-message-id]")]
      .find((message) => message.getBoundingClientRect().bottom > top);
    anchor.current = visible?.dataset.messageId ? { id: visible.dataset.messageId, top: visible.getBoundingClientRect().top - top } : null;
  }
  useLayoutEffect(() => {
    if (open && history.current) history.current.scrollTop = savedScrollTop.current;
  }, [open]);
  useLayoutEffect(() => {
    const element = history.current;
    if (!element) return;
    if (previousConversation.current !== conversationId) {
      previousConversation.current = conversationId;
      previousMessage.current = undefined;
      latest();
    }
    const saved = anchor.current;
    const newest = messages.at(-1);
    if (!hasMessages) element.scrollTop = 0;
    else if (saved) {
      const message = element.querySelector<HTMLElement>(`[data-message-id="${saved.id}"]`);
      if (message) element.scrollTop += message.getBoundingClientRect().top - element.getBoundingClientRect().top - saved.top;
      anchor.current = null;
    } else if (following.current) {
      const answer = newest?.role === "assistant" && newest.id !== previousMessage.current
        ? element.querySelector<HTMLElement>(`[data-message-id="${newest.id}"]`) : null;
      // A completed answer can contain ten results. Show its summary before its last row.
      if (answer && answer.getBoundingClientRect().height > element.clientHeight) {
        element.scrollTop += answer.getBoundingClientRect().top - element.getBoundingClientRect().top;
      } else element.scrollTop = element.scrollHeight;
    }
    previousMessage.current = newest?.id;
    update();
  }, [messages, open, conversationId]);

  useLayoutEffect(() => {
    if (!open || !history.current || !content.current) return;
    const observer = new ResizeObserver(() => {
      if (following.current && history.current) history.current.scrollTop = hasMessages ? history.current.scrollHeight : 0;
      update();
    });
    observer.observe(history.current);
    observer.observe(content.current);
    return () => observer.disconnect();
  }, [open, hasMessages]);

  return { history, content, showLatest, update, latest, remember };
}
