#!/usr/bin/env node

import { appendFile, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {
  CHECK_NAME,
  REVIEW_SCHEMA,
  addRedactionFinding,
  applyLimits,
  buildInstructions,
  buildMergeContext,
  buildMergeInstructions,
  buildReviewContext,
  discordPayload,
  extractResponseText,
  fetchWithRetry,
  findCheckRun,
  findReviewComment,
  incompleteReview,
  isInternalPullRequest,
  mapWithConcurrency,
  mergeReviewsFallback,
  normalizeReview,
  planForEvent,
  planReviewChunks,
  reconcileMergedReview,
  redactSecrets,
  renderDiscordReviewMessages,
  renderGitHubComment,
  shouldIgnoreFile,
  stableSafetyIdentifier,
  sumUsage
} from "./pr-review-lib.mjs";

const rootDir = process.env.GITHUB_WORKSPACE || process.cwd();
const repository = requiredEnv("GITHUB_REPOSITORY");
const githubToken = requiredEnv("GITHUB_TOKEN");
const githubApiUrl = process.env.GITHUB_API_URL || "https://api.github.com";
const eventName = process.env.GITHUB_EVENT_NAME || "workflow_dispatch";
const eventPath = requiredEnv("GITHUB_EVENT_PATH");
const dryRun = parseBoolean(process.env.PR_REVIEW_DRY_RUN, eventName === "workflow_dispatch");
const invokeOpenAI = parseBoolean(process.env.PR_REVIEW_INVOKE_OPENAI, eventName !== "workflow_dispatch");
const model = process.env.OPENAI_REVIEW_MODEL || "gpt-5.6-terra";
const reasoningEffort = process.env.OPENAI_REVIEW_REASONING_EFFORT || "medium";
const mergeModel = process.env.OPENAI_REVIEW_MERGE_MODEL || model;
const mergeReasoningEffort = process.env.OPENAI_REVIEW_MERGE_REASONING_EFFORT || reasoningEffort;
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
  if (pr.draft) {
    await writeSummary(`## PR Policy Agent\n\nDraft PR #${prNumber}는 secret을 사용하는 알림과 AI 리뷰를 실행하지 않았습니다.`);
    process.exit(0);
  }

  const action = event.action || "workflow_dispatch";
  const eventPlan = planForEvent({ eventName, action, pr });

  if (eventPlan.notifyCreated) {
    await notifyDiscord(
      `📬 **PR 생성${pr.draft ? " (Draft)" : ""}**\nPR #${pr.number} ${safePrTitle(pr.title, 240)}\n작성자: ${pr.user?.login ?? "unknown"}\n${pr.html_url}`
    );
  }

  if (eventPlan.notifyClosed) {
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

  // 변경: action이 "opened"가 아닐 때만 시작 알림 전송
  if (action !== "opened") {
    const staleNotice = action === "synchronize" ? "\n이전 SHA의 리뷰는 만료되었으며 최신 commit을 검토합니다." : "";
    await notifyDiscord(
      `🤖 **PR AI 리뷰 시작**\nPR #${pr.number} ${safePrTitle(pr.title, 220)}\nSHA: \`${pr.head.sha.slice(0, 12)}\`${staleNotice}\n${runUrl}`
    );
  }


  const files = await listPullRequestFiles(pr.number);
  const reviewableFiles = files.filter((file) => !shouldIgnoreFile(file.filename, policyFile));
  const limits = effectiveLimits(policyFile.limits ?? {});
  const sizeCheck = applyLimits(reviewableFiles, limits);
  const chunkPlan = sizeCheck.accepted
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
    chunkCount: chunkPlan.chunks.length
  };
  let review;
  let usage = { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
  let effectiveModel = model;

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
    const chunkContexts = await Promise.all(
      chunkPlan.chunks.map((chunk) =>
        buildReviewContext({
          rootDir,
          pr,
          files: chunk.files,
          policy: policyFile,
          limits
        })
      )
    );
    context = combineChunkContexts(chunkPlan, chunkContexts);
    const rejectedChunks = chunkContexts.flatMap((chunkContext, index) =>
      chunkContext.accepted
        ? []
        : chunkContext.reasons.map((reason) => `${chunkPlan.chunks[index].id}: ${reason}`)
    );

    if (rejectedChunks.length > 0) {
      review = incompleteReview(rejectedChunks);
    } else if (dryRun && !invokeOpenAI) {
      review = incompleteReview([
        `Dry-run에서 OpenAI 호출 없이 ${chunkPlan.chunks.length}개 리뷰 chunk 구성까지만 검증했습니다.`
      ]);
    } else if (chunkPlan.chunks.length === 1) {
      try {
        const response = await callOpenAI({
          pr,
          context: chunkContexts[0],
          limits,
          instructions: buildInstructions(limits.maxFindings),
          schemaName: "pr_policy_review"
        });
        effectiveModel = response.model || model;
        usage = response.usage || usage;
        assertCompletedResponse(response);
        review = normalizeReview(JSON.parse(extractResponseText(response)), limits.maxFindings);
      } catch (error) {
        openAiFailure = true;
        review = incompleteReview([safeError(error)]);
      }
    } else {
      await notifyDiscord(
        `🧩 **분할 리뷰 계획**\n${chunkPlan.chunks.length}개 chunk · 최대 동시 실행 ${limits.maxConcurrency}\n${chunkPlan.chunks.map((chunk) => `${chunk.id}: ${chunk.filenames.length} files / ${chunk.changedLines} lines`).join("\n")}`
      );
      const chunkRuns = await mapWithConcurrency(
        chunkPlan.chunks,
        limits.maxConcurrency,
        async (chunk, index) => {
          const chunkContext = chunkContexts[index];
          let response;
          try {
            response = await callOpenAI({
              pr,
              context: chunkContext,
              limits,
              instructions: `${buildInstructions(limits.chunkMaxFindings)}\n- 이번 요청은 ${chunk.id} chunk만 검토합니다. 다른 chunk의 변경을 추측하지 않습니다.`,
              schemaName: "pr_policy_chunk_review"
            });
            assertCompletedResponse(response);
            return {
              ok: true,
              chunk,
              context: chunkContext,
              model: response.model || model,
              usage: response.usage || {},
              review: normalizeReview(
                JSON.parse(extractResponseText(response)),
                limits.chunkMaxFindings
              )
            };
          } catch (error) {
            return {
              ok: false,
              chunk,
              context: chunkContext,
              model: response?.model || model,
              usage: response?.usage || {},
              review: incompleteReview([`${chunk.id}: ${safeError(error)}`])
            };
          }
        }
      );
      usage = sumUsage(chunkRuns.map((run) => run.usage));
      effectiveModel = [...new Set(chunkRuns.map((run) => run.model))].join(", ") || model;
      const leafReviews = chunkRuns.map((run) =>
        withContextEvidence(run.review, run.context, run.chunk.id)
      );

      if (chunkRuns.some((run) => !run.ok)) {
        openAiFailure = true;
        review = mergeReviewsFallback(leafReviews, limits.maxFindings, {
          forceIncomplete: true
        });
      } else {
        const mergeInput = chunkRuns.map((run, index) => ({
          chunk_id: run.chunk.id,
          group: run.chunk.group,
          files: run.chunk.filenames,
          review: leafReviews[index]
        }));
        const mergeContext = await buildMergeContext({
          rootDir,
          pr,
          files: reviewableFiles,
          policy: policyFile,
          limits,
          chunkResults: mergeInput
        });
        context.mergeContextChars = mergeContext.contextChars;
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
              requestModel: mergeModel,
              requestReasoningEffort: mergeReasoningEffort,
              schemaName: "pr_policy_merged_review"
            });
            assertCompletedResponse(response);
            usage = sumUsage([usage, response.usage]);
            const responseModel = response.model || mergeModel;
            effectiveModel = responseModel === model ? model : `${model} + ${responseModel}`;
            review = reconcileMergedReview(
              normalizeReview(
                JSON.parse(extractResponseText(response)),
                limits.maxFindings
              ),
              leafReviews,
              limits.maxFindings
            );
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
    }
  }

  review = withContextEvidence(review, context);
  review = addRedactionFinding(review, context.redactedFiles ?? []);
  const durationMs = Date.now() - startedAt;
  const comment = renderGitHubComment({
    pr,
    review,
    model: effectiveModel,
    usage,
    durationMs,
    context
  });

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
    durationMs,
    modules: context.modules ?? [],
    reviewMode: context.reviewMode,
    chunkCount: context.chunkCount,
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
- 파일: ${reviewableFiles.length} reviewable / ${files.length} total, 변경 줄: ${sizeCheck.changedLines}
- 부분 컨텍스트 합: ${context.contextChars ?? 0}자, 통합 컨텍스트: ${context.mergeContextChars ?? 0}자
- 비밀 의심 redaction: ${context.redactionCount ?? 0}
- Finding: ${review.findings.length}
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
  return context.reviewMode === "multi"
    ? `분할 ${context.chunkCount ?? 0}개 + 최종 통합`
    : "단일 리뷰";
}

