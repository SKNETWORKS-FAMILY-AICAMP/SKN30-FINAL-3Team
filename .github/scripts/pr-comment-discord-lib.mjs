import { discordPayload, redactSecrets } from "./pr-review-lib.mjs";

const COMMENT_SNIPPET_LIMIT = 240;
const TITLE_LIMIT = 180;

function truncate(value, maxLength) {
  const characters = Array.from(String(value ?? ""));
  if (characters.length <= maxLength) return characters.join("");
  return `${characters.slice(0, Math.max(0, maxLength - 1)).join("")}…`;
}

function escapeDiscordMarkdown(value) {
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/([\\`*_~|>])/g, "\\$1")
    .replace(/\s+/g, " ")
    .trim();
}

function isBot(actor) {
  const login = String(actor?.login ?? "");
  return actor?.type === "Bot" || login.toLowerCase().endsWith("[bot]");
}

function commentSnippet(body) {
  const redacted = redactSecrets(body ?? "").text;
  const withoutHtmlComments = redacted.replace(/<!--[\s\S]*?-->/g, " ");
  const normalized = escapeDiscordMarkdown(withoutHtmlComments);
  return normalized ? truncate(normalized, COMMENT_SNIPPET_LIMIT) : "";
}

function locationText(comment) {
  const filePath = escapeDiscordMarkdown(comment?.path ?? "");
  if (!filePath) return "";
  const line = comment?.line ?? comment?.original_line;
  return line ? `${filePath}:${line}` : filePath;
}

function reviewLabel(state) {
  const normalized = String(state ?? "").toLowerCase();
  if (normalized === "approved") return { heading: "✅ **PR 승인**", type: "승인" };
  if (normalized === "changes_requested") {
    return { heading: "🚧 **PR 변경 요청**", type: "변경 요청" };
  }
  if (normalized === "dismissed") return { heading: "↩️ **PR 리뷰 취소**", type: "리뷰 취소" };
  return { heading: "📝 **PR 리뷰**", type: "리뷰" };
}

function eventDetails(eventName, event) {
  if (eventName === "issue_comment") {
    if (!event.issue?.pull_request) return null;
    return {
      heading: "💬 **PR 일반 댓글**",
      type: "일반 댓글",
      pr: event.issue,
      actor: event.comment?.user ?? event.sender,
      body: event.comment?.body,
      url: event.comment?.html_url ?? event.issue?.html_url,
      location: ""
    };
  }

  if (eventName === "pull_request_review") {
    const label = reviewLabel(event.review?.state);
    return {
      heading: label.heading,
      type: label.type,
      pr: event.pull_request,
      actor: event.review?.user ?? event.sender,
      body: event.review?.body,
      url: event.review?.html_url ?? event.pull_request?.html_url,
      location: ""
    };
  }

  if (eventName === "pull_request_review_comment") {
    return {
      heading: "🧵 **PR 코드 댓글**",
      type: "코드 댓글",
      pr: event.pull_request,
      actor: event.comment?.user ?? event.sender,
      body: event.comment?.body,
      url: event.comment?.html_url ?? event.pull_request?.html_url,
      location: locationText(event.comment)
    };
  }

  return null;
}

export function buildPrCommentNotification(eventName, event) {
  const details = eventDetails(eventName, event);
  if (!details || isBot(details.actor)) return null;

  const prNumber = Number(details.pr?.number);
  const title = truncate(escapeDiscordMarkdown(details.pr?.title ?? "제목 없음"), TITLE_LIMIT);
  const login = escapeDiscordMarkdown(details.actor?.login ?? "unknown");
  const snippet = commentSnippet(details.body);
  const url = String(details.url ?? details.pr?.html_url ?? "").trim();
  const lines = [
    details.heading,
    `PR #${Number.isInteger(prNumber) ? prNumber : "?"} ${title}`,
    `작성자: \`${login}\` · 유형: ${details.type}`
  ];

  if (details.location) lines.push(`위치: \`${details.location}\``);
  if (snippet) lines.push(`내용: ${snippet}`);
  if (url) lines.push(`바로가기: ${url}`);

  return {
    content: lines.join("\n"),
    payload: discordPayload(lines.join("\n")),
    prNumber: Number.isInteger(prNumber) ? prNumber : null,
    type: details.type
  };
}
