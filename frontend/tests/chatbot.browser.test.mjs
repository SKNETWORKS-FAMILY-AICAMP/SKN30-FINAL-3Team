import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { after, before, test } from "node:test";
import { randomUUID } from "node:crypto";
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

// Synthetic HTTP+real SSE fixture. Browser uses the production transport/controller/components.
let vite, browser, backend, baseUrl;
const cid = "10000000-0000-4000-8000-000000000001";
const date = "2026-09-08T01:00:00Z";
const sockets = new Set();
const streams = new Set();
let db;
function reset() {
  for (const stream of streams) stream.end(); streams.clear();
  db = { enabled: true, conversation: null, messages: [], request: null, submissions: [], mutations: [], failDelete: false, failStatus: false, delayHistory: false, pendingHistory: [], disabledDiscovery: false, historyPageSize: 0 };
}
function conversation(active = null) { return { id: cid, active_request: active, active_filters: {}, state_version: 1, created_at: date, updated_at: date }; }
function request(id = randomUUID()) { return { id, conversation_id: cid, status: "RUNNING", stage: "interpreting", revision: 1, failure_code: null, answer: null, created_at: date, completed_at: null }; }
function result(offset = 0) {
  return { kind: "properties", text: "매물 11건을 찾았어요.", filters: { tool: "properties", transaction_type: "SALE", price_expression: "15억 이하" }, total: 11, offset, limit: 10, as_of: date, actions: [], items: Array.from({ length: offset === 0 ? 10 : 1 }, (_, index) => ({ id: String(index + offset + 1), title: `합성 단지 ${index + offset + 1}`, subtitle: "매매", fields: [{ label: "가격", value: "10억원" }], action: { type: "open_property", target_id: index + offset + 1, label: `매물 ${index + offset + 1} 상세 열기` } })) };
}
function json(response, body, status = 200) { response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); response.end(JSON.stringify(body)); }
function event(type, value = db.request) {
  return `event: ${type}\ndata: ${JSON.stringify({ schema_version: 1, request_id: value.id, revision: value.revision, occurred_at: date, type, payload: value })}\n\n`;
}
function emit(type, value = db.request) { for (const stream of streams) stream.write(event(type, value)); }
function complete() {
  const sequence = (db.messages.at(-1)?.sequence_no ?? 0) + 1;
  const answer = { id: sequence, request_id: db.request.id, sequence_no: sequence, role: "assistant", content: result().text, result_payload: result(), created_at: date };
  db.request = { ...db.request, status: "COMPLETED", stage: "completed", revision: 4, completed_at: date, answer };
  db.messages.push(answer); db.conversation = { ...conversation(), state_version: 2, active_filters: result().filters };
  emit("completed");
}
async function handle(request, response) {
  const url = new URL(request.url, "http://localhost");
  const path = url.pathname.replace("/api/v1/chatbot", "");
  const method = request.method;
  if (method !== "GET") {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    request.body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
    db.mutations.push({ path, csrf: request.headers["x-csrf-token"] });
    if (request.headers["x-csrf-token"] !== "synthetic-chatbot-test-csrf") return json(response, { code: "INVALID_CSRF_TOKEN" }, 403);
  }
  if (path === "/conversation") return json(response, { enabled: db.enabled, conversation: db.conversation });
  if (path === "/conversations" && method === "POST") { db.conversation ??= conversation(); return json(response, db.conversation); }
  if (path.endsWith("/messages")) {
    const before = Number(url.searchParams.get("before") ?? Infinity);
    const eligible = db.messages.filter((message) => message.sequence_no < before);
    const items = db.historyPageSize ? eligible.slice(-db.historyPageSize) : eligible;
    const body = { items, next_cursor: eligible.length > items.length ? items[0].sequence_no : null };
    if (db.delayHistory) { db.pendingHistory.push(() => json(response, body)); return; }
    return json(response, body);
  }
  if (path.endsWith("/requests") && method === "POST") {
    db.submissions.push(request.body); db.request = requestFixture(); db.conversation = conversation(db.request);
    db.messages = [{ id: 1, request_id: db.request.id, sequence_no: 1, role: "user", content: request.body.question, result_payload: null, created_at: date }];
    return json(response, db.request, 202);
  }
  if (path.endsWith("/events")) {
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    response.write(event("snapshot")); streams.add(response); response.on("close", () => streams.delete(response)); return;
  }
  if (path.endsWith("/cancel")) {
    db.request = { ...db.request, status: "CANCELLED", revision: db.request.revision + 1, completed_at: date };
    db.conversation = conversation(); emit("cancelled"); return json(response, db.request);
  }
  if (path.endsWith("/filters") && method === "PATCH") { db.conversation = { ...conversation(), state_version: db.conversation.state_version + 1 }; return json(response, db.conversation); }
  if (path.endsWith("/results")) return json(response, result(Number(url.searchParams.get("offset") ?? 0)));
  if (path.startsWith("/requests/") && method === "GET") {
    if (db.failStatus) return json(response, { code: "UNAVAILABLE" }, 503);
    if (!db.request) return json(response, { code: "NOT_FOUND" }, 404);
    return json(response, db.request);
  }
  if (path === `/conversations/${cid}` && method === "DELETE") {
    if (db.failDelete) return json(response, { code: "DB_UNAVAILABLE", message: "internal secret" }, 503);
    db.conversation = null; db.messages = []; db.request = null;
    response.writeHead(204); response.end(); return;
  }
  return json(response, { code: "NOT_FOUND" }, 404);
}
const requestFixture = request;
before(async () => {
  reset();
  backend = createServer((request, response) => { void handle(request, response).catch(() => { if (!response.headersSent) json(response, { code: "FIXTURE_ERROR" }, 500); }); });
  backend.on("connection", (socket) => { sockets.add(socket); socket.on("close", () => sockets.delete(socket)); });
  backend.listen(0, "127.0.0.1"); await once(backend, "listening");
  const origin = `http://127.0.0.1:${backend.address().port}`;
  vite = spawn(process.execPath, ["./node_modules/vite/bin/vite.js", "--host", "127.0.0.1"], { env: { ...process.env, VITE_AUTH_DEVELOPMENT_ENABLED: "true", VITE_LEDGER_SOURCE: "mock", VITE_API_BASE_URL: "/api/v1", VITE_MOCK_ROW_COUNT: "40", VITE_MOCK_LATENCY_MS: "0", FRONTEND_BACKEND_ORIGIN: origin }, stdio: ["ignore", "pipe", "pipe"] });
  baseUrl = await new Promise((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error(`Vite startup: ${output}`)), 30_000);
    const read = (chunk) => { output += String(chunk).replace(/\u001b\[[0-9;]*m/g, ""); const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//); if (match) { clearTimeout(timeout); resolve(match[0]); } };
    vite.stdout.on("data", read); vite.stderr.on("data", read); vite.once("exit", () => { clearTimeout(timeout); reject(new Error(output)); });
  });
  browser = process.env.CHATBOT_BROWSER_WS_ENDPOINT
    ? await chromium.connect(process.env.CHATBOT_BROWSER_WS_ENDPOINT)
    : await chromium.launch();
});
after(async () => { await browser?.close(); vite?.kill(); for (const socket of sockets) socket.destroy(); await new Promise((resolve) => backend?.close(resolve)); });
async function open(page) {
  await page.goto(`${baseUrl}tests/fixtures/chatbot.html`);
  await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  await page.getByRole("region", { name: "업무 챗봇", exact: true }).waitFor();
}
async function send(page, text = "매매 15억 이하 매물 찾기") {
  await page.getByLabel("질문", { exact: true }).fill(text);
  await page.getByRole("button", { name: "전송", exact: true }).click();
  await page.getByText("검색 조건 해석 중", { exact: true }).waitFor();
}
async function waitForOpenStream() {
  // ACCEPTED/RUNNING can render from POST before EventSource's first connection arrives.
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (streams.size > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("The browser did not establish its SSE subscription");
}

test("recommendations require send; actual SSE restores progress, paging, filters and explicit detail", async () => {
  reset(); const page = await browser.newPage(); const errors = []; page.on("pageerror", (error) => errors.push(String(error)));
  await open(page);
  await page.getByRole("button", { name: "매매 15억 이하 매물 찾기", exact: true }).click();
  assert.equal(db.submissions.length, 0);
  assert.equal(await page.getByLabel("질문", { exact: true }).inputValue(), "매매 15억 이하 매물 찾기");
  await page.getByRole("button", { name: "전송", exact: true }).click();
  await page.getByText("검색 조건 해석 중", { exact: true }).waitFor();
  const newest = { ...db.request, stage: "searching", revision: 3, search_filters: result().filters }; db.request = newest; db.conversation.active_request = newest;
  emit("progress", newest); emit("progress", { ...newest, stage: "interpreting", revision: 2 });
  await page.getByText("장부 조회 중", { exact: true }).waitFor();
  assert.match(await page.getByLabel("검색 중인 조건").innerText(), /금액: 15억 이하/);
  await page.reload(); await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  await page.getByText("장부 조회 중", { exact: true }).waitFor();
  assert.equal(db.submissions.length, 1);
  complete(); await page.getByText("전체 11건", { exact: false }).waitFor();
  await page.getByRole("button", { name: "이 답변을 참고하여 질문" }).click();
  await page.getByText("선택한 답변을 참고해요.", { exact: false }).waitFor();
  await page.getByRole("button", { name: "다음 결과" }).click();
  await page.getByText("합성 단지 11", { exact: true }).waitFor();
  assert.equal(await page.getByText("선택한 답변을 참고해요.", { exact: false }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "이 답변을 참고하여 질문" }).isDisabled(), true);
  await page.getByRole("button", { name: "이전 결과" }).click();
  await page.getByText("합성 단지 1", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "이 답변을 참고하여 질문" }).isDisabled(), true);
  await page.getByRole("button", { name: "다음 결과" }).click();
  await page.getByText("합성 단지 11", { exact: true }).waitFor();
  await page.getByRole("button", { name: "검색 조건 초기화" }).click();
  await page.getByLabel("현재 검색 조건").waitFor({ state: "hidden" });
  assert.ok(db.messages.length > 0);
  await page.getByRole("button", { name: "매물 11 상세 열기", exact: true }).click();
  assert.match(await page.getByLabel("실행한 화면 이동").innerText(), /"target_id":11/);
  assert.equal(await page.locator("#chatbot-panel").count(), 0);
  assert.ok(db.mutations.every((entry) => entry.csrf === "synthetic-chatbot-test-csrf"));
  assert.deepEqual(errors, []); await page.close();
});

