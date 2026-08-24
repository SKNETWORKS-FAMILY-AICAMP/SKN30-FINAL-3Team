import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {
  REVIEW_MARKER,
  addRedactionFinding,
  applyLimits,
  attachReviewState,
  buildMergeContext,
  buildOpenAIRequest,
  buildReviewContext,
  chunkText,
  discordPayload,
  extractResponseText,
  fetchWithRetry,
  findCheckRun,
  findReviewComment,
  hasProjectWideChange,
  isInternalPullRequest,
  isPatchIncomplete,
  isReusableReviewState,
  mapWithConcurrency,
  mergeReviewsFallback,
  normalizeReview,
  parseReviewState,
  patchChangedLines,
  planForEvent,
  planReviewChunks,
  reconcileMergedReview,
  reviewChunkFingerprint,
  renderDiscordReviewMessages,
  renderGitHubComment,
  selectPolicyPaths,
  stableObjectHash,
  stripReviewState,
  sumUsage
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
  assert.equal(
    planForEvent({
      eventName: "pull_request_target",
      action: "closed",
      pr: { ...pr, draft: true }
    }).notifyClosed,
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
  assert.match(context.cachePrefixText, /^<accepted_policy>/);
  assert.match(context.dynamicText, /^<pull_request/);
  assert.doesNotMatch(context.dynamicText, /<accepted_policy>/);
  assert.match(context.text, /\[REDACTED SECRET-LIKE LINE\]/);
  assert.doesNotMatch(context.text, /sk-proj-abcdefghijklmnopqrstuvwxyz/);
});

