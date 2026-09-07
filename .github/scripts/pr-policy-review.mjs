#!/usr/bin/env node

import { appendFile, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {
  CHECK_NAME,
  MERGED_REVIEW_SCHEMA,
  REVIEW_SCHEMA,
  addRedactionFinding,
  applyLimits,
  attachReviewState,
  buildInstructions,
  buildMergeContext,
  buildMergeInstructions,
  buildOpenAIRequest,
  collectHeadFileEvidence,
  discordPayload,
  estimateOpenAICost,
  extractResponseText,
  fetchWithRetry,
  findCheckRun,
  findReviewComment,
  fitReviewChunksToContext,
  hasProjectWideChange,
  incompleteReview,
  isReusableReviewState,
  isInternalPullRequest,
  isSamePullRequestSnapshot,
  mapWithConcurrency,
  mergeReviewsFallback,
  normalizeMergedReview,
  normalizeReview,
  parseReviewState,
  planPolicyArbitration,
  planForEvent,
  planReviewChunks,
  reconcileMergedReview,
  redactSecrets,
  reviewChunkFingerprint,
  renderDiscordReviewMessages,
  renderGitHubComment,
  shouldIgnoreFile,
  stableObjectHash,
  stableSafetyIdentifier,
  stripReviewState,
  sumUsage,
  validatePolicyConfig
} from "./pr-review-lib.mjs";

const rootDir = process.env.GITHUB_WORKSPACE || process.cwd();
const repository = requiredEnv("GITHUB_REPOSITORY");
const githubToken = requiredEnv("GITHUB_TOKEN");
const githubApiUrl = process.env.GITHUB_API_URL || "https://api.github.com";
const eventName = process.env.GITHUB_EVENT_NAME || "workflow_dispatch";
const eventPath = requiredEnv("GITHUB_EVENT_PATH");
const trustedBaseSha = process.env.PR_REVIEW_TRUSTED_BASE_SHA || process.env.GITHUB_SHA || "";
const dryRun = parseBoolean(process.env.PR_REVIEW_DRY_RUN, eventName === "workflow_dispatch");
const invokeOpenAI = parseBoolean(process.env.PR_REVIEW_INVOKE_OPENAI, eventName !== "workflow_dispatch");
const skipDiscord = parseBoolean(process.env.PR_REVIEW_SKIP_DISCORD, false);
const model = process.env.OPENAI_REVIEW_MODEL || "gpt-5.6-luna";
const reasoningEffort = process.env.OPENAI_REVIEW_REASONING_EFFORT || "low";
const mergeModel = process.env.OPENAI_REVIEW_MERGE_MODEL || "gpt-5.6-terra";
const mergeReasoningEffort = process.env.OPENAI_REVIEW_MERGE_REASONING_EFFORT || "medium";
const reviewVerbosity = process.env.OPENAI_REVIEW_VERBOSITY || "low";
const mergeVerbosity = process.env.OPENAI_REVIEW_MERGE_VERBOSITY || "low";
const openAiKey = process.env.OPENAI_REVIEW_API_KEY || "";
const discordWebhookUrl = process.env.DISCORD_PR_WEBHOOK_URL || "";
const runUrl = `${process.env.GITHUB_SERVER_URL || "https://github.com"}/${repository}/actions/runs/${process.env.GITHUB_RUN_ID || ""}`;

const startedAt = Date.now();
let discordFailures = 0;
let openAiFailure = false;

try {
  const [event, policyFile] = await Promise.all([
    readJson(eventPath),
    readJson(path.join(rootDir, ".github/pr-review-policy.json"))
  ]);
  const policyValidation = validatePolicyConfig(policyFile);
  if (!policyValidation.valid) {
    throw new Error(`PR review policy is invalid: ${policyValidation.reasons.join("; ")}`);
  }
  const prNumber = Number(
    eventName === "workflow_dispatch"
      ? process.env.PR_REVIEW_PR_NUMBER || event.inputs?.pr_number
      : event.pull_request?.number
  );
  if (!Number.isInteger(prNumber) || prNumber < 1) {
    throw new Error("A valid pull request number is required");
  }

  const pr = await githubJson(`/repos/${repository}/pulls/${prNumber}`);
  if (!isInternalPullRequest(pr, repository)) {
    await writeSummary(`## PR Policy Agent\n\n외부 fork PR #${prNumber}는 정책에 따라 건너뛰었습니다.`);
    process.exit(0);
  }
  const action = event.action || "workflow_dispatch";
  const eventPlan = planForEvent({ eventName, action, pr });
  if (pr.draft && !eventPlan.notifyClosed) {
    await writeSummary(`## PR Policy Agent\n\nDraft PR #${prNumber}는 secret을 사용하는 알림과 AI 리뷰를 실행하지 않았습니다.`);
    process.exit(0);
  }

  if (eventPlan.notifyCreated) {
    await notifyDiscord(
      `📬 **PR 생성${pr.draft ? " (Draft)" : ""}**\nPR #${pr.number} ${safePrTitle(pr.title, 240)}\n작성자: ${pr.user?.login ?? "unknown"}\n${pr.html_url}`
    );
  }

  if (eventPlan.notifyClosed) {
    if (!dryRun) await clearStoredReviewState(pr.number);
    await notifyDiscord(
      `${pr.merged ? "✅ **PR 병합**" : "🚫 **PR 종료**"}\nPR #${pr.number} ${safePrTitle(pr.title, 240)}\n${pr.html_url}`
    );
    await writeSummary(
      `## PR Policy Agent\n\nPR #${pr.number}의 ${pr.merged ? "병합" : "종료"} 알림을 처리했습니다.\n\nDiscord 실패: ${discordFailures}`
    );
    process.exit(0);
  }

  if (!eventPlan.review) {
    await writeSummary(
      `## PR Policy Agent\n\nPR #${pr.number}는 ${eventPlan.reason} 상태이므로 AI 리뷰를 실행하지 않았습니다.\n\nDiscord 실패: ${discordFailures}`
    );
    process.exit(0);
  }
  if (!trustedBaseSha || pr.base?.sha !== trustedBaseSha) {
    await writeSummary(
      `## PR Policy Agent\n\ncheckout한 trusted base SHA와 PR #${pr.number}의 현재 base SHA가 달라 stale 실행을 종료했습니다. 최신 base에서 workflow를 다시 실행해 주세요.`
    );
    process.exit(0);
  }

  // 변경: action이 "opened"가 아닐 때만 시작 알림 전송
  if (action !== "opened") {
    const staleNotice = action === "synchronize" ? "\n이전 SHA의 리뷰는 만료되었으며 최신 commit을 검토합니다." : "";
    await notifyDiscord(
      `🤖 **PR AI 리뷰 시작**\nPR #${pr.number} ${safePrTitle(pr.title, 220)}\nSHA: \`${pr.head.sha.slice(0, 12)}\`${staleNotice}\n${runUrl}`
    );
  }
  const previousReviewComment =
    action === "synchronize" ? findReviewComment(await listIssueComments(pr.number)) : null;
  const previousReviewState = parseReviewState(previousReviewComment?.body);
  const files = await listPullRequestFiles(pr.number);
  const prAfterFileCollection = await githubJson(`/repos/${repository}/pulls/${pr.number}`);
  if (!isSamePullRequestSnapshot(pr, prAfterFileCollection)) {
    await writeSummary(
      `## PR Policy Agent\n\nPR #${pr.number}의 head 또는 base가 입력 수집 중 변경되어 stale 실행을 종료했습니다. 최신 workflow 실행이 현재 SHA를 검토합니다.`
    );
    process.exit(0);
  }
  const reviewableFiles = files.filter((file) => !shouldIgnoreFile(file.filename, policyFile));
  const limits = effectiveLimits(policyFile.limits ?? {});
  const serviceTier = policyFile.cost?.serviceTier ?? "default";
  const configurationHash = stableObjectHash({
    stateVersion: 1,
    policy: policyFile,
    limits,
    leaf: { model, reasoningEffort, reviewVerbosity, serviceTier },
    merge: {
      model: mergeModel,
      reasoningEffort: mergeReasoningEffort,
      verbosity: mergeVerbosity,
      serviceTier
    },
    schema: REVIEW_SCHEMA,
    mergeSchema: MERGED_REVIEW_SCHEMA,
    leafInstructions: buildInstructions(limits.chunkMaxFindings),
    singleInstructions: buildInstructions(limits.maxFindings),
    mergeInstructions: buildMergeInstructions(limits.maxFindings)
  });
  const sizeCheck = applyLimits(reviewableFiles, limits);
  let chunkPlan = sizeCheck.accepted
    ? planReviewChunks(reviewableFiles, policyFile, limits)
    : { accepted: false, chunks: [], reasons: [] };
  let context = {
    modules: [],
    redactionCount: 0,
    redactedFiles: [],
    missingPolicyPaths: [],
    missingPatches: [],
    contextChars: 0,
    reasons: [],
    reviewMode: chunkPlan.chunks.length > 1 ? "multi" : "single",
    chunkCount: chunkPlan.chunks.length,
    reusedChunkCount: 0,
    reviewedChunkCount: chunkPlan.chunks.length,
    finalReviewReused: false,
    arbiterRequired: false,
    arbiterCompleted: false,
    arbiterReused: false
  };
  let review;
  let usage = sumUsage([]);
  const usageCalls = [];
  let effectiveModel = model;
  let reviewState = null;
  let headEvidence = {
    files: [],
    unavailable: [],
    candidateCount: 0,
    sourceChars: 0,
    contextChars: 0,
    redactionCount: 0,
    redactedFiles: [],
    fingerprint: stableObjectHash({ candidates: [] })
  };

  if (reviewableFiles.length === 0) {
    review = {
      status: "clean",
      summary: "lockfile, binary 또는 생성물 제외 후 AI 검토 대상 파일이 없습니다.",
      findings: [],
      missing_evidence: []
    };
  } else if (!sizeCheck.accepted) {
    review = incompleteReview(sizeCheck.reasons);
  } else if (!chunkPlan.accepted) {
    review = incompleteReview(chunkPlan.reasons);
  } else {
    headEvidence = await collectHeadFileEvidence({
      files: reviewableFiles,
      policy: policyFile,
      limits,
      loadFile: (file) =>
        githubJson(
          `/repos/${repository}/contents/${encodeRepositoryPath(file.filename)}?ref=${encodeURIComponent(pr.head.sha)}`
        )
    });
    const fittedPlan = await fitReviewChunksToContext({
      rootDir,
      pr,
      chunks: chunkPlan.chunks,
      policy: policyFile,
      limits,
      headEvidence
    });
    chunkPlan = {
      accepted: fittedPlan.accepted,
      chunks: fittedPlan.chunks,
      reasons: fittedPlan.reasons
    };
    const chunkContexts = fittedPlan.contexts;
    context = combineChunkContexts(chunkPlan, chunkContexts);
    context.headEvidenceCandidateCount = headEvidence.candidateCount;
    context.headEvidenceFileCount = headEvidence.files.length;
    context.headEvidenceChars = headEvidence.contextChars;
    context.unavailableHeadEvidencePaths = headEvidence.unavailable.map(
      (item) => item.filename
    );
    context.redactionCount += headEvidence.redactionCount;
    context.headEvidenceRedactionCount = headEvidence.redactionCount;
    const arbitration = planPolicyArbitration(
      reviewableFiles.map((file) => file.filename),
      policyFile,
      chunkPlan.chunks.length
    );
    context.arbiterRequired = arbitration.required;
    context.arbiterReasons = arbitration.reasons;
    context.arbiterPolicyPackIds = arbitration.policyPackIds;
    if (!chunkPlan.accepted) {
      review = incompleteReview(chunkPlan.reasons);
    } else if (dryRun && !invokeOpenAI) {
      review = incompleteReview([
        `Dry-run에서 OpenAI 호출 없이 ${chunkPlan.chunks.length}개 리뷰 chunk 구성까지만 검증했습니다.`
      ]);
    } else {
      const prMetadataFingerprint = stableObjectHash({
        title: pr.title ?? "",
        body: pr.body ?? ""
      });
      const chunkFingerprints = chunkPlan.chunks.map((chunk) =>
        reviewChunkFingerprint(chunk, headEvidence.fingerprint, prMetadataFingerprint)
      );
      const aggregateFingerprint = stableObjectHash({
        chunks: chunkFingerprints,
        headEvidenceFingerprint: headEvidence.fingerprint,
        title: pr.title ?? "",
        body: pr.body ?? "",
        inventory: reviewableFiles.map((file) => ({
          filename: file.filename,
          previous_filename: file.previous_filename ?? null,
          status: file.status,
          additions: Number(file.additions ?? 0),
          deletions: Number(file.deletions ?? 0)
        }))
      });
      const canReuseState =
        action === "synchronize" &&
        isReusableReviewState(previousReviewState, {
          repository,
          prNumber: pr.number,
          baseSha: pr.base.sha,
          configurationHash,
          projectWideChanged: hasProjectWideChange(reviewableFiles, policyFile)
        });
      const previousChunks = new Map(
        canReuseState
          ? previousReviewState.chunks
              .filter((item) => item?.fingerprint && item?.review)
              .map((item) => [item.fingerprint, item])
          : []
      );
      const findingLimit = chunkPlan.chunks.length === 1
        ? limits.maxFindings
        : limits.chunkMaxFindings;
      const leafInstructions = buildInstructions(findingLimit);
      const leafSchemaName =
        chunkPlan.chunks.length === 1 ? "pr_policy_review" : "pr_policy_chunk_review";
      const reusableReviews = chunkFingerprints.map((fingerprint) => {
        const stored = previousChunks.get(fingerprint);
        if (!stored) return null;
        try {
          return { ...stored, review: normalizeReview(stored.review, findingLimit) };
        } catch {
          return null;
        }
      });
      context.reusedChunkCount = reusableReviews.filter(Boolean).length;
      context.reviewedChunkCount = chunkPlan.chunks.length - context.reusedChunkCount;

      if (chunkPlan.chunks.length > 1) {
        await notifyDiscord(
          `🧩 **분할 리뷰 계획**\n${chunkPlan.chunks.length}개 chunk · 신규 ${context.reviewedChunkCount}개 · 재사용 ${context.reusedChunkCount}개 · 최대 동시 실행 ${limits.maxConcurrency}\n${chunkPlan.chunks.map((chunk) => `${chunk.id}: ${chunk.filenames.length} files / ${chunk.changedLines} lines`).join("\n")}`
        );
      }

      const runChunk = async (chunk, index) => {
        const chunkContext = chunkContexts[index];
        const stored = reusableReviews[index];
        if (stored) {
          return {
            ok: true,
            reused: true,
            chunk,
            fingerprint: chunkFingerprints[index],
            context: chunkContext,
            model: stored.model || model,
            usage: sumUsage([]),
            review: stored.review
          };
        }

        let response;
        try {
          response = await callOpenAI({
            pr,
            context: chunkContext,
            limits,
            instructions: leafInstructions,
            taskInstruction:
              chunkPlan.chunks.length === 1
                ? "이 PR의 전체 reviewable 변경을 검토합니다."
                : `이번 요청은 ${chunk.id} chunk만 검토합니다. 다른 chunk의 변경을 추측하지 않습니다.`,
            schemaName: leafSchemaName,
            requestMaxOutputTokens: limits.leafMaxOutputTokens,
            requestVerbosity: reviewVerbosity,
            requestServiceTier: serviceTier
          });
          assertCompletedResponse(response);
          return {
            ok: true,
            reused: false,
            chunk,
            fingerprint: chunkFingerprints[index],
            context: chunkContext,
            model: response.model || model,
            usage: response.usage || {},
            review: normalizeReview(
              JSON.parse(extractResponseText(response)),
              findingLimit
            )
          };
        } catch (error) {
          return {
            ok: false,
            reused: false,
            chunk,
            fingerprint: chunkFingerprints[index],
            context: chunkContext,
            model: response?.model || model,
            usage: response?.usage || {},
            review: incompleteReview([`${chunk.id}: ${safeError(error)}`])
          };
        }
      };
      const chunkRuns = new Array(chunkPlan.chunks.length);
      const pendingIndices = [];
      for (let index = 0; index < chunkPlan.chunks.length; index += 1) {
        if (reusableReviews[index]) {
          chunkRuns[index] = await runChunk(chunkPlan.chunks[index], index);
        } else {
          pendingIndices.push(index);
        }
      }
      const firstByCachePrefix = new Map();
      const followerIndices = [];
      for (const index of pendingIndices) {
        const key = stableObjectHash({
          model,
          schemaName: leafSchemaName,
          instructions: leafInstructions,
          cachePrefixText: chunkContexts[index].cachePrefixText
        });
        if (!firstByCachePrefix.has(key)) firstByCachePrefix.set(key, index);
        else followerIndices.push(index);
      }
      const runIndices = async (indices) => {
        const results = await mapWithConcurrency(
          indices,
          limits.maxConcurrency,
          async (index) => runChunk(chunkPlan.chunks[index], index)
        );
        indices.forEach((index, resultIndex) => {
          chunkRuns[index] = results[resultIndex];
        });
      };
      // 같은 정책 접두사를 쓰는 병렬 호출이 모두 cold cache write를 만들지 않도록
      // prefix별 첫 호출을 먼저 완료한 뒤 나머지 chunk를 병렬 실행한다.
      await runIndices([...firstByCachePrefix.values()]);
      await runIndices(followerIndices);
      usage = sumUsage(chunkRuns.map((run) => run.usage));
      usageCalls.push(
        ...chunkRuns
          .filter((run) => !run.reused)
          .map((run) => ({ model: run.model, usage: run.usage }))
      );
      effectiveModel = [...new Set(chunkRuns.map((run) => run.model))].join(", ") || model;
      const leafReviews = chunkRuns.map((run) => run.review);
      let finalReviewComplete = false;
      let finalModelUsed = null;

      if (chunkRuns.some((run) => !run.ok)) {
        openAiFailure = true;
        review = mergeReviewsFallback(leafReviews, limits.maxFindings, {
          forceIncomplete: true
        });
      } else if (!context.arbiterRequired) {
        review = chunkRuns.length === 1
          ? leafReviews[0]
          : mergeReviewsFallback(leafReviews, limits.maxFindings);
        finalReviewComplete = true;
        finalModelUsed = chunkRuns[0].model;
      } else if (
        context.reviewedChunkCount === 0 &&
        previousReviewState?.aggregateFingerprint === aggregateFingerprint &&
        previousReviewState?.finalReview
      ) {
        try {
          review = reconcileMergedReview(
            normalizeMergedReview(previousReviewState.finalReview, limits.maxFindings),
            leafReviews,
            limits.maxFindings
          );
          context.finalReviewReused = true;
          context.arbiterReused = true;
          finalReviewComplete = true;
          finalModelUsed = previousReviewState.finalModel || mergeModel;
          if (!effectiveModel.split(" + ").includes(finalModelUsed)) {
            effectiveModel = `${effectiveModel} + ${finalModelUsed}`;
          }
        } catch {
          review = null;
        }
      }

      if (!review && context.arbiterRequired && chunkRuns.every((run) => run.ok)) {
        const mergeInput = chunkRuns.map((run, index) => ({
          chunk_id: run.chunk.id,
          group: run.chunk.group,
          files: run.chunk.filenames,
          policy_packs: run.context.policyPackIds,
          review: leafReviews[index]
        }));
        const mergeContext = await buildMergeContext({
          rootDir,
          pr,
          files: reviewableFiles,
          policy: policyFile,
          limits,
          chunkResults: mergeInput,
          headEvidence,
          leafPolicyDocuments: chunkContexts.flatMap(
            (chunkContext) => chunkContext.policyDocuments ?? []
          )
        });
        context.mergeContextChars = mergeContext.contextChars;
        context.mergePolicySourceChars = mergeContext.policySourceChars;
        context.mergePolicyPaths = mergeContext.policyPaths;
        context.mergePolicyPackIds = mergeContext.policyPackIds;
        context.citedMergePolicyPaths = mergeContext.citedPolicyPaths;
        context.missingPolicyPaths = [...new Set([
          ...(context.missingPolicyPaths ?? []),
          ...(mergeContext.missingPolicyPaths ?? [])
        ])];
        if (!mergeContext.accepted) {
          review = mergeReviewsFallback(leafReviews, limits.maxFindings, {
            forceIncomplete: true
          });
          review.missing_evidence = [
            ...review.missing_evidence,
            ...mergeContext.reasons
          ].slice(0, 10);
        } else {
          try {
            const response = await callOpenAI({
              pr,
              context: mergeContext,
              limits,
              instructions: buildMergeInstructions(limits.maxFindings),
              taskInstruction: "선택된 leaf 결과를 현재 PR의 교차 정책 관점에서 중재합니다.",
              requestModel: mergeModel,
              requestReasoningEffort: mergeReasoningEffort,
              requestMaxOutputTokens: limits.mergeMaxOutputTokens,
              requestVerbosity: mergeVerbosity,
              requestServiceTier: serviceTier,
              schemaName: "pr_policy_merged_review",
              schema: MERGED_REVIEW_SCHEMA
            });
            const responseModel = response.model || mergeModel;
            usage = sumUsage([usage, response.usage]);
            usageCalls.push({ model: responseModel, usage: response.usage || {} });
            assertCompletedResponse(response);
            finalModelUsed = responseModel;
            effectiveModel = responseModel === model ? model : `${effectiveModel} + ${responseModel}`;
            review = reconcileMergedReview(
              normalizeMergedReview(
                JSON.parse(extractResponseText(response)),
                limits.maxFindings
              ),
              leafReviews,
              limits.maxFindings
            );
            finalReviewComplete = true;
            context.arbiterCompleted = true;
          } catch (error) {
            openAiFailure = true;
            review = mergeReviewsFallback(leafReviews, limits.maxFindings, {
              forceIncomplete: true
            });
            review.missing_evidence = [
              ...review.missing_evidence,
              `통합 리뷰: ${safeError(error)}`
            ].slice(0, 10);
          }
        }
      }

      reviewState = {
        version: 1,
        repository,
        prNumber: pr.number,
        baseSha: pr.base.sha,
        headSha: pr.head.sha,
        configurationHash,
        aggregateFingerprint,
        chunks: chunkRuns
          .filter((run) => run.ok)
          .map((run) => ({
            fingerprint: run.fingerprint,
            model: run.model,
            review: run.review
          })),
        finalModel: finalModelUsed,
        finalReview: finalReviewComplete ? review : null
      };
    }
  }

  const prBeforePublication = await githubJson(`/repos/${repository}/pulls/${pr.number}`);
  if (!isSamePullRequestSnapshot(pr, prBeforePublication)) {
    await writeSummary(
      `## PR Policy Agent\n\nPR #${pr.number}의 head, base 또는 상태가 리뷰 중 변경되어 stale 결과를 게시하지 않았습니다. 최신 workflow 실행이 현재 SHA를 검토합니다.`
    );
    process.exit(0);
  }

  review = withContextEvidence(review, context);
  review = addRedactionFinding(review, context.redactedFiles ?? []);
  const costEstimate = estimateOpenAICost(usageCalls, policyFile.cost);
  context.longContextCallCount = costEstimate.longContextCalls;
  const durationMs = Date.now() - startedAt;
  const renderedComment = renderGitHubComment({
    pr,
    review,
    model: effectiveModel,
    usage,
    costEstimate,
    durationMs,
    context
  });
  const stateAttachment = attachReviewState(renderedComment, reviewState);
  const comment = stateAttachment.body;
  context.reviewStatePersisted = stateAttachment.persisted;

  if (!dryRun) {
    await upsertReviewComment(pr.number, comment);
    await upsertCheckRun({
      sha: pr.head.sha,
      conclusion: openAiFailure ? "failure" : review.status === "clean" ? "success" : "neutral",
      title: checkTitle(review, openAiFailure),
      summary: checkSummary(review, context, runUrl)
    });
  }

  for (const message of renderDiscordReviewMessages({
    pr: { ...pr, title: safePrTitle(pr.title, 240) },
    review,
    model: effectiveModel,
    usage,
    costEstimate,
    durationMs,
    modules: context.modules ?? [],
    reviewMode: context.reviewMode,
    arbiterRequired: context.arbiterRequired,
    chunkCount: context.chunkCount,
    reusedChunkCount: context.reusedChunkCount,
    reviewedChunkCount: context.reviewedChunkCount,
    runUrl
  })) {
    await notifyDiscord(message);
  }

  await writeSummary(`## PR Policy Agent

- PR: #${pr.number}
- SHA: \`${pr.head.sha}\`
- 상태: **${review.status}**
- 모델: \`${effectiveModel}\`
- 영향 모듈: ${(context.modules ?? []).join(", ") || "없음"}
- 리뷰 방식: ${reviewModeLabel(context)}
- 정책 pack: ${(context.policyPackIds ?? []).join(", ") || "common-core"}
- 정책 중재 trigger: ${(context.arbiterReasons ?? []).join(", ") || "없음"}
- 중재 pack: ${(context.mergePolicyPackIds ?? []).join(", ") || "없음"}
- 증분 리뷰: 신규 ${context.reviewedChunkCount ?? context.chunkCount ?? 0}개 / 재사용 ${context.reusedChunkCount ?? 0}개 / 정책 중재 재사용 ${context.arbiterReused ? "예" : "아니오"}
- 파일: ${reviewableFiles.length} reviewable / ${files.length} total, 변경 줄: ${sizeCheck.changedLines}
- 부분 정책 원문 합: ${context.policySourceChars ?? 0}자, 부분 컨텍스트 합: ${context.contextChars ?? 0}자
- 중재 정책 원문: ${context.mergePolicySourceChars ?? 0}자, 중재 컨텍스트: ${context.mergeContextChars ?? 0}자
- PR head 전체 파일 근거: ${context.headEvidenceFileCount ?? 0}/${context.headEvidenceCandidateCount ?? 0}개, ${context.headEvidenceChars ?? 0}자
- 비밀 의심 redaction: ${context.redactionCount ?? 0}
- Finding: ${review.findings.length}
- 교차 검증 제외: ${(review.dismissed_findings ?? []).length}
- Token cache: read ${usage.input_tokens_details?.cached_tokens ?? 0} / write ${usage.input_tokens_details?.cache_write_tokens ?? 0}
- 예상 API 비용: ${costEstimate.complete ? `${costEstimate.currency} ${costEstimate.estimatedCost.toFixed(6)}` : `산정 불완전 (${costEstimate.unpricedModels.join(", ")})`}
- 272K token 초과 호출: ${costEstimate.longContextCalls}
- 증분 상태 저장: ${context.reviewStatePersisted ? "예" : "아니오"}
- Discord 실패: ${discordFailures}
- Dry-run: ${dryRun}
- OpenAI 호출: ${!dryRun || invokeOpenAI}`);

  if (openAiFailure) process.exitCode = 1;
} catch (error) {
  await writeSummary(`## PR Policy Agent 실패\n\n${safeError(error)}`);
  throw error;
}

function combineChunkContexts(chunkPlan, chunkContexts) {
  const unique = (items) => [...new Set(items)];
  return {
    modules: unique(chunkContexts.flatMap((item) => item.modules ?? [])),
    policyPaths: unique(chunkContexts.flatMap((item) => item.policyPaths ?? [])),
    policyDocuments: chunkContexts.flatMap((item) => item.policyDocuments ?? []),
    policyPackIds: unique(chunkContexts.flatMap((item) => item.policyPackIds ?? [])),
    policySourceChars: chunkContexts.reduce(
      (total, item) => total + Number(item.policySourceChars ?? 0),
      0
    ),
    missingPolicyPaths: unique(chunkContexts.flatMap((item) => item.missingPolicyPaths ?? [])),
    missingPatches: unique(chunkContexts.flatMap((item) => item.missingPatches ?? [])),
    redactionCount: chunkContexts.reduce((total, item) => total + Number(item.redactionCount ?? 0), 0),
    redactedFiles: unique(chunkContexts.flatMap((item) => item.redactedFiles ?? [])),
    contextChars: chunkContexts.reduce((total, item) => total + Number(item.contextChars ?? 0), 0),
    reasons: chunkContexts.flatMap((item) => item.reasons ?? []),
    reviewMode: chunkPlan.chunks.length > 1 ? "multi" : "single",
    chunkCount: chunkPlan.chunks.length,
    chunkIds: chunkPlan.chunks.map((chunk) => chunk.id)
  };
}

function withContextEvidence(review, context, prefix = "") {
  const label = prefix ? `${prefix}: ` : "";
  const unavailable = [
    ...(context.missingPolicyPaths ?? []).map((item) => `${label}정책 파일을 읽지 못함: ${item}`),
    ...(context.missingPatches ?? []).map((item) => `${label}GitHub patch가 없거나 불완전함: ${item}`)
  ];
  if (unavailable.length === 0) return review;
  return {
    ...review,
    status: "incomplete",
    missing_evidence: [...new Set([...(review.missing_evidence ?? []), ...unavailable])].slice(0, 10)
  };
}

function assertCompletedResponse(response) {
  if (response?.status && response.status !== "completed") {
    throw new Error(`OpenAI response status was ${response.status}`);
  }
}

function reviewModeLabel(context) {
  const mode = context.reviewMode === "multi"
    ? `분할 ${context.chunkCount ?? 0}개`
    : "단일 리뷰";
  const withArbiter = context.arbiterRequired ? `${mode} + 정책 중재` : mode;
  return context.reusedChunkCount > 0
    ? `${withArbiter} (신규 ${context.reviewedChunkCount ?? 0}, 재사용 ${context.reusedChunkCount})`
    : withArbiter;
}

async function callOpenAI({
  pr,
  context,
  limits,
  instructions,
  taskInstruction,
  requestModel = model,
  requestReasoningEffort = reasoningEffort,
  requestMaxOutputTokens = limits.leafMaxOutputTokens,
  requestVerbosity = reviewVerbosity,
  requestServiceTier = "default",
  schemaName = "pr_policy_review",
  schema = REVIEW_SCHEMA
}) {
  if (!openAiKey) throw new Error("OPENAI_REVIEW_API_KEY is not configured");
  const requestBody = buildOpenAIRequest({
    model: requestModel,
    instructions,
    cachePrefixText: context.cachePrefixText,
    dynamicText: context.dynamicText ?? context.text,
    taskInstruction,
    reasoningEffort: requestReasoningEffort,
    verbosity: requestVerbosity,
    schemaName,
    schema,
    maxOutputTokens: requestMaxOutputTokens,
    serviceTier: requestServiceTier,
    safetyIdentifier: stableSafetyIdentifier(repository, pr.user?.login ?? "unknown")
  });
  const response = await fetchWithRetry(
    "https://api.openai.com/v1/responses",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${openAiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(requestBody),
      timeoutMs: 300000
    },
    { attempts: 3 }
  );
  return response.json();
}

async function githubJson(apiPath, options = {}) {
  const response = await fetchWithRetry(`${githubApiUrl}${apiPath}`, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${githubToken}`,
      "X-GitHub-Api-Version": "2022-11-28",
      ...(options.headers ?? {})
    }
  });
  if (response.status === 204) return null;
  return response.json();
}

async function listPullRequestFiles(prNumber) {
  const files = [];
  for (let page = 1; page <= 30; page += 1) {
    const batch = await githubJson(
      `/repos/${repository}/pulls/${prNumber}/files?per_page=100&page=${page}`
    );
    files.push(...batch);
    if (batch.length < 100) break;
  }
  return files;
}

async function listIssueComments(prNumber) {
  const comments = [];
  for (let page = 1; page <= 10; page += 1) {
    const batch = await githubJson(
      `/repos/${repository}/issues/${prNumber}/comments?per_page=100&page=${page}`
    );
    comments.push(...batch);
    if (batch.length < 100) break;
  }
  return comments;
}

async function upsertReviewComment(prNumber, body) {
  const comments = await listIssueComments(prNumber);
  const existing = findReviewComment(comments);
  if (existing) {
    await githubJson(`/repos/${repository}/issues/comments/${existing.id}`, {
      method: "PATCH",
      body: JSON.stringify({ body })
    });
  } else {
    await githubJson(`/repos/${repository}/issues/${prNumber}/comments`, {
      method: "POST",
      body: JSON.stringify({ body })
    });
  }
}

async function clearStoredReviewState(prNumber) {
  const comments = await listIssueComments(prNumber);
  const existing = findReviewComment(comments);
  if (!existing) return;
  const body = stripReviewState(existing.body);
  if (body === existing.body) return;
  await githubJson(`/repos/${repository}/issues/comments/${existing.id}`, {
    method: "PATCH",
    body: JSON.stringify({ body })
  });
}

async function upsertCheckRun({ sha, conclusion, title, summary }) {
  const existing = await githubJson(
    `/repos/${repository}/commits/${sha}/check-runs?check_name=${encodeURIComponent(CHECK_NAME)}&per_page=100`
  );
  const check = findCheckRun(existing.check_runs ?? []);
  const body = {
    name: CHECK_NAME,
    status: "completed",
    conclusion,
    details_url: runUrl,
    output: { title, summary: safeText(summary, 60000) }
  };
  if (check) {
    await githubJson(`/repos/${repository}/check-runs/${check.id}`, {
      method: "PATCH",
      body: JSON.stringify(body)
    });
  } else {
    await githubJson(`/repos/${repository}/check-runs`, {
      method: "POST",
      body: JSON.stringify({ ...body, head_sha: sha })
    });
  }
}

async function notifyDiscord(content) {
  if (dryRun || skipDiscord) return;
  if (!discordWebhookUrl) {
    discordFailures += 1;
    return;
  }
  try {
    await fetchWithRetry(
      withQuery(discordWebhookUrl, "wait", "true"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(discordPayload(content))
      },
      { attempts: 3 }
    );
  } catch {
    discordFailures += 1;
  }
}

function effectiveLimits(configured) {
  const maxFindings = Math.min(
    5,
    positiveInteger(process.env.AI_REVIEW_MAX_FINDINGS, configured.maxFindings ?? 5)
  );
  return {
    maxFiles: positiveInteger(process.env.AI_REVIEW_MAX_FILES, configured.maxFiles ?? 200),
    maxChangedLines: positiveInteger(
      process.env.AI_REVIEW_MAX_CHANGED_LINES,
      configured.maxChangedLines ?? 10000
    ),
    maxContextChars: positiveInteger(
      process.env.AI_REVIEW_MAX_CONTEXT_CHARS,
      configured.maxContextChars ?? 200000
    ),
    headFileMaxChars: positiveInteger(
      process.env.AI_REVIEW_HEAD_FILE_MAX_CHARS,
      configured.headFileMaxChars ?? 20000
    ),
    headFileMaxBytes: positiveInteger(
      process.env.AI_REVIEW_HEAD_FILE_MAX_BYTES,
      configured.headFileMaxBytes ?? 80000
    ),
    headEvidenceMaxChars: positiveInteger(
      process.env.AI_REVIEW_HEAD_EVIDENCE_MAX_CHARS,
      configured.headEvidenceMaxChars ?? 60000
    ),
    headEvidenceMaxFiles: positiveInteger(
      process.env.AI_REVIEW_HEAD_EVIDENCE_MAX_FILES,
      configured.headEvidenceMaxFiles ?? 20
    ),
    chunkChangedLines: positiveInteger(
      process.env.AI_REVIEW_CHUNK_CHANGED_LINES,
      configured.chunkChangedLines ?? 2000
    ),
    chunkPatchChars: positiveInteger(
      process.env.AI_REVIEW_CHUNK_PATCH_CHARS,
      configured.chunkPatchChars ?? 80000
    ),
    maxChunks: positiveInteger(process.env.AI_REVIEW_MAX_CHUNKS, configured.maxChunks ?? 10),
    maxConcurrency: Math.min(
      6,
      positiveInteger(process.env.AI_REVIEW_MAX_CONCURRENCY, configured.maxConcurrency ?? 3)
    ),
    chunkMaxFindings: Math.min(
      3,
      maxFindings,
      positiveInteger(
        process.env.AI_REVIEW_CHUNK_MAX_FINDINGS,
        configured.chunkMaxFindings ?? 3
      )
    ),
    maxMergeContextChars: positiveInteger(
      process.env.AI_REVIEW_MAX_MERGE_CONTEXT_CHARS,
      configured.maxMergeContextChars ?? 300000
    ),
    maxFindings,
    leafMaxOutputTokens: positiveInteger(
      process.env.AI_REVIEW_LEAF_MAX_OUTPUT_TOKENS || process.env.AI_REVIEW_MAX_OUTPUT_TOKENS,
      configured.leafMaxOutputTokens ?? configured.maxOutputTokens ?? 2500
    ),
    mergeMaxOutputTokens: positiveInteger(
      process.env.AI_REVIEW_MERGE_MAX_OUTPUT_TOKENS || process.env.AI_REVIEW_MAX_OUTPUT_TOKENS,
      configured.mergeMaxOutputTokens ?? configured.maxOutputTokens ?? 4000
    )
  };
}

function checkTitle(review, failed) {
  if (failed) return "OpenAI 리뷰를 완료하지 못했습니다";
  if (review.status === "clean") return "정책 위반 finding이 없습니다";
  if (review.status === "incomplete") return "리뷰 입력 범위를 확인해 주세요";
  return `${review.findings.length}개의 권고 finding이 있습니다`;
}

function checkSummary(review, context, actionsUrl) {
  return `${review.summary}\n\nFinding: ${review.findings.length}\n교차 검증 제외: ${(review.dismissed_findings ?? []).length}\n영향 모듈: ${(context.modules ?? []).join(", ") || "없음"}\nActions: ${actionsUrl}\n\n이 검토는 권고형이며 사람 승인을 대체하지 않습니다.`;
}

function parseBoolean(value, fallback) {
  if (value === undefined || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
}

function positiveInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function safeError(error) {
  let message = error instanceof Error ? error.message : String(error);
  if (openAiKey) message = message.replaceAll(openAiKey, "[REDACTED]");
  if (discordWebhookUrl) message = message.replaceAll(discordWebhookUrl, "[REDACTED]");
  message = redactSecrets(message).text;
  return safeText(message, 1000);
}

function safePrTitle(value, maxLength) {
  return safeText(redactSecrets(value).text, maxLength);
}

function safeText(value, maxLength) {
  const text = String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim();
  return text.length <= maxLength ? text : `${text.slice(0, maxLength - 1)}…`;
}

function withQuery(url, key, value) {
  const parsed = new URL(url);
  parsed.searchParams.set(key, value);
  return parsed.toString();
}

function encodeRepositoryPath(filename) {
  return String(filename)
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function writeSummary(markdown) {
  if (!process.env.GITHUB_STEP_SUMMARY) return;
  await appendFile(process.env.GITHUB_STEP_SUMMARY, `${markdown}\n`, "utf8");
}
