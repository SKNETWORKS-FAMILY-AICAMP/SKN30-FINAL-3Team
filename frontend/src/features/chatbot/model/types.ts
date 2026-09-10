/** Chatbot HTTP DTOs. No model prompt or browser persistence belongs to this boundary. */
export interface ChatbotAction {
  type: "open_f2" | "open_property" | "open_buyer";
  target_id: number | null;
  label: string;
}
export interface ChatbotResult {
  kind: "properties" | "buyers" | "agenda" | "help" | "clarification" | "unsupported" | "action";
  text: string;
  filters: Record<string, unknown>;
  items: {
    id: string;
    title: string;
    subtitle: string;
    fields: { label: string; value: string }[];
    action: ChatbotAction | null;
  }[];
  total: number;
  offset: number;
  limit: number;
  as_of: string;
  actions: ChatbotAction[];
}
export interface ChatbotMessage {
  id: number;
  request_id: string;
  sequence_no: number;
  role: "user" | "assistant";
  content: string;
  result_payload: ChatbotResult | null;
  created_at: string;
}
export type RequestStatus = "ACCEPTED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export interface ChatbotRequest {
  id: string;
  conversation_id: string;
  status: RequestStatus;
  stage: string;
  revision: number;
  failure_code: string | null;
  search_filters?: Record<string, unknown> | null;
  answer: ChatbotMessage | null;
  created_at: string;
  completed_at: string | null;
}
export interface ChatbotConversation {
  id: string;
  state_version: number;
  active_filters: Record<string, unknown>;
  active_request: ChatbotRequest | null;
  created_at: string;
  updated_at: string;
}
export interface HistoryPage {
  items: ChatbotMessage[];
  next_cursor: number | null;
}
export interface ConversationResponse {
  enabled: boolean;
  conversation: ChatbotConversation | null;
}
export interface SubmitQuestion {
  question: string;
  client_request_id: string;
  expected_version: number;
  reference_message_id?: number;
}
export function isActive(request: ChatbotRequest | null): boolean {
  return request?.status === "ACCEPTED" || request?.status === "RUNNING";
}
