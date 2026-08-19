import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {
  REVIEW_MARKER,
  addRedactionFinding,
  applyLimits,
  buildReviewContext,
  chunkText,
  discordPayload,
  extractResponseText,
  fetchWithRetry,
  findCheckRun,
  findReviewComment,
  isInternalPullRequest,
  normalizeReview,
  planForEvent,
  renderDiscordReviewMessages,
  renderGitHubComment,
  selectPolicyPaths
} from "../pr-review-lib.mjs";

const rootDir = process.cwd();
const event = JSON.parse(
  await readFile(
    path.join(rootDir, ".github/scripts/tests/fixtures/pull-request.json"),
    "utf8"
  )
);
const policy = JSON.parse(
  await readFile(path.join(rootDir, ".github/pr-review-policy.json"), "utf8")
);
const pr = event.pull_request;

test("same-repository PR is trusted for the base workflow", () => {
  assert.equal(
    isInternalPullRequest(pr, "SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team"),
    true
  );
  assert.equal(isInternalPullRequest(pr, "someone/fork"), false);
});

test("draft and lifecycle events route correctly", () => {
  assert.deepEqual(planForEvent({ eventName: "pull_request_target", action: "opened", pr }), {
    notifyCreated: true,
    notifyClosed: false,
    review: true,
    reason: "opened"
  });
  assert.equal(
    planForEvent({
      eventName: "pull_request_target",
      action: "opened",
      pr: { ...pr, draft: true }
    }).review,
    false
  );
  assert.equal(
    planForEvent({ eventName: "pull_request_target", action: "closed", pr }).notifyClosed,
    true
  );
});

test("changed paths select only applicable module policies", async () => {
  const selected = await selectPolicyPaths(
    ["ai/src/brokerage_ai/runtime.py", "backend/src/main.py"],
    policy,
    rootDir
  );
  assert.deepEqual(selected.modules, ["backend", "ai"]);
  assert.equal(selected.projectWide, true);
  assert.ok(selected.paths.includes(".agents/skills/ai/SKILL.md"));
  assert.ok(selected.paths.includes(".agents/skills/backend/SKILL.md"));
  assert.ok(
    selected.paths.includes(
      ".agents/skills/project-wiki/references/decisions/ADR-0006-ai-backend-boundary.md"
    )
  );
  assert.equal(selected.paths.includes(".agents/skills/frontend/SKILL.md"), false);
});

test("secret-like patch lines are redacted before context leaves the runner", async () => {
  const context = await buildReviewContext({
    rootDir,
    pr,
    files: [
      {
        filename: "ai/example.py",
        status: "modified",
        additions: 1,
        deletions: 0,
        patch: '@@ -1 +1 @@\n+OPENAI_API_KEY="sk-proj-abcdefghijklmnopqrstuvwxyz"'
      }
    ],
    policy,
    limits: { ...policy.limits, maxContextChars: 500000 }
  });
  assert.equal(context.redactionCount, 1);
  assert.deepEqual(context.redactedFiles, ["ai/example.py"]);
  assert.match(context.text, /\[REDACTED SECRET-LIKE LINE\]/);
  assert.doesNotMatch(context.text, /sk-proj-abcdefghijklmnopqrstuvwxyz/);
});

test("file and changed-line limits reject oversized PRs", () => {
  const files = Array.from({ length: 3 }, (_, index) => ({
    filename: `file-${index}.js`,
    additions: 10,
    deletions: 10
  }));
  const result = applyLimits(files, {
    maxFiles: 2,
    maxChangedLines: 50,
    maxContextChars: 1000
  });
  assert.equal(result.accepted, false);
  assert.equal(result.changedLines, 60);
  assert.equal(result.reasons.length, 2);
});

test("structured review output is validated and capped", () => {
  const finding = {
    severity: "high",
    category: "architecture",
    title: "경계 위반",
    file: "backend/src/main.py",
    line: 10,
    evidence: "backend가 LangGraph를 직접 import합니다.",
    rule_source: ".agents/skills/ai/SKILL.md",
    impact: "모듈 경계가 깨집니다.",
    recommendation: "AI facade를 사용하십시오."
  };
  const review = normalizeReview(
    {
      status: "needs_attention",
      summary: "수정이 필요합니다.",
      findings: Array.from({ length: 12 }, () => finding),
      missing_evidence: []
    },
    10
  );
  assert.equal(review.findings.length, 10);
  const inconsistent = normalizeReview({
    status: "clean",
    summary: "clean",
    findings: [finding],
    missing_evidence: []
  });
  assert.equal(inconsistent.status, "needs_attention");
  const sanitized = normalizeReview({
    status: "clean",
    summary: "sk-proj-abcdefghijklmnopqrstuvwxyz",
    findings: [],
    missing_evidence: []
  });
  assert.match(sanitized.summary, /REDACTED/);
  assert.doesNotMatch(sanitized.summary, /sk-proj-/);
  assert.throws(
    () => normalizeReview({ status: "unknown", summary: "", findings: [] }),
    /invalid status/
  );
});