test("F2 is only opened by an explicit click and folding restores focus", async () => {
  reset(); const page = await browser.newPage(); await open(page);
  await page.getByLabel("질문", { exact: true }).press("Escape");
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label")?.startsWith("업무 챗봇 열기"));
  assert.match(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), /^업무 챗봇 열기/);
  await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  await page.getByRole("button", { name: "음성메모로 장부 작성하기" }).click();
  assert.match(await page.getByLabel("실행한 화면 이동").innerText(), /"type":"open_f2"/);
  assert.equal(db.submissions.length, 0); assert.equal(db.mutations.length, 0); await page.close();
});

test("deletion failure preserves history; successful delete rejects late SSE and uses a fresh conversation", async () => {
  reset(); const page = await browser.newPage(); await open(page); await send(page);
  const late = { ...db.request, status: "COMPLETED", revision: 9, completed_at: date, answer: null };
  db.failDelete = true;
  await page.getByRole("button", { name: "전체 삭제", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "대화 전체 삭제" });
  await modal.getByRole("button", { name: "대화 전체 삭제", exact: true }).click();
  await modal.getByText("지금은 답변을 준비할 수 없어요.", { exact: false }).waitFor();
  assert.equal(db.messages.length, 1);
  assert.equal(await page.getByText("internal secret").count(), 0);
  db.failDelete = false;
  await modal.getByRole("button", { name: "대화 전체 삭제", exact: true }).click();
  await modal.waitFor({ state: "hidden" }); emit("completed", late);
  await page.getByText("이런 걸 물어보세요", { exact: true }).waitFor();
  assert.equal(await page.locator(".chatbot__message").count(), 0);
  assert.equal(db.submissions.length, 1); await page.close();
});

