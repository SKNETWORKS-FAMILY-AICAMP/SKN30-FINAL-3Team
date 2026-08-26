import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { buildPrCommentNotification } from "../pr-comment-discord-lib.mjs";

const pullRequest = {
  number: 17,
  title: "feat: 댓글 알림 추가",
  html_url: "https://github.com/example/repo/pull/17"
};

test("formats a human conversation comment and disables Discord mentions", () => {
  const notification = buildPrCommentNotification("issue_comment", {
    issue: { ...pullRequest, pull_request: { url: "https://api.github.com/pulls/17" } },
    comment: {
      body: "@everyone CSRF 처리 방식을 확인해 주세요.",
      html_url: "https://github.com/example/repo/pull/17#issuecomment-1",
      user: { login: "reviewer", type: "User" }
    }
  });

  assert.match(notification.content, /PR 일반 댓글/);
  assert.match(notification.content, /reviewer/);
  assert.match(notification.content, /CSRF 처리 방식/);
  assert.equal(notification.payload.allowed_mentions.parse.length, 0);
});

test("ignores issue comments that are not attached to pull requests", () => {
  const notification = buildPrCommentNotification("issue_comment", {
    issue: { number: 3, title: "일반 이슈" },
    comment: { body: "이슈 댓글", user: { login: "reviewer", type: "User" } }
  });
  assert.equal(notification, null);
});

test("ignores bot comments to avoid duplicating PR Policy Agent notifications", () => {
  const notification = buildPrCommentNotification("issue_comment", {
    issue: { ...pullRequest, pull_request: {} },
    comment: {
      body: "자동 리뷰 결과",
      user: { login: "github-actions[bot]", type: "Bot" }
    }
  });
  assert.equal(notification, null);
});

test("formats approvals and change requests without requiring a review body", () => {
  const approved = buildPrCommentNotification("pull_request_review", {
    pull_request: pullRequest,
    review: {
      state: "approved",
      body: "",
      html_url: "https://github.com/example/repo/pull/17#pullrequestreview-1",
      user: { login: "Hong1008", type: "User" }
    }
  });
  const changesRequested = buildPrCommentNotification("pull_request_review", {
    pull_request: pullRequest,
    review: {
      state: "changes_requested",
      body: "테스트 결과를 추가해 주세요.",
      user: { login: "Hong1008", type: "User" }
    }
  });

  assert.match(approved.content, /PR 승인/);
  assert.doesNotMatch(approved.content, /내용:/);
  assert.match(changesRequested.content, /PR 변경 요청/);
});

test("includes inline file location and redacts secret-like comment lines", () => {
  const notification = buildPrCommentNotification("pull_request_review_comment", {
    pull_request: pullRequest,
    comment: {
      path: "backend/src/api.py",
      line: 42,
      body: 'OPENAI_API_KEY="sk-proj-abcdefghijklmnopqrstuvwxyz"',
      html_url: "https://github.com/example/repo/pull/17#discussion_r1",
      user: { login: "reviewer", type: "User" }
    }
  });

  assert.ok(notification.content.includes("backend/src/api.py:42"));
  assert.match(notification.content, /REDACTED SECRET-LIKE LINE/);
  assert.doesNotMatch(notification.content, /sk-proj-/);
});

test("limits the comment preview length", () => {
  const notification = buildPrCommentNotification("issue_comment", {
    issue: { ...pullRequest, pull_request: {} },
    comment: {
      body: "가".repeat(400),
      user: { login: "reviewer", type: "User" }
    }
  });
  const preview = notification.content.split("내용: ")[1].split("\n")[0];
  assert.ok(Array.from(preview).length <= 240);
  assert.ok(preview.endsWith("…"));
});

test("workflow subscribes to all three PR collaboration event families", async () => {
  const workflow = await readFile(".github/workflows/pr-comment-discord.yml", "utf8");
  assert.match(workflow, /issue_comment:/);
  assert.match(workflow, /pull_request_review:/);
  assert.match(workflow, /pull_request_review_comment:/);
  assert.match(workflow, /github\.event\.sender\.type != 'Bot'/);
  assert.doesNotMatch(workflow, /pull_request_target:/);
});
