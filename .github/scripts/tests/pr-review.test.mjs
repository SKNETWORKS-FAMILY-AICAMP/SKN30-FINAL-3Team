import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  extractMarkdownSections,
  fitReviewChunksToContext,
  isInternalPullRequest,
  isSamePullRequestSnapshot,
  planPolicyArbitration,
  planForEvent,
  reviewChunkFingerprint,
  selectPolicyPaths,
  validatePolicyConfig
} from "../pr-review-lib.mjs";
import { rootDir, event, policy, pr } from "./fixtures/pr-review.mjs";

test("same-repository PR is trusted for the base workflow", () => {
  assert.equal(
    isInternalPullRequest(pr, "SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team"),
    true
  );
  assert.equal(isInternalPullRequest(pr, "someone/fork"), false);
  assert.equal(isSamePullRequestSnapshot(pr, structuredClone(pr)), true);
  assert.equal(
    isSamePullRequestSnapshot(pr, { ...structuredClone(pr), head: { ...pr.head, sha: "new" } }),
    false
  );
  assert.equal(
    isSamePullRequestSnapshot(pr, { ...structuredClone(pr), state: "closed" }),
    false
  );
});

test("pull_request_target keeps executing trusted base code while configuring bounded evidence", async () => {
  const [workflow, engine] = await Promise.all([
    readFile(path.join(rootDir, ".github/workflows/pr-policy-review.yml"), "utf8"),
    readFile(path.join(rootDir, ".github/scripts/pr-policy-review.mjs"), "utf8")
  ]);
  assert.match(
    workflow,
    /ref: \$\{\{ github\.event\.pull_request\.base\.sha \|\| github\.sha \}\}/
  );
  assert.doesNotMatch(workflow, /ref:.*pull_request\.head\.sha/);
  assert.match(workflow, /uses: actions\/checkout@[0-9a-f]{40}/);
  assert.match(workflow, /persist-credentials: false/);
  assert.doesNotMatch(workflow, /git checkout/);
  assert.match(workflow, /PR_REVIEW_TRUSTED_BASE_SHA/);
  assert.match(workflow, /AI_REVIEW_HEAD_FILE_MAX_CHARS/);
  assert.match(workflow, /AI_REVIEW_HEAD_FILE_MAX_BYTES/);
  assert.match(workflow, /AI_REVIEW_HEAD_EVIDENCE_MAX_CHARS/);
  assert.match(workflow, /AI_REVIEW_HEAD_EVIDENCE_MAX_FILES/);
  assert.match(engine, /encodeRepositoryPath\(file\.filename\)/);
  assert.match(engine, /encodeURIComponent\(pr\.head\.sha\)/);
  assert.match(
    engine,
    /reviewChunkFingerprint\(chunk, headEvidence\.fingerprint, prMetadataFingerprint\)/
  );
  assert.match(engine, /fitReviewChunksToContext\(/);
  assert.match(engine, /planPolicyArbitration\(/);
  assert.match(engine, /!review && context\.arbiterRequired/);
  assert.doesNotMatch(engine, /headEvidence\.redactedFiles/);
  assert.doesNotMatch(engine, /raw_url|download_url|contents_url/);
});

test("runner passes the block-scoped policy service tier explicitly to every OpenAI call", async () => {
  const engine = await readFile(
    path.join(rootDir, ".github/scripts/pr-policy-review.mjs"),
    "utf8"
  );
  const explicitCallArguments = engine.match(/requestServiceTier: serviceTier/g) ?? [];

  assert.equal(explicitCallArguments.length, 2);
  assert.match(engine, /requestServiceTier = "default"/);
  assert.match(engine, /serviceTier: requestServiceTier/);
  assert.doesNotMatch(engine, /serviceTier: policyFile\.cost/);
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

  const policyOnly = await selectPolicyPaths(
    [".agents/skills/backend/references/decisions/ADR-0099.md"],
    policy,
    rootDir
  );
  assert.deepEqual(policyOnly.modules, ["backend"]);
  assert.ok(policyOnly.paths.includes(".agents/skills/backend/SKILL.md"));
  assert.ok(
    policyOnly.paths.includes(
      ".agents/skills/backend/references/decisions/ADR-0002-backend-runtime-database-authentication.md"
    )
  );
});

test("policy packs select split API contracts and bounded Infra domains", async () => {
  const api = await selectPolicyPaths(
    ["frontend/src/features/f3/api/f3Transport.ts"],
    policy,
    rootDir
  );
  assert.ok(api.policyPackIds.includes("api-contract-base"));
  assert.ok(api.policyPackIds.includes("api-contract-f3"));
  const contracts = ".agents/skills/project-wiki/references/contracts/";
  for (const filename of ["api-common.md", "api-f3.md", "f3-ai-common.md", "f3-ai-position-card.md", "f3-ai-brokerage.md", "f3-ai-implementation.md"]) {
    assert.ok(api.paths.includes(contracts + filename), filename);
  }
  assert.equal(api.paths.includes(contracts + "api-f2.md"), false);
  assert.equal(api.paths.includes(contracts + "api.md"), false);

  const network = await selectPolicyPaths(
    ["infra/environments/dev/network.tf"],
    policy,
    rootDir
  );
  assert.ok(network.policyPackIds.includes("infra-runtime-storage-network"));
  assert.equal(network.policyPackIds.includes("infra-runpod-sllm"), false);
  assert.equal(
    network.paths.includes(
      ".agents/skills/infra/references/decisions/ADR-0017-runpod-ephemeral-sllm-serving.md"
    ),
    false
  );

  const backendFeatures = await selectPolicyPaths(
    ["backend/src/api/f2.py", "backend/src/api/f3_runs.py"],
    policy,
    rootDir
  );
  assert.ok(backendFeatures.policyPackIds.includes("api-contract-f2"));
  assert.ok(backendFeatures.policyPackIds.includes("api-contract-f3"));
});

test("split contract edits retain common and feature evidence in leaf and arbiter", async () => {
  const contracts = ".agents/skills/project-wiki/references/contracts/";
  const cases = [
    ["api-f1.md", ["api-common.md", "api-f1.md"]],
    ["api-f2.md", ["api-common.md", "api-f2.md"]],
    ["api-f3.md", ["api-common.md", "api-f3.md", "f3-ai-common.md", "f3-ai-position-card.md", "f3-ai-brokerage.md", "f3-ai-implementation.md"]],
    ["f3-ai-position-card.md", ["api-common.md", "api-f3.md", "f3-ai-common.md", "f3-ai-brokerage.md"]],
    ["api-f4-timekeeper.md", ["api-common.md", "api-f4-timekeeper.md"]],
    ["api-f4-calendar.md", ["api-common.md", "api-f4-calendar.md", "api-f4-timekeeper.md"]]
  ];
  for (const phase of ["leaf", "arbiter"]) {
    for (const [changed, expected] of cases) {
      const selected = await selectPolicyPaths([contracts + changed], policy, rootDir, { phase });
      for (const filename of expected) assert.ok(selected.paths.includes(contracts + filename), `${phase} ${changed}: ${filename}`);
    }
  }
});

test("calendar code selects its persistence contract and Time Keeper union boundary", async () => {
  const contracts = ".agents/skills/project-wiki/references/contracts/";
  for (const filename of ["backend/src/domain/calendar/service.py", "frontend/src/features/calendar/model/dto.ts"]) {
    const selected = await selectPolicyPaths([filename], policy, rootDir);
    assert.ok(selected.policyPackIds.includes("api-contract-f4-calendar"));
    for (const document of ["api-common.md", "api-f4-calendar.md", "api-f4-timekeeper.md"]) {
      assert.ok(selected.paths.includes(contracts + document), document);
    }
    assert.ok(selected.paths.includes(".agents/skills/project-wiki/references/decisions/ADR-0025-calendar-storage-ownership.md"));
    assert.equal(selected.paths.includes(contracts + "api-f2.md"), false);
  }
});

test("Markdown section selection keeps document identity and rejects missing headings", () => {
  const source = "---\nstatus: 결정\n---\n\n# 계약\n\n소개\n\n## A\nA 본문\n\n### A 하위\n하위\n\n## B\nB 본문\n";
  const selected = extractMarkdownSections(source, ["B"]);
  assert.match(selected.text, /# 계약/);
  assert.match(selected.text, /## B\nB 본문/);
  assert.doesNotMatch(selected.text, /A 본문/);
  assert.deepEqual(selected.missingSections, []);
  assert.deepEqual(extractMarkdownSections(source, ["없음"]).missingSections, ["없음"]);
});

test("policy arbiter is conditional on chunks, modules, policies, and sensitive packs", () => {
  assert.equal(
    planPolicyArbitration(["frontend/src/features/HomeScreen.tsx"], policy, 1).required,
    false
  );
  assert.equal(
    planPolicyArbitration(["frontend/src/features/f3/api/f3Transport.ts"], policy, 1).required,
    true
  );
  assert.equal(planPolicyArbitration(["frontend/src/App.tsx"], policy, 2).required, true);
  assert.equal(
    planPolicyArbitration([".github/workflows/backend-ci.yml"], policy, 1).required,
    true
  );
  assert.equal(
    planPolicyArbitration(
      [".agents/skills/backend/references/decisions/ADR-0002-backend-runtime-database-authentication.md"],
      policy,
      1
    ).required,
    true
  );
  assert.equal(
    planPolicyArbitration(["frontend/src/App.tsx", "backend/src/main.py"], policy, 1).required,
    true
  );
});

test("policy pack manifest rejects ambiguous or incomplete definitions", () => {
  assert.deepEqual(validatePolicyConfig(policy), { valid: true, reasons: [] });
  const invalid = validatePolicyConfig({
    version: 2,
    modules: { infra: { directories: [".agents/skills/infra/references/decisions"] } },
    policyPacks: [
      { id: "duplicate", phases: ["leaf"], when: [{ always: true }], files: ["AGENTS.md"] },
      { id: "duplicate", phases: ["unknown"], when: [], files: [] }
    ]
  });
  assert.equal(invalid.valid, false);
  assert.match(
    invalid.reasons.join("\n"),
    /directory 재귀|중복|지원하지 않는 phase|when|정책 파일/
  );
});

test("every policy pack source and configured Markdown section resolves", async () => {
  const coreFiles = [
    ...(policy.always?.files ?? []),
    ...(policy.projectWide?.files ?? []),
    ...Object.values(policy.modules ?? {}).flatMap((module) => module.files ?? [])
  ];
  for (const policyPath of new Set(coreFiles)) {
    await readFile(path.join(rootDir, policyPath), "utf8");
  }
  for (const pack of policy.policyPacks) {
    for (const entry of pack.files) {
      const document = typeof entry === "string" ? { path: entry, sections: [] } : entry;
      const contents = await readFile(path.join(rootDir, document.path), "utf8");
      const extracted = extractMarkdownSections(contents, document.sections);
      assert.deepEqual(extracted.missingSections, [], `${pack.id}: ${document.path}`);
    }
  }
});