test("account replacement clears the old draft and drops delayed history", async () => {
  reset(); const page = await browser.newPage(); await open(page); await send(page);
  complete(); await page.getByText("전체 11건", { exact: false }).waitFor();
  await page.getByLabel("질문", { exact: true }).fill("이전 계정의 임시 질문");
  db.delayHistory = true;
  await page.getByRole("button", { name: "업무 챗봇 접기", exact: true }).first().click();
  await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  db.conversation = null; db.messages = []; db.request = null;
  await page.getByRole("button", { name: "테스트 계정 전환" }).click();
  for (const flush of db.pendingHistory.splice(0)) flush(); db.delayHistory = false;
  await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  assert.equal(await page.getByLabel("질문", { exact: true }).inputValue(), "");
  assert.equal(await page.locator(".chatbot__message").count(), 0); await page.close();
});

test("cancel requires a manual retry; mobile view has no horizontal overflow", async () => {
  reset(); const page = await browser.newPage({ viewport: { width: 360, height: 740 } }); await open(page); await send(page);
  await page.getByRole("button", { name: "요청 중지", exact: true }).click();
  await page.getByText("요청을 중지했어요.", { exact: true }).waitFor();
  assert.equal(db.submissions.length, 1);
  await page.getByRole("button", { name: "이 질문 다시 시도", exact: true }).click();
  await page.getByText("검색 조건 해석 중", { exact: true }).waitFor();
  assert.equal(db.submissions.length, 2);
  assert.notEqual(db.submissions[0].client_request_id, db.submissions[1].client_request_id);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  const box = await page.locator("#chatbot-panel").boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= 360);
  await page.close();
});