async function callOpenAI({
  pr,
  context,
  limits,
  instructions,
  requestModel = model,
  requestReasoningEffort = reasoningEffort,
  schemaName = "pr_policy_review"
}) {
  if (!openAiKey) throw new Error("OPENAI_REVIEW_API_KEY is not configured");
  const response = await fetchWithRetry(
    "https://api.openai.com/v1/responses",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${openAiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: requestModel,
        instructions,
        input: context.text,
        reasoning: { effort: requestReasoningEffort },
        text: {
          verbosity: "medium",
          format: {
            type: "json_schema",
            name: schemaName,
            strict: true,
            schema: REVIEW_SCHEMA
          }
        },
        max_output_tokens: limits.maxOutputTokens,
        store: false,
        safety_identifier: stableSafetyIdentifier(repository, pr.user?.login ?? "unknown")
      }),
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
  if (dryRun) return;
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
    10,
    positiveInteger(process.env.AI_REVIEW_MAX_FINDINGS, configured.maxFindings ?? 10)
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
      maxFindings,
      positiveInteger(
        process.env.AI_REVIEW_CHUNK_MAX_FINDINGS,
        configured.chunkMaxFindings ?? 5
      )
    ),
    maxMergeContextChars: positiveInteger(
      process.env.AI_REVIEW_MAX_MERGE_CONTEXT_CHARS,
      configured.maxMergeContextChars ?? 300000
    ),
    maxFindings,
    maxOutputTokens: positiveInteger(
      process.env.AI_REVIEW_MAX_OUTPUT_TOKENS,
      configured.maxOutputTokens ?? 4000
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
  return `${review.summary}\n\nFinding: ${review.findings.length}\n영향 모듈: ${(context.modules ?? []).join(", ") || "없음"}\nActions: ${actionsUrl}\n\n이 검토는 권고형이며 사람 승인을 대체하지 않습니다.`;
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

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function writeSummary(markdown) {
  if (!process.env.GITHUB_STEP_SUMMARY) return;
  await appendFile(process.env.GITHUB_STEP_SUMMARY, `${markdown}\n`, "utf8");
}