test("GPT-5.6 requests cache only the stable policy prefix", () => {
  const base = {
    model: "gpt-5.6-luna",
    instructions: "stable instructions",
    cachePrefixText: "<accepted_policy>stable policy</accepted_policy>",
    dynamicText: "<pull_request head_sha=\"one\">changed patch</pull_request>",
    taskInstruction: "review chunk",
    reasoningEffort: "low",
    verbosity: "low",
    schemaName: "pr_policy_chunk_review",
    maxOutputTokens: 2500,
    safetyIdentifier: "safe"
  };
  const first = buildOpenAIRequest(base);
  const second = buildOpenAIRequest({
    ...base,
    dynamicText: "<pull_request head_sha=\"two\">new patch</pull_request>"
  });
  assert.equal(first.prompt_cache_key, second.prompt_cache_key);
  assert.deepEqual(first.prompt_cache_options, { mode: "explicit", ttl: "30m" });
  assert.deepEqual(first.input[0].content[0].prompt_cache_breakpoint, { mode: "explicit" });
  assert.match(first.input[0].content[0].text, /stable policy/);
  assert.doesNotMatch(first.input[0].content[0].text, /changed patch/);
  assert.match(first.input[1].content[0].text, /changed patch/);
  assert.equal(first.store, false);
  assert.equal(first.max_output_tokens, 2500);
  assert.ok(first.prompt_cache_key.length <= 64);
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

test("review publication limits favor a short actionable result", () => {
  assert.equal(policy.limits.chunkMaxFindings, 3);
  assert.equal(policy.limits.maxFindings, 5);
  assert.equal(policy.limits.leafMaxOutputTokens, 2500);
  assert.equal(policy.limits.mergeMaxOutputTokens, 4000);
});

test("structured review output is validated and capped", () => {
  const finding = {
    severity: "high",
    root_cause: "architecture-boundary",
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
    5
  );
  assert.equal(review.findings.length, 5);
  const inconsistent = normalizeReview({
    status: "clean",
    summary: "clean",
    findings: [finding],
    missing_evidence: []
  });
  assert.equal(inconsistent.status, "needs_attention");
  const modelReportedGap = normalizeReview({
    status: "incomplete",
    summary: "insufficient",
    findings: [],
    missing_evidence: ["patch missing"]
  });
  assert.equal(modelReportedGap.status, "clean");
  assert.deepEqual(modelReportedGap.missing_evidence, []);
  const lowOnly = normalizeReview({
    status: "needs_attention",
    summary: "style",
    findings: [{ ...finding, severity: "low" }],
    missing_evidence: []
  });
  assert.equal(lowOnly.status, "clean");
  assert.deepEqual(lowOnly.findings, []);
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
        root_cause: "architecture-boundary",
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
    usage: {
      input_tokens: 100,
      output_tokens: 20,
      total_tokens: 120,
      input_tokens_details: { cached_tokens: 60, cache_write_tokens: 10 }
    },
    durationMs: 1200,
    context: { modules: ["backend"] }
  });
  assert.ok(comment.startsWith(REVIEW_MARKER));
  assert.match(comment, /HIGH · 병합 전 확인/);
  assert.match(comment, /cache read 60 \/ write 10/);
  const mediumComment = renderGitHubComment({
    pr,
    review: { ...review, findings: [{ ...review.findings[0], severity: "medium" }] },
    model: "gpt-5.6-terra",
    usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    durationMs: 1200,
    context: { modules: ["backend"] }
  });
  assert.match(mediumComment, /MEDIUM · 개선 권고/);
  const messages = renderDiscordReviewMessages({
    pr,
    review,
    model: "gpt-5.6-terra",
    usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    durationMs: 1200,
    modules: ["backend"],
    runUrl: "https://github.com/example/actions/runs/1"
  });
  assert.ok(messages.length >= 2);
  assert.ok(messages[0].includes("리뷰 기록"));
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

test("incremental review state round-trips without storing raw patches", () => {
  const state = {
    version: 1,
    repository: "owner/repo",
    prNumber: 12,
    baseSha: "base",
    headSha: "head",
    configurationHash: "config",
    aggregateFingerprint: "aggregate",
    chunks: [
      {
        fingerprint: "chunk",
        model: "gpt-5.6-luna",
        review: { status: "clean", summary: "완료", findings: [], missing_evidence: [] }
      }
    ],
    finalReview: { status: "clean", summary: "완료", findings: [], missing_evidence: [] }
  };
  const attached = attachReviewState(`${REVIEW_MARKER}\nvisible`, state);
  assert.equal(attached.persisted, true);
  assert.deepEqual(parseReviewState(attached.body), state);
  assert.equal(stripReviewState(attached.body), `${REVIEW_MARKER}\nvisible`);
  assert.doesNotMatch(attached.body, /raw patch/);
  assert.equal(attachReviewState("x".repeat(100), state, 20).persisted, false);
  assert.equal(parseReviewState("<!-- pr-policy-state:v1:not-base64 -->"), null);
});

test("incremental state reuse requires the same base and configuration", () => {
  const state = {
    version: 1,
    repository: "owner/repo",
    prNumber: 12,
    baseSha: "base",
    configurationHash: "config",
    chunks: []
  };
  const expected = {
    repository: "owner/repo",
    prNumber: 12,
    baseSha: "base",
    configurationHash: "config"
  };
  assert.equal(isReusableReviewState(state, expected), true);
  assert.equal(isReusableReviewState(state, { ...expected, baseSha: "changed" }), false);
  assert.equal(isReusableReviewState(state, { ...expected, projectWideChanged: true }), false);
});

test("chunk fingerprints change with patch content and project-wide paths force a full review", () => {
  const chunk = {
    group: "backend",
    files: [
      {
        filename: "backend/a.py",
        status: "modified",
        additions: 1,
        deletions: 0,
        patch: "@@ -0,0 +1 @@\n+a"
      }
    ]
  };
  assert.equal(reviewChunkFingerprint(chunk), reviewChunkFingerprint(chunk));
  assert.notEqual(
    reviewChunkFingerprint(chunk),
    reviewChunkFingerprint({
      ...chunk,
      files: [{ ...chunk.files[0], patch: "@@ -0,0 +1 @@\n+b" }]
    })
  );
  assert.equal(hasProjectWideChange([{ filename: ".github/workflow.yml" }], policy), true);
  assert.equal(hasProjectWideChange([{ filename: "backend/a.py" }], policy), false);
  assert.equal(stableObjectHash({ b: 2, a: 1 }), stableObjectHash({ a: 1, b: 2 }));
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

test("large patches are split deterministically by review chunk limits", () => {
  const patch = `@@ -0,0 +1,6 @@\n${Array.from({ length: 6 }, (_, index) => `+line ${index + 1}`).join("\n")}`;
  assert.equal(patchChangedLines(patch), 6);
  assert.equal(patchChangedLines("@@ -1 +1 @@\n+++counter\n---value"), 2);
  const result = planReviewChunks(
    [{ filename: "backend/large.py", status: "modified", additions: 6, deletions: 0, patch }],
    policy,
    { chunkChangedLines: 2, chunkPatchChars: 10000, maxChunks: 10 }
  );
  assert.equal(result.accepted, true);
  assert.equal(result.chunks.length, 3);
  assert.deepEqual(result.chunks.map((chunk) => chunk.changedLines), [2, 2, 2]);
  assert.ok(result.chunks.every((chunk) => chunk.group === "backend"));
});

test("chunk plans preserve module boundaries and enforce their own cap", () => {
  const files = [
    { filename: "backend/a.py", additions: 1, deletions: 0, patch: "@@ -0,0 +1 @@\n+a" },
    { filename: "ai/b.py", additions: 1, deletions: 0, patch: "@@ -0,0 +1 @@\n+b" }
  ];
  const accepted = planReviewChunks(files, policy, {
    chunkChangedLines: 10,
    chunkPatchChars: 10000,
    maxChunks: 2
  });
  assert.deepEqual(accepted.chunks.map((chunk) => chunk.group), ["backend", "ai"]);
  assert.equal(accepted.accepted, true);
  const rejected = planReviewChunks(files, policy, {
    chunkChangedLines: 10,
    chunkPatchChars: 10000,
    maxChunks: 1
  });
  assert.equal(rejected.accepted, false);
  assert.match(rejected.reasons[0], /한도 1개/);
});

test("concurrent chunk execution is bounded and keeps result order", async () => {
  let active = 0;
  let maximum = 0;
  const result = await mapWithConcurrency([3, 2, 1, 0], 2, async (value) => {
    active += 1;
    maximum = Math.max(maximum, active);
    await new Promise((resolve) => setTimeout(resolve, value));
    active -= 1;
    return value * 2;
  });
  assert.deepEqual(result, [6, 4, 2, 0]);
  assert.equal(maximum, 2);
});

test("usage and fallback findings are merged deterministically", () => {
  assert.deepEqual(
    sumUsage([
      {
        input_tokens: 10,
        output_tokens: 2,
        total_tokens: 12,
        input_tokens_details: { cached_tokens: 4, cache_write_tokens: 2 }
      },
      {
        input_tokens: 20,
        output_tokens: 3,
        total_tokens: 23,
        input_tokens_details: { cached_tokens: 5, cache_write_tokens: 1 }
      }
    ]),
    {
      input_tokens: 30,
      output_tokens: 5,
      total_tokens: 35,
      input_tokens_details: { cached_tokens: 9, cache_write_tokens: 3 }
    }
  );
  const finding = {
    severity: "high",
    root_cause: "module-boundary-violation",
    category: "architecture",
    title: "경계 위반",
    file: "backend/a.py",
    line: 1,
    evidence: "직접 의존",
    rule_source: "AGENTS.md",
    impact: "결합",
    recommendation: "포트 사용"
  };
  const merged = mergeReviewsFallback(
    [
      { status: "needs_attention", summary: "a", findings: [finding], missing_evidence: [] },
      { status: "clean", summary: "b", findings: [{ ...finding, file: "ai/b.py", line: 2, rule_source: "architecture.md" }], missing_evidence: ["missing"] }
    ],
    10,
    { forceIncomplete: true }
  );
  assert.equal(merged.status, "incomplete");
  assert.equal(merged.findings.length, 1);
  assert.deepEqual(merged.missing_evidence, ["missing"]);
});

test("merge context contains inventory and summaries but not raw diff", async () => {
  const rawPatch = "@@ -0,0 +1 @@\n+DO_NOT_COPY_RAW_PATCH";
  const context = await buildMergeContext({
    rootDir,
    pr,
    files: [{ filename: "backend/a.py", status: "modified", additions: 1, deletions: 0, patch: rawPatch }],
    policy,
    limits: { ...policy.limits, maxMergeContextChars: 900000 },
    chunkResults: [
      {
        chunk_id: "backend-1",
        group: "backend",
        files: ["backend/a.py"],
        review: { status: "clean", summary: "검토 완료", findings: [], missing_evidence: [] }
      }
    ]
  });
  assert.equal(context.accepted, true);
  assert.match(context.text, /<changed_file_inventory>/);
  assert.match(context.text, /<chunk_reviews>/);
  assert.doesNotMatch(context.text, /DO_NOT_COPY_RAW_PATCH/);
});

test("truncated GitHub patches are treated as incomplete evidence", () => {
  assert.equal(
    isPatchIncomplete({ additions: 2, deletions: 0, patch: "@@ -0,0 +1 @@\n+only one" }),
    true
  );
});

test("final merge preserves high-severity leaf findings", () => {
  const leafFinding = {
    severity: "high",
    category: "security",
    title: "보존해야 하는 finding",
    file: "backend/security.py",
    line: 7,
    evidence: "권한 확대",
    rule_source: "AGENTS.md",
    impact: "과도한 접근",
    recommendation: "권한 축소"
  };
  const reconciled = reconcileMergedReview(
    { status: "clean", summary: "통합 결과", findings: [], missing_evidence: [] },
    [{ status: "needs_attention", summary: "부분 결과", findings: [leafFinding], missing_evidence: [] }],
    10
  );
  assert.equal(reconciled.status, "needs_attention");
  assert.deepEqual(reconciled.findings, [leafFinding]);
});