test("SSE loss falls back to a read and never restarts the running question", async () => {
  reset(); const page = await browser.newPage(); await open(page); await send(page);
  await waitForOpenStream();
  db.failStatus = true;
  for (const stream of streams) stream.end();
  await page.getByText("연결 상태를 확인하고 있어요. 서버 처리는 계속돼요.", { exact: true }).waitFor();
  assert.equal(db.submissions.length, 1);
  db.failStatus = false; complete();
  await page.getByText("전체 11건", { exact: false }).waitFor();
  assert.equal(db.submissions.length, 1);
  await page.close();
});

test("disabled capability makes no chatbot entry point or execution calls", async () => {
  reset(); db.enabled = false; const page = await browser.newPage();
  const discovered = page.waitForResponse((response) => response.url().endsWith("/chatbot/conversation"));
  await page.goto(`${baseUrl}tests/fixtures/chatbot.html`);
  await discovered;
  assert.equal(await page.getByRole("button", { name: /^업무 챗봇 열기/ }).count(), 0);
  assert.equal(db.mutations.length, 0); await page.close();
});

test("another tab advancing recent context or replacing the conversation clears its selected reference", async () => {
  reset(); const page = await browser.newPage(); await open(page); await send(page);
  complete(); await page.getByText("전체 11건", { exact: false }).waitFor();
  await page.getByRole("button", { name: "이 답변을 참고하여 질문" }).click();
  await page.getByText("선택한 답변을 참고해요.", { exact: false }).waitFor();
  for (const sequence of [3, 5]) {
    const id = randomUUID();
    db.messages.push({ id: sequence, request_id: id, sequence_no: sequence, role: "user", content: "도움말", result_payload: null, created_at: date });
    const answer = { id: sequence + 1, request_id: id, sequence_no: sequence + 1, role: "assistant", content: "장부 조건 조회를 도와드려요.", result_payload: null, created_at: date };
    db.messages.push(answer); db.request = { ...request(id), status: "COMPLETED", revision: 2, completed_at: date, answer };
  }
  await page.getByRole("button", { name: "업무 챗봇 접기", exact: true }).first().click();
  await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  await page.getByText("선택한 답변을 참고해요.", { exact: false }).waitFor({ state: "hidden" });
  assert.equal(await page.getByRole("button", { name: "이 답변을 참고하여 질문" }).isDisabled(), true);
  // The same identity can replace its one conversation from another tab.
  db.conversation = { ...conversation(), id: randomUUID() }; db.messages = []; db.request = null;
  await page.getByRole("button", { name: "업무 챗봇 접기", exact: true }).first().click();
  await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
  await page.getByText("이런 걸 물어보세요", { exact: true }).waitFor();
  assert.equal(await page.locator(".chatbot__message").count(), 0); await page.close();
});




