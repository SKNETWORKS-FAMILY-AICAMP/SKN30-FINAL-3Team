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
  buildReviewContext,
  discordPayload,
  extractResponseText,
  fetchWithRetry,
  findCheckRun,
  findReviewComment,
  incompleteReview,
  isInternalPullRequest,
  normalizeReview,
  planForEvent,
  redactSecrets,
  renderDiscordReviewMessages,
  renderGitHubComment,
  shouldIgnoreFile,
  stableSafetyIdentifier
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

  const staleNotice = action === "synchronize" ? "\n이전 SHA의 리뷰는 만료되었으며 최신 commit을 검토합니다." : "";
  await notifyDiscord(
    `🤖 **PR AI 리뷰 시작**\nPR #${pr.number} ${safePrTitle(pr.title, 220)}\nSHA: \`${pr.head.sha.slice(0, 12)}\`${staleNotice}\n${runUrl}`
  );

  const files = await listPullRequestFiles(pr.number);
  const reviewableFiles = files.filter((file) => !shouldIgnoreFile(file.filename, policyFile));
  const limits = effectiveLimits(policyFile.limits ?? {});
  const sizeCheck = applyLimits(reviewableFiles, limits);
  let context = {
    modules: [],
    redactionCount: 0,
    redactedFiles: [],
    contextChars: 0,
    reasons: []
  };
  let review;
  let usage = { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
  let effectiveModel = model;

  if (!sizeCheck.accepted) {
    review = incompleteReview(sizeCheck.reasons);
  } else {
    context = await buildReviewContext({
      rootDir,
      pr,
      files,
      policy: policyFile,
      limits
    });
    if (!context.accepted) {
      review = incompleteReview(context.reasons);
    } else if (dryRun && !invokeOpenAI) {
      review = incompleteReview([
        "Dry-run에서 OpenAI 호출이 비활성화되어 컨텍스트 구성까지만 검증했습니다."
      ]);
    } else {
      try {
        const response = await callOpenAI({ pr, context, limits });
        effectiveModel = response.model || model;
        usage = response.usage || usage;
        if (response.status && response.status !== "completed") {
          throw new Error(`OpenAI response status was ${response.status}`);
        }
        review = normalizeReview(JSON.parse(extractResponseText(response)), limits.maxFindings);
      } catch (error) {
        openAiFailure = true;
        review = incompleteReview([safeError(error)]);
      }
    }
  }

  const unavailableEvidence = [
    ...(context.missingPolicyPaths ?? []).map((item) => `정책 파일을 읽지 못함: ${item}`),
    ...(context.missingPatches ?? []).map((item) => `GitHub patch를 제공받지 못함: ${item}`)
  ];
  if (unavailableEvidence.length > 0) {
    review = {
      ...review,
      missing_evidence: [...review.missing_evidence, ...unavailableEvidence].slice(0, 10)
    };
  }
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
- 파일: ${reviewableFiles.length} reviewable / ${files.length} total, 변경 줄: ${sizeCheck.changedLines}
- 컨텍스트: ${context.contextChars ?? 0}자
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

async function callOpenAI({ pr, context, limits }) {
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
        model,
        instructions: buildInstructions(limits.maxFindings),
        input: context.text,
        reasoning: { effort: reasoningEffort },
        text: {
          verbosity: "medium",
          format: {
            type: "json_schema",
            name: "pr_policy_review",
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
  return {
    maxFiles: positiveInteger(process.env.AI_REVIEW_MAX_FILES, configured.maxFiles ?? 60),
    maxChangedLines: positiveInteger(
      process.env.AI_REVIEW_MAX_CHANGED_LINES,
      configured.maxChangedLines ?? 2000
    ),
    maxContextChars: positiveInteger(
      process.env.AI_REVIEW_MAX_CONTEXT_CHARS,
      configured.maxContextChars ?? 200000
    ),
    maxFindings: Math.min(
      10,
      positiveInteger(process.env.AI_REVIEW_MAX_FINDINGS, configured.maxFindings ?? 10)
    ),
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
