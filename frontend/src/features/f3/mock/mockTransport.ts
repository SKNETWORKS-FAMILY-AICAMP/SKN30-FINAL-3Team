/**
 * Worker 없이 F3 화면을 완성하기 위한 메모리 transport.
 *
 * `WORKER_ENABLED=false`인 배포에서는 실행이 `QUEUED`에 머물러 앵커 카드, 후보 목록, 등급,
 * 기각 접기, 페이지네이션을 아무도 볼 수 없다. 여기서 시간에 따라 단계를 넘기며 서버가 할
 * 일을 흉내 낸다.
 *
 * 응답 본문은 `scenario.ts`가 만들고 이 파일은 저장소, 시계, 지연과 취소만 다룬다. 지어낸
 * 응답을 화면 모델로 바로 넘기지 않고 **실제 decoder에 통과시킨다.** 그래야 mock이 계약에서
 * 어긋날 때 화면이 아니라 decoder가 먼저 잡아내고, mock으로 확인한 화면이 실서버로 바꿔도
 * 같은 가정 위에서 돈다.
 *
 * 관심없음은 mock에서도 완성되지 않는다. `match_candidate_evaluation_id`가 아직 공개 계약에
 * 없어 화면이 버튼을 잠그기 때문이며, 없는 필드를 mock이 지어내면 만들어지지 않을 기능을
 * 준비하게 된다.
 */

import { APP_ENV } from "../../../config/env.ts";
import { ApiError } from "../../../shared/api/index.ts";
import { decodeFeedback, decodeRun, decodeRunResult, decodeRunStatus } from "../model/decode.ts";
import type { AnchorType } from "../model/dto.ts";
import { DEFAULT_CANDIDATE_LIMIT, MAX_CANDIDATE_LIMIT } from "../api/limits.ts";
import type { F3Transport } from "../api/transport.ts";
import { resultPayload, runPayload, statusAt, statusPayload } from "./scenario.ts";
import type { MockRun } from "./scenario.ts";

const runsByAnchor = new Map<string, MockRun>();
const runsById = new Map<number, MockRun>();
let nextRunId = 9_000;

function anchorKey(anchorType: AnchorType, anchorId: number): string {
  return `${anchorType}:${anchorId}`;
}

function statusOf(run: MockRun): string {
  return statusAt(Date.now() - run.createdAt);
}

function requireRun(runId: number): MockRun {
  const run = runsById.get(runId);
  // 실제 서버도 없는 실행과 다른 사무소의 실행을 똑같이 404로 답한다.
  if (run == null) {
    throw new ApiError({ kind: "notFound", message: "실행을 찾지 못했습니다.", status: 404 });
  }
  return run;
}

async function delay(signal?: AbortSignal): Promise<void> {
  const ms = APP_ENV.mockLatencyMs;
  if (ms <= 0) return;
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new ApiError({ kind: "canceled", message: "요청이 취소되었습니다." }));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export const mockTransport: F3Transport = {
  async createRun(anchor, signal) {
    await delay(signal);
    const key = anchorKey(anchor.anchorType, anchor.anchorId);
    // 서버의 활성 실행 중복 방지와 같게, 같은 앵커는 기존 실행을 그대로 돌려준다.
    let run = runsByAnchor.get(key);
    if (run == null) {
      nextRunId += 1;
      run = {
        runId: nextRunId,
        anchorType: anchor.anchorType,
        anchorId: anchor.anchorId,
        createdAt: Date.now(),
      };
      runsByAnchor.set(key, run);
      runsById.set(run.runId, run);
    }
    return decodeRun(runPayload(run, statusOf(run)));
  },

  async getRunStatus(runId, signal) {
    await delay(signal);
    const run = requireRun(runId);
    return decodeRunStatus(statusPayload(run, statusOf(run)));
  },

  async getRunResult(runId, page = {}, signal) {
    await delay(signal);
    const run = requireRun(runId);
    // 서버와 같은 범위로 자른다. 화면이 상한 없는 페이지를 전제하지 않게 한다.
    const limit = Math.min(Math.max(page.limit ?? DEFAULT_CANDIDATE_LIMIT, 1), MAX_CANDIDATE_LIMIT);
    const offset = Math.max(page.offset ?? 0, 0);
    return decodeRunResult(resultPayload(run, statusOf(run), { limit, offset }));
  },

  async sendNotInterested(input, signal) {
    await delay(signal);
    return decodeFeedback({
      feedback_id: 1,
      target: "MATCH_CANDIDATE",
      target_id: input.targetId,
      feedback_type: "NOT_INTERESTED",
      reason: input.reason,
      field_name: input.fieldName ?? null,
      created_at: new Date().toISOString(),
    });
  },
};
