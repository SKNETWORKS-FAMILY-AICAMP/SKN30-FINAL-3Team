/**
 * F3 실행 lifecycle 조정.
 *
 * 앵커가 정해지면 실행을 확보하고, 끝날 때까지 상태를 확인하고, 단계가 바뀔 때만 결과를 다시
 * 읽는다. 패널은 이 훅이 만든 화면 상태만 그린다.
 *
 * SSE 진행 구독이 아직 없어 polling으로 만든다. 상태 조회는 가볍고 결과 조회는 무거우므로 두
 * 호출을 분리한다. 매번 결과까지 읽으면 바뀐 것이 없는데도 전체 후보를 다시 받는다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isCanceled } from "../../../shared/api/index.ts";
import { f3Transport } from "../api/f3Transport.ts";
import { DEFAULT_CANDIDATE_LIMIT } from "../api/limits.ts";
import type { CandidateSummary, RunAnchor } from "../api/transport.ts";
import type { AnchorCardDto, AnchorType, RunResultDto } from "../model/dto.ts";
import { describeCriteria, isTerminal, toCandidateView, toPanelState } from "../model/viewModel.ts";
import type { CandidateView, PanelState } from "../model/viewModel.ts";

/** 첫 확인은 빠르게. 5초 목표 구간에서 사용자가 진행을 곧바로 본다. */
const FIRST_INTERVAL_MS = 1000;
/** 길어지면 간격을 늘린다. 같은 답을 반복해서 받는 요청을 줄인다. */
const MAX_INTERVAL_MS = 5000;
/** 이 시간을 넘기면 자동 확인을 멈춘다. 실패로 바꾸지 않고 사용자에게 넘긴다. */
const PAUSE_AFTER_MS = 60_000;

/**
 * 확보한 실행의 화면 캐시.
 *
 * 같은 상세에서 패널을 닫았다 다시 열 때 새 실행을 만들지 않기 위한 것이다. Backend의 완료
 * 결과 재사용을 대신하는 영구 캐시가 아니다.
 *
 * 메모리에만 둔다. localStorage·sessionStorage에 넣지 않는다. 판정 결과에는 상담 근거가 섞일
 * 수 있고 브라우저 저장소는 세션이 끝나도 남는다.
 */
const runRegistry = new Map<string, number>();

/** 후보 요약 임시 캐시. Backend가 후보 응답에 표시 필드를 실어주면 함께 사라진다. */
const summaryCache = new Map<number, CandidateSummary>();

/**
 * 세션이 끝나면 두 캐시를 비운다.
 *
 * 사무소 공용 PC를 전제하므로 같은 브라우저에서 계정이 바뀔 수 있다. 실행 식별자와 장부
 * 식별자는 중개사무소 안에서만 유효하므로, 남겨 두면 앞 사용자의 실행을 조회해 404를 맞거나
 * 앞 사용자의 희망 단지를 화면에 그린다.
 */
export function resetCrossJudgmentCache(): void {
  runRegistry.clear();
  summaryCache.clear();
}

/**
 * 훅 입력은 원시값으로 받는다.
 *
 * 앵커를 객체로 받으면 부모가 렌더마다 새 객체를 만들 때 effect가 매번 다시 돌고, 그때마다
 * 실행 확보와 polling이 처음부터 시작된다. 호출부가 `useMemo`를 잊지 않아야만 동작하는 훅은
 * 만들지 않는다.
 */
export interface CrossJudgmentInput {
  /** `null`이면 저장 전이거나 매물 건이 없어 판정 대상이 아니다. */
  anchorType: AnchorType | null;
  anchorId: number | null;
  /**
   * 앵커 행의 `row_version`.
   *
   * 저장으로 이 값이 바뀌면 다른 실행이다. 같은 앵커라도 입력이 달라졌으므로 이전 판정을
   * 그대로 보여주면 안 된다.
   */
  dataVersion: number | null;
  /** 패널이 열려 있는 동안만 확인한다. */
  enabled: boolean;
  limit?: number;
}

