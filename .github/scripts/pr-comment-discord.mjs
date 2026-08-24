#!/usr/bin/env node

import { appendFile, readFile } from "node:fs/promises";
import { buildPrCommentNotification } from "./pr-comment-discord-lib.mjs";
import { fetchWithRetry } from "./pr-review-lib.mjs";

const eventName = requiredEnv("GITHUB_EVENT_NAME");
const eventPath = requiredEnv("GITHUB_EVENT_PATH");
const webhookUrl = requiredEnv("DISCORD_PR_WEBHOOK_URL");
const event = JSON.parse(await readFile(eventPath, "utf8"));
const notification = buildPrCommentNotification(eventName, event);

if (!notification) {
  await writeSummary("## PR 댓글 Discord 알림\n\n알림 대상이 아닌 이벤트를 건너뛰었습니다.");
  process.exit(0);
}

const endpoint = new URL(webhookUrl);
endpoint.searchParams.set("wait", "true");

await fetchWithRetry(
  endpoint,
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(notification.payload),
    timeoutMs: 15000
  },
  { attempts: 3 }
);

await writeSummary(
  `## PR 댓글 Discord 알림\n\nPR #${notification.prNumber ?? "?"}의 ${notification.type} 알림을 전송했습니다.`
);

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function writeSummary(markdown) {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY;
  if (!summaryPath) return;
  await appendFile(summaryPath, `${markdown}\n`, "utf8");
}