async function screenshot(page, name) {
  const directory = process.env.CHATBOT_SCREENSHOT_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: `${directory}/${name}.png` });
}

test("drafts remain editable while running; retry preserves a separate draft and Enter respects IME", async () => {
  reset(); const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await open(page);
  await screenshot(page, "chatbot-windows-welcome");
  const input = page.getByLabel("질문", { exact: true });
  await input.fill("매물 질문");
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true, bubbles: true });
  assert.equal(db.submissions.length, 0);
  await input.press("Shift+Enter");
  await input.press("B");
  assert.match(await input.inputValue(), /\nB$/);
  await input.press("Enter");
  await page.getByText("검색 조건 해석 중", { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.id === "chatbot-question" && !document.querySelector("#chatbot-question").disabled);
  await input.fill("이번 달 만기 일정 보기");
  await input.press("Enter");
  assert.equal(db.submissions.length, 1);
  assert.equal(await page.getByRole("button", { name: "전송", exact: true }).isDisabled(), true);
  await screenshot(page, "chatbot-windows-running");
  await page.getByRole("button", { name: "요청 중지", exact: true }).click();
  await page.getByText("요청을 중지했어요.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "이 질문 다시 시도", exact: true }).click();
  await page.getByText("검색 조건 해석 중", { exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector("#chatbot-question").disabled);
  assert.equal(await input.inputValue(), "이번 달 만기 일정 보기");
  assert.equal(db.submissions[1].question, db.submissions[0].question);
  complete();
  await page.getByText("전체 11건", { exact: false }).waitFor();
  assert.equal(await input.inputValue(), "이번 달 만기 일정 보기");
  assert.equal(await page.getByRole("button", { name: "전송", exact: true }).isEnabled(), true);
  await screenshot(page, "chatbot-windows-results");
  await page.close();
});

test("older history preserves the visible message and incoming answers never pull a reader down", async () => {
  reset(); db.historyPageSize = 20;
  db.request = request(); db.conversation = conversation(db.request);
  db.messages = Array.from({ length: 40 }, (_, index) => ({ id: index + 1, sequence_no: index + 1, request_id: db.request.id, role: index % 2 ? "assistant" : "user", content: `합성 대화 ${index + 1}\n조건을 확인하고 장부에서 원하는 대상을 찾아보세요.`, result_payload: null, created_at: date }));
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); await open(page);
  await page.locator('[data-message-id="40"]').waitFor();
  const history = page.getByLabel("대화 이력", { exact: true });
  await history.evaluate((element) => { element.scrollTop = 0; });
  await page.getByRole("button", { name: "최신 대화로 이동" }).waitFor();
  const position = async () => page.locator('[data-message-id="21"]').evaluate((element) => element.getBoundingClientRect().top - element.closest(".chatbot__history").getBoundingClientRect().top);
  const before = await position();
  await page.getByRole("button", { name: "이전 대화 이력 보기" }).click();
  await page.locator('[data-message-id="1"]').waitFor();
  assert.ok(Math.abs((await position()) - before) < 3, "prepending history must preserve the same visible message");
  await waitForOpenStream(); complete();
  await page.getByText("전체 11건", { exact: false }).waitFor();
  assert.ok(Math.abs((await position()) - before) < 3, "a new answer must not move a reader of old messages");
  await screenshot(page, "chatbot-windows-history");
  await page.getByRole("button", { name: "최신 대화로 이동" }).click();
  await page.waitForFunction(() => {
    const element = document.querySelector(".chatbot__history");
    return element.scrollHeight - element.scrollTop - element.clientHeight < 2;
  });
  assert.equal(await inputFocus(page), true);
  await page.close();
});
async function inputFocus(page) { return page.evaluate(() => document.activeElement?.id === "chatbot-question"); }