test("OpenAI refusal and missing output are rejected", () => {
  assert.throws(
    () => extractResponseText({ output: [{ content: [{ type: "refusal", refusal: "policy" }] }] }),
    /refused/
  );
  assert.throws(() => extractResponseText({ output: [] }), /did not contain output text/);
});

test("redaction finding never includes the detected value", () => {
  const review = addRedactionFinding(
    { status: "clean", summary: "clean", findings: [], missing_evidence: [] },
    ["ai/.env"]
  );
  assert.equal(review.status, "needs_attention");
  assert.equal(review.findings[0].severity, "high");
  assert.doesNotMatch(JSON.stringify(review), /sk-proj-/);
});

test("GitHub output is sticky and Discord output is bounded", () => {
  const review = {
    status: "needs_attention",
    summary: "정책 검토 결과입니다.",
    findings: [
      {
        severity: "high",
        category: "architecture",
        title: "경계 위반",
        file: "backend/src/main.py",
        line: 10,
        evidence: "직접 의존합니다.",
        rule_source: ".agents/skills/ai/SKILL.md",
        impact: "결합도가 증가합니다.",
        recommendation: "공개 facade를 사용하십시오."
      }
    ],
    missing_evidence: []
  };
  const comment = renderGitHubComment({
    pr,
    review,
    model: "gpt-5.6-terra",
    usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    durationMs: 1200,
    context: { modules: ["backend"] }
  });
  assert.ok(comment.startsWith(REVIEW_MARKER));
  const messages = renderDiscordReviewMessages({
    pr,
    review,
    model: "gpt-5.6-terra",
    usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    durationMs: 1200,
    modules: ["backend"],
    runUrl: "https://github.com/example/actions/runs/1"
  });
  assert.ok(messages.length >= 3);
  assert.ok(messages.every((message) => message.length <= 1800));
  assert.deepEqual(discordPayload("@everyone test").allowed_mentions, { parse: [] });
});

test("sticky resources only select GitHub-owned records", () => {
  const userMarker = { id: 1, user: { type: "User" }, body: REVIEW_MARKER };
  const botMarker = { id: 2, user: { type: "Bot" }, body: REVIEW_MARKER };
  assert.equal(findReviewComment([userMarker, botMarker]).id, 2);

  const foreignCheck = { id: 3, name: "PR Policy Agent", app: { slug: "other-app" } };
  const actionsCheck = { id: 4, name: "PR Policy Agent", app: { slug: "github-actions" } };
  assert.equal(findCheckRun([foreignCheck, actionsCheck]).id, 4);
});

test("missing patches are reported as unavailable evidence", async () => {
  const context = await buildReviewContext({
    rootDir,
    pr,
    files: [{ filename: "backend/large.py", status: "modified", additions: 1, deletions: 0 }],
    policy,
    limits: { ...policy.limits, maxContextChars: 500000 }
  });
  assert.deepEqual(context.missingPatches, ["backend/large.py"]);
});

test("chunking preserves content within Discord limits", () => {
  const input = `${"a".repeat(900)}\n\n${"b".repeat(900)}`;
  const chunks = chunkText(input, 1000);
  assert.deepEqual(chunks.map((chunk) => chunk.length), [900, 900]);
});

test("transient HTTP responses honor retry behavior", async () => {
  let calls = 0;
  const waits = [];
  const response = await fetchWithRetry(
    "https://example.invalid",
    {},
    {
      attempts: 3,
      sleep: async (milliseconds) => waits.push(milliseconds),
      fetchImpl: async () => {
        calls += 1;
        if (calls === 1) {
          return new Response("rate limited", {
            status: 429,
            headers: { "retry-after": "0.25" }
          });
        }
        return new Response("ok", { status: 200 });
      }
    }
  );
  assert.equal(response.status, 200);
  assert.equal(calls, 2);
  assert.deepEqual(waits, [250]);
});

test("transient 5xx responses are retried", async () => {
  let calls = 0;
  const response = await fetchWithRetry(
    "https://example.invalid",
    {},
    {
      attempts: 3,
      sleep: async () => {},
      fetchImpl: async () => {
        calls += 1;
        return calls === 1
          ? new Response("unavailable", { status: 503 })
          : new Response("ok", { status: 200 });
      }
    }
  );
  assert.equal(response.status, 200);
  assert.equal(calls, 2);
});

test("non-retryable HTTP responses fail once", async () => {
  let calls = 0;
  await assert.rejects(
    fetchWithRetry(
      "https://example.invalid",
      {},
      {
        attempts: 3,
        sleep: async () => {},
        fetchImpl: async () => {
          calls += 1;
          return new Response("bad request", { status: 400 });
        }
      }
    ),
    /HTTP 400/
  );
  assert.equal(calls, 1);
});
