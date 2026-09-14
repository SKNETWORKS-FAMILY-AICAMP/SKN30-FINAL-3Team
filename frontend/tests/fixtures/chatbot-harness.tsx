import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { Chatbot } from "../../src/features/chatbot/index.ts";
import { setCsrfToken } from "../../src/shared/api/session.ts";
import "@patternfly/react-core/dist/styles/base.css";

setCsrfToken("synthetic-chatbot-test-csrf");
function Harness() {
  const [user, setUser] = useState("synthetic-user-a");
  const [action, setAction] = useState("");
  const [expired, setExpired] = useState(false);
  return <main>
    <h1>챗봇 통합 테스트</h1>
    <button onClick={() => setUser("synthetic-user-b")}>테스트 계정 전환</button>
    <output aria-label="실행한 화면 이동">{action}</output>
    <output aria-label="세션 만료">{String(expired)}</output>
    <Chatbot userKey={user} onAction={(value) => setAction(JSON.stringify(value))} onSessionExpired={() => setExpired(true)} />
  </main>;
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<React.StrictMode><Harness /></React.StrictMode>);