test("small viewports retain an accessible composer and readable conversation", async () => {
  for (const viewport of [{ width: 360, height: 740 }, { width: 720, height: 500 }]) {
    reset(); const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
    await open(page);
    const input = page.getByLabel("질문", { exact: true });
    const bounds = await input.boundingBox();
    const history = await page.getByLabel("대화 이력", { exact: true }).boundingBox();
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= viewport.height);
    assert.ok(history.height >= 80);
    assert.equal(await page.getByLabel("대화 이력", { exact: true }).evaluate((element) => element.scrollTop), 0, "welcome opens at the introduction");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await screenshot(page, `chatbot-windows-${viewport.width}`);
    await input.press("Escape");
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label")?.startsWith("업무 챗봇 열기"));
    await page.close();
  }
});

test("chat opens as a full-height right overlay without shifting the main content", async () => {
  for (const viewport of [{ width: 1366, height: 768 }, { width: 1920, height: 1080 }, { width: 360, height: 740 }]) {
    reset(); const page = await browser.newPage({ viewport });
    await page.goto(`${baseUrl}tests/fixtures/chatbot.html`);
    const mainTitle = page.getByRole("heading", { level: 1 });
    const before = await mainTitle.boundingBox();
    await page.getByRole("button", { name: /^업무 챗봇 열기/ }).click();
    const panel = page.getByRole("region", { name: "업무 챗봇", exact: true });
    const box = await panel.boundingBox();
    assert.equal(box.y, 0);
    assert.equal(box.height, viewport.height);
    assert.equal(box.x + box.width, viewport.width);
    const expectedWidth = viewport.width < 768 ? viewport.width : Math.min(768, Math.max(576, viewport.width * 0.45)) * 0.8;
    assert.ok(Math.abs(box.width - expectedWidth) < 1, "desktop panel is 20% narrower; mobile remains full width");
    assert.deepEqual(await mainTitle.boundingBox(), before, "opening chat must not resize or move the main layout");
    assert.equal(await page.locator(".chatbot__trigger").isVisible(), false);
    await screenshot(page, `chatbot-sidebar-${viewport.width}`);
    await page.getByRole("button", { name: "업무 챗봇 접기", exact: true }).click();
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label")?.startsWith("업무 챗봇 열기"));
    assert.deepEqual(await mainTitle.boundingBox(), before);
    await page.close();
  }
});

test("header help contains storage guidance and the compact composer grows then resets", async () => {
  reset(); const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  await open(page);
  const input = page.getByLabel("질문", { exact: true });
  const initial = await input.boundingBox();
  assert.ok((await page.locator(".chatbot__footer").boundingBox()).height < 150);
  await page.getByRole("button", { name: "대화 도움말" }).click();
  await page.getByText("질문과 답변은 저장되며", { exact: false }).waitFor();
  await page.keyboard.press("Escape");
  await page.getByText("질문과 답변은 저장되며", { exact: false }).waitFor({ state: "hidden" });
  assert.equal(await page.locator("#chatbot-panel").isVisible(), true);
  await input.fill("첫 줄\n둘째 줄\n셋째 줄\n넷째 줄");
  assert.ok((await input.boundingBox()).height > initial.height);
  await input.fill("");
  assert.equal((await input.boundingBox()).height, initial.height);
  await send(page); complete();
  await page.getByText("전체 11건", { exact: false }).waitFor();
  await page.getByRole("button", { name: "대화 도움말" }).click();
  await page.locator(".chatbot__help-content").getByText("답변을 저장했어요.", { exact: true }).waitFor();
  await screenshot(page, "chatbot-composer-help");
  await page.getByRole("button", { name: "도움말 닫기" }).click();
  assert.equal(await page.locator("#chatbot-panel").isVisible(), true);
  await screenshot(page, "chatbot-compact-composer");
  await page.close();
});
