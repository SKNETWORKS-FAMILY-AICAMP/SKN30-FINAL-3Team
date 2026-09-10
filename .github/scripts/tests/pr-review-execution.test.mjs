import assert from "node:assert/strict";
import test from "node:test";
import {
  REVIEW_MARKER,
  attachReviewState,
  buildReviewContext,
  chunkText,
  fetchWithRetry,
  fitReviewChunksToContext,
  hasProjectWideChange,
  isReusableReviewState,
  mapWithConcurrency,
  parseReviewState,
  patchChangedLines,
  planReviewChunks,
  reviewChunkFingerprint,
  stableObjectHash,
  stripReviewState
} from "../pr-review-lib.mjs";
import { rootDir, policy, pr } from "./fixtures/pr-review.mjs";

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
  assert.notEqual(
    reviewChunkFingerprint(chunk, "policy-evidence-a"),
    reviewChunkFingerprint(chunk, "policy-evidence-b")
  );
  assert.notEqual(
    reviewChunkFingerprint(chunk, "policy-evidence", "pr-metadata-a"),
    reviewChunkFingerprint(chunk, "policy-evidence", "pr-metadata-b")
  );
  assert.notEqual(
    reviewChunkFingerprint({
      ...chunk,
      files: [{ ...chunk.files[0], contextFragment: "0.1" }]
    }),
    reviewChunkFingerprint({
      ...chunk,
      files: [{ ...chunk.files[0], contextFragment: "0.2" }]
    })
  );
  assert.equal(hasProjectWideChange([{ filename: ".github/workflow.yml" }], policy), true);
  assert.equal(
    hasProjectWideChange(
      [{ filename: ".agents/skills/backend/references/decisions/ADR-0002.md" }],
      policy
    ),
    true
  );
  assert.equal(hasProjectWideChange([{ filename: ".gitignore" }], policy), true);
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

test("oversized single patch lines are split within the raw patch cap", () => {
  const result = planReviewChunks(
    [
      {
        filename: "infra/environments/dev/main.tf",
        status: "modified",
        additions: 1,
        deletions: 0,
        patch: `+${"x".repeat(500)}`
      }
    ],
    policy,
    { chunkChangedLines: 10, chunkPatchChars: 120, maxChunks: 10 }
  );
  assert.equal(result.accepted, true);
  assert.ok(result.chunks.length > 1);
  assert.ok(result.chunks.every((chunk) => chunk.patchChars <= 120));
  assert.equal(
    result.chunks.reduce((total, chunk) => total + chunk.changedLines, 0),
    1
  );
});

test("serialized frontend and infra contexts are re-split before review", async () => {
  const cases = [
    {
      filename: "frontend/src/Synthetic.tsx",
      row: "+<A><B><C><D></D></C></B></A>",
      count: 1800
    },
    {
      filename: "infra/environments/dev/main.tf",
      row: '+value = "<A><B><C><D><E><F><G></G></F></E></D></C></B></A>"',
      count: 900
    }
  ];
  for (const item of cases) {
    const patch = Array.from({ length: item.count }, () => item.row).join("\n");
    const initial = planReviewChunks(
      [
        {
          filename: item.filename,
          status: "modified",
          additions: item.count,
          deletions: 0,
          patch
        }
      ],
      policy,
      policy.limits
    );
    assert.equal(initial.accepted, true);
    assert.equal(initial.chunks.length, 1);

    const fitted = await fitReviewChunksToContext({
      rootDir,
      pr,
      chunks: initial.chunks,
      policy,
      limits: policy.limits
    });
    assert.equal(fitted.accepted, true, item.filename);
    assert.ok(fitted.chunks.length > 1, item.filename);
    assert.equal(fitted.contexts.length, fitted.chunks.length);
    assert.ok(
      fitted.contexts.every((context) => context.contextChars <= policy.limits.maxContextChars),
      item.filename
    );
    assert.equal(
      fitted.chunks.reduce((total, chunk) => total + chunk.changedLines, 0),
      item.count,
      item.filename
    );
  }
});

test("a serialized oversized single JSX line is split to fit context", async () => {
  const patch = `+${"<>".repeat(30000)}`;
  const initial = planReviewChunks(
    [
      {
        filename: "frontend/src/Generated.tsx",
        status: "modified",
        additions: 1,
        deletions: 0,
        patch
      }
    ],
    policy,
    policy.limits
  );
  assert.equal(initial.chunks.length, 1);
  const fitted = await fitReviewChunksToContext({
    rootDir,
    pr,
    chunks: initial.chunks,
    policy,
    limits: policy.limits
  });
  assert.equal(fitted.accepted, true);
  assert.ok(fitted.chunks.length > 1);
  assert.ok(
    fitted.contexts.every((context) => context.contextChars <= policy.limits.maxContextChars)
  );
  assert.equal(
    fitted.chunks.reduce((total, chunk) => total + chunk.changedLines, 0),
    1
  );
});

test("context-aware splitting still enforces the final chunk cap", async () => {
  const patch = Array.from(
    { length: 1800 },
    () => "+<A><B><C><D></D></C></B></A>"
  ).join("\n");
  const initial = planReviewChunks(
    [
      {
        filename: "frontend/src/Synthetic.tsx",
        status: "modified",
        additions: 1800,
        deletions: 0,
        patch
      }
    ],
    policy,
    policy.limits
  );
  const fitted = await fitReviewChunksToContext({
    rootDir,
    pr,
    chunks: initial.chunks,
    policy,
    limits: { ...policy.limits, maxChunks: 1 }
  });
  assert.equal(fitted.accepted, false);
  assert.match(fitted.reasons.at(-1), /chunk .*한도 1개/);
});

test("an oversized policy baseline is reported without splitting patch to characters", async () => {
  const initial = planReviewChunks(
    [
      {
        filename: "backend/src/example.py",
        status: "modified",
        additions: 1,
        deletions: 0,
        patch: "+value = 1"
      }
    ],
    policy,
    policy.limits
  );
  const fitted = await fitReviewChunksToContext({
    rootDir,
    pr,
    chunks: initial.chunks,
    policy,
    limits: { ...policy.limits, maxContextChars: 1 }
  });
  assert.equal(fitted.accepted, false);
  assert.equal(fitted.chunks.length, 1);
  assert.match(fitted.reasons[0], /backend-1: 리뷰 컨텍스트/);
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