export interface CrossJudgment {
  state: PanelState;
  runId: number | null;
  anchorCard: AnchorCardDto | null;
  candidates: CandidateView[];
  candidatesTotal: number;
  cardedCount: number;
  limit: number;
  offset: number;
  criteria: string[];
  /** 서버가 공개한 실패 문구. 내부 예외나 Provider 원문이 아니다. */
  failureMessage: string | null;
  /** HTTP·계약 오류. 실행 실패와 다른 축이다. */
  error: ApiError | null;
  setOffset: (offset: number) => void;
  /** 실패했거나 멈춘 뒤 다시 시작한다. */
  retry: () => void;
}

interface Snapshot {
  state: PanelState;
  runId: number | null;
  result: RunResultDto | null;
  error: ApiError | null;
}

const IDLE: Snapshot = { state: "unavailable", runId: null, result: null, error: null };

export function useCrossJudgment(input: CrossJudgmentInput): CrossJudgment {
  const { anchorType, anchorId, dataVersion, enabled } = input;
  const limit = input.limit ?? DEFAULT_CANDIDATE_LIMIT;

  const key =
    anchorType == null || anchorId == null || dataVersion == null
      ? null
      : `${anchorType}:${anchorId}:${dataVersion}`;

  const [snapshot, setSnapshot] = useState<Snapshot>(IDLE);
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [summaries, setSummaries] = useState<Map<number, CandidateSummary>>(summaryCache);

  // 늦게 도착한 이전 앵커의 응답이 현재 패널을 덮지 않게 하는 세대 번호.
  const generation = useRef(0);

  useEffect(() => {
    setOffset(0);
  }, [key]);

  useEffect(() => {
    if (key == null || anchorType == null || anchorId == null || !enabled) {
      setSnapshot(IDLE);
      return;
    }

    // 좁혀진 타입은 아래 중첩 async 함수 안까지 따라오지 않는다. 가드를 통과한 값으로
    // 앵커를 여기서 한 번 만든다. effect가 다시 돌 때만 새로 만들어지므로 신원도 안정적이다.
    const anchor: RunAnchor = { anchorType, anchorId };

    generation.current += 1;
    const mine = generation.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const isCurrent = () => !stopped && generation.current === mine;

    const publish = (next: Snapshot) => {
      if (isCurrent()) setSnapshot(next);
    };

    // 이전 결과를 유지해야 하는 전이는 함수형 갱신으로 읽는다. 렌더 중에 ref를 채워 두고
    // 꺼내 쓰면 렌더가 순수하지 않고, 이 effect가 언제 실행되든 최신 값이 보장되지도 않는다.
    const publishWith = (next: (previous: Snapshot) => Snapshot) => {
      if (isCurrent()) setSnapshot(next);
    };

    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, ms);
      });

    async function loadResult(runId: number, status: string): Promise<RunResultDto | null> {
      const result = await f3Transport.getRunResult(runId, { limit, offset }, controller.signal);
      if (!isCurrent()) return null;
      publish({
        // 페이지 길이가 아니라 전체 건수로 본다. 뒷 페이지를 보는 중에 앞 페이지가 비면
        // 후보가 있는 실행을 "후보 없음"으로 그리게 된다.
        state: toPanelState(status, result.candidates_total),
        runId,
        result,
        error: null,
      });
      void hydrateSummaries(result);
      return result;
    }

    /**
     * 후보 제목을 장부에서 채운다.
     *
     * 임시 우회이며 실패해도 판정 표시를 막지 않는다. 제목 하나 때문에 이미 받은 판정을 감추면
     * 사용자가 잃는 것이 더 크다.
     */
    async function hydrateSummaries(result: RunResultDto) {
      if (result.anchor_type !== "LISTING") return;
      const missing = result.candidates
        .map((candidate) => candidate.candidate_id)
        .filter((id) => !summaryCache.has(id));
      if (missing.length === 0) return;

      const loaded = await Promise.all(
        missing.map(async (id) => {
          try {
            return await f3Transport.fetchCandidateSummary(id, controller.signal);
          } catch {
            return null;
          }
        }),
      );
      if (!isCurrent()) return;

      let changed = false;
      for (const summary of loaded) {
        if (summary == null) continue;
        summaryCache.set(summary.requirementId, summary);
        changed = true;
      }
      if (changed) setSummaries(new Map(summaryCache));
    }

    /** 실행을 새로 접수하고 registry에 기록한다. */
    async function queueRun(): Promise<number> {
      publish({ state: "queueing", runId: null, result: null, error: null });
      const run = await f3Transport.createRun(anchor, controller.signal);
      runRegistry.set(key as string, run.run_id);
      return run.run_id;
    }

    /**
     * 실행을 확보하고 현재 단계를 함께 읽는다.
     *
     * 캐시된 실행 식별자를 그대로 믿지 않는다. 실행은 중개사무소 안에서만 유효한데 registry는
     * 브라우저 메모리에 남으므로, 계정이 바뀐 뒤 같은 앵커를 열면 서버가 404로 답한다. 그때는
     * 캐시를 버리고 새로 접수한 뒤 **그 실행 식별자를 돌려준다.** 옛 식별자를 그대로 들고
     * polling을 이어가면 이후 조회가 전부 없는 실행을 향한다.
     */
    async function resolveRun(): Promise<{ runId: number; status: string }> {
      const cached = runRegistry.get(key as string);
      if (cached == null) {
        const runId = await queueRun();
        return { runId, status: (await f3Transport.getRunStatus(runId, controller.signal)).status };
      }

      try {
        return { runId: cached, status: (await f3Transport.getRunStatus(cached, controller.signal)).status };
      } catch (cause) {
        if (!(cause instanceof ApiError) || cause.kind !== "notFound") throw cause;
        runRegistry.delete(key as string);
        const runId = await queueRun();
        return { runId, status: (await f3Transport.getRunStatus(runId, controller.signal)).status };
      }
    }

    async function drive() {
      try {
        // 확보한 실행의 현재 단계를 먼저 그린다. 이미 끝난 실행이면 여기서 끝난다.
        const resolved = await resolveRun();
        if (!isCurrent()) return;
        const runId = resolved.runId;
        let status = resolved.status;
        let lastStatus = "";
        const startedAt = Date.now();
        let interval = FIRST_INTERVAL_MS;

        for (;;) {
          if (!isCurrent()) return;

          // 단계가 바뀔 때만 결과를 다시 읽는다.
          if (status !== lastStatus) {
            lastStatus = status;
            await loadResult(runId, status);
            if (!isCurrent()) return;
          }

          if (isTerminal(status)) return;

          if (Date.now() - startedAt > PAUSE_AFTER_MS) {
            // 실패로 바꾸지 않는다. 서버 작업은 계속 돌고 있을 수 있다.
            publishWith((previous) => ({ ...previous, state: "paused" }));
            return;
          }

          await wait(interval);
          if (!isCurrent()) return;
          interval = Math.min(interval * 2, MAX_INTERVAL_MS);
          status = (await f3Transport.getRunStatus(runId, controller.signal)).status;
        }
      } catch (cause) {
        if (isCanceled(cause) || !isCurrent()) return;
        // 이미 받은 단계 결과는 버리지 않는다. 앵커 카드까지 보고 있던 사용자가 통신 오류
        // 한 번에 화면을 통째로 잃으면, 실패한 것이 무엇인지 알 수 없다.
        publishWith((previous) => ({
          state: "failed",
          runId: runRegistry.get(key as string) ?? null,
          result: previous.result,
          error:
            cause instanceof ApiError
              ? cause
              : new ApiError({ kind: "server", message: "판정을 불러오지 못했습니다.", cause }),
        }));
      }
    }

    void drive();

    return () => {
      stopped = true;
      controller.abort();
      if (timer != null) clearTimeout(timer);
    };
    // offset과 limit이 바뀌면 실행을 새로 만들지 않고 registry의 같은 실행을 다시 읽는다.
  }, [key, anchorType, anchorId, enabled, attempt, limit, offset]);

  const retry = useCallback(() => {
    if (key != null) runRegistry.delete(key);
    setAttempt((current) => current + 1);
  }, [key]);

  const result = snapshot.result;
  const candidates = result == null
    ? []
    : result.candidates.map((candidate) =>
        toCandidateView(candidate, summaries.get(candidate.candidate_id), result.anchor_type),
      );

  return {
    state: snapshot.state,
    runId: snapshot.runId,
    anchorCard: result?.anchor_card ?? null,
    candidates,
    candidatesTotal: result?.candidates_total ?? 0,
    cardedCount: result?.candidate_selection.carded_count ?? 0,
    limit,
    offset,
    criteria: result == null ? [] : describeCriteria(result),
    failureMessage: result?.failure_message ?? null,
    error: snapshot.error,
    setOffset,
    retry,
  };
}
