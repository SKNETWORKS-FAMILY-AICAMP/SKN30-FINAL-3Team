import { APP_ENV } from "../../../config/env.ts";
import { request, expectNoContent } from "../../../shared/api/httpClient.ts";
import { decodeConversation, decodeConversationResponse, decodeEvent, decodeHistory, decodeRequest, decodeResult } from "../model/decode.ts";
import type { ChatbotTransport } from "./port.ts";

const prefix = "/chatbot";
export const chatbotTransport: ChatbotTransport = {
  discover: (signal) => request(`${prefix}/conversation`, { signal, decode: decodeConversationResponse }),
  create: (signal) => request(`${prefix}/conversations`, { method: "POST", signal, decode: decodeConversation }),
  history: (id, before, signal) => request(`${prefix}/conversations/${id}/messages`, { query: { before, limit: 30 }, signal, decode: decodeHistory }),
  submit: (id, body, signal) => request(`${prefix}/conversations/${id}/requests`, { method: "POST", body, signal, decode: decodeRequest }),
  status: (id, signal) => request(`${prefix}/requests/${id}`, { signal, decode: decodeRequest }),
  cancel: (id, signal) => request(`${prefix}/requests/${id}/cancel`, { method: "POST", signal, decode: decodeRequest }),
  reset: (id, version, signal) => request(`${prefix}/conversations/${id}/filters`, { method: "PATCH", body: { expected_version: version }, signal, decode: decodeConversation }),
  results: (id, offset, signal) => request(`${prefix}/requests/${id}/results`, { query: { offset }, signal, decode: decodeResult }),
  remove: (id, signal) => request(`${prefix}/conversations/${id}`, { method: "DELETE", signal, decode: expectNoContent }),
  subscribe(id, receive, unavailable) {
    const source = new EventSource(`${APP_ENV.apiBaseUrl.replace(/\/$/, "")}${prefix}/requests/${id}/events`, { withCredentials: true });
    for (const type of ["snapshot", "progress", "completed", "failed", "cancelled", "interrupted"]) {
      source.addEventListener(type, (event) => {
        try {
          if (!(event instanceof MessageEvent)) return;
          const parsed: unknown = JSON.parse(String(event.data));
          receive(decodeEvent(parsed, type, id));
        } catch {
          // Do not show server text or accept partial payloads. GET provides a validated fallback.
          source.close();
          unavailable();
        }
      });
    }
    source.onerror = unavailable;
    return () => source.close();
  },
};
