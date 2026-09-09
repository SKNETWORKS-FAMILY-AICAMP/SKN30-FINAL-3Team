import assert from "node:assert/strict";
import test from "node:test";
import {
  MERGED_REVIEW_SCHEMA,
  REVIEW_MARKER,
  addRedactionFinding,
  applyLimits,
  buildOpenAIRequest,
  discordPayload,
  estimateOpenAICost,
  extractResponseText,
  findCheckRun,
  findReviewComment,
  normalizeMergedReview,
  normalizeReview,
  renderDiscordReviewMessages,
  renderGitHubComment
} from "../pr-review-lib.mjs";
import { policy, pr } from "./fixtures/pr-review.mjs";

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
  assert.equal(first.service_tier, "default");
  assert.equal(first.max_output_tokens, 2500);
  assert.ok(first.prompt_cache_key.length <= 64);
});

test("standard-tier model usage is converted to an auditable estimated cost", () => {
  const estimated = estimateOpenAICost(
    [
      {
        model: "gpt-5.6-luna",
        usage: {
          input_tokens: 100000,
          output_tokens: 2500,
          input_tokens_details: { cached_tokens: 20000, cache_write_tokens: 30000 }
        }
      }
    ],
    policy.cost
  );
  assert.equal(estimated.complete, true);
  assert.equal(estimated.longContextCalls, 0);
  assert.ok(Math.abs(estimated.estimatedCost - 0.0209) < 1e-12);

  const longContext = estimateOpenAICost(
    [{ model: "gpt-5.6-terra", usage: { input_tokens: 300000, output_tokens: 4000 } }],
    policy.cost
  );
  assert.equal(longContext.longContextCalls, 1);
  assert.ok(Math.abs(longContext.estimatedCost - 1.272) < 1e-12);
  assert.equal(
    estimateOpenAICost(
      [{ model: "unpriced-model", usage: { input_tokens: 1, output_tokens: 1 } }],
      policy.cost
    ).complete,
    false
  );
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
  assert.equal(review.findings.length, 1);
  const prioritized = normalizeReview(
    {
      status: "needs_attention",
      summary: "우선순위 검증",
      findings: [
        {
          ...finding,
          severity: "medium",
          root_cause: "medium-a",
          title: "medium a",
          file: "backend/medium-a.py"
        },
        {
          ...finding,
          severity: "medium",
          root_cause: "medium-b",
          title: "medium b",
          file: "backend/medium-b.py"
        },
        { ...finding, root_cause: "high-a", title: "high a", file: "backend/high-a.py" },
        {
          ...finding,
          severity: "critical",
          root_cause: "critical-a",
          title: "critical a",
          file: "backend/critical-a.py"
        }
      ],
      missing_evidence: []
    },
    3
  );
  assert.deepEqual(
    prioritized.findings.map((item) => item.severity),
    ["critical", "high", "medium"]
  );
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
  const merged = normalizeMergedReview({
    status: "clean",
    summary: "교차 검증 완료",
    findings: [],
    missing_evidence: [],
    dismissed_findings: [
      {
        root_cause: "partial-diff-absence",
        reason: "전체 파일에서 기존 규칙을 확인했습니다.",
        evidence: ".gitignore PR head 전체 파일"
      }
    ]
  });
  assert.equal(merged.dismissed_findings[0].root_cause, "partial-diff-absence");
  assert.ok(MERGED_REVIEW_SCHEMA.required.includes("dismissed_findings"));
  assert.throws(
    () =>
      normalizeMergedReview({
        status: "clean",
        summary: "누락",
        findings: [],
        missing_evidence: []
      }),
    /missing dismissed_findings/
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
    missing_evidence: [],
    dismissed_findings: [
      {
        root_cause: "partial-diff-absence",
        reason: "전체 파일에서 기존 설정을 확인했습니다.",
        evidence: ".gitignore PR head 전체 파일"
      }
    ]
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
    costEstimate: {
      complete: true,
      currency: "USD",
      estimatedCost: 0.012345,
      longContextCalls: 0,
      unpricedModels: []
    },
    durationMs: 1200,
    context: {
      modules: ["backend"],
      policyPackIds: ["backend-core"],
      reviewMode: "single",
      chunkCount: 1,
      arbiterRequired: true
    }
  });
  assert.ok(comment.startsWith(REVIEW_MARKER));
  assert.match(comment, /HIGH · 병합 전 확인/);
  assert.match(comment, /cache read 60 \/ write 10/);
  assert.match(comment, /backend-core/);
  assert.match(comment, /단일 리뷰 \+ 정책 중재/);
  assert.match(comment, /USD 0\.012345/);
  assert.match(comment, /교차 검증으로 제외한 부분 리뷰 finding/);
  assert.match(comment, /partial-diff-absence/);
  assert.match(comment, /전체 파일에서 기존 설정을 확인/);
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
  assert.match(messages[0], /교차 검증 제외: 1/);
  assert.ok(messages.every((message) => message.length <= 1800));
  assert.deepEqual(discordPayload("@everyone test").allowed_mentions, { parse: [] });
});

test("GitHub output remains publishable while preserving the maximum leaf critical set", () => {
  const findings = Array.from({ length: 30 }, (_, index) => ({
    severity: "critical",
    root_cause: `critical-root-${index}`,
    category: "security".repeat(8),
    title: `critical ${index} ${"제목".repeat(80)}`,
    file: `backend/${"deep/".repeat(100)}file-${index}.py`,
    line: index + 1,
    evidence: "근거".repeat(500),
    rule_source: "AGENTS.md ".repeat(50),
    impact: "영향".repeat(400),
    recommendation: "권고".repeat(500)
  }));
  const comment = renderGitHubComment({
    pr,
    review: {
      status: "needs_attention",
      summary: "요약".repeat(600),
      findings,
      dismissed_findings: [],
      missing_evidence: Array.from({ length: 10 }, () => "누락".repeat(250))
    },
    model: "gpt-5.6-terra",
    usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    durationMs: 1200,
    context: { modules: ["backend"], reviewMode: "multi", chunkCount: 10 }
  });

  assert.equal((comment.match(/CRITICAL · 즉시 확인/g) ?? []).length, 35);
  assert.ok(Buffer.byteLength(comment, "utf8") < 60000);
});

test("sticky resources only select GitHub-owned records", () => {
  const userMarker = { id: 1, user: { type: "User" }, body: REVIEW_MARKER };
  const botMarker = { id: 2, user: { type: "Bot" }, body: REVIEW_MARKER };
  assert.equal(findReviewComment([userMarker, botMarker]).id, 2);

  const foreignCheck = { id: 3, name: "PR Policy Agent", app: { slug: "other-app" } };
  const actionsCheck = { id: 4, name: "PR Policy Agent", app: { slug: "github-actions" } };
  assert.equal(findCheckRun([foreignCheck, actionsCheck]).id, 4);
});
