import type { ChatbotConversation, ChatbotRequest, ChatbotResult, ConversationResponse, HistoryPage, SubmitQuestion } from "../model/types.ts";

/** HTTP and SSE are independent. Subscribing or reconnecting never submits a question. */
export interface ChatbotTransport {
  discover(signal: AbortSignal): Promise<ConversationResponse>;
  create(signal: AbortSignal): Promise<ChatbotConversation>;
  history(id: string, before: number | null, signal: AbortSignal): Promise<HistoryPage>;
  submit(id: string, body: SubmitQuestion, signal: AbortSignal): Promise<ChatbotRequest>;
  status(id: string, signal: AbortSignal): Promise<ChatbotRequest>;
  cancel(id: string, signal: AbortSignal): Promise<ChatbotRequest>;
  reset(id: string, version: number, signal: AbortSignal): Promise<ChatbotConversation>;
  results(id: string, offset: number, signal: AbortSignal): Promise<ChatbotResult>;
  remove(id: string, signal: AbortSignal): Promise<void>;
  subscribe(id: string, receive: (request: ChatbotRequest) => void, unavailable: () => void): () => void;
}
