import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isCanceled } from "../../../shared/api/index.ts";
import { f3Transport } from "../api/f3Transport.ts";
import { isTerminal } from "../model/viewModel.ts";
import type { AnchorType } from "../model/dto.ts";
import { judgmentApi } from "./api.ts";
import type { JudgmentTarget } from "./model.ts";
export function judgmentError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === "offline")
      return "연결을 확인한 뒤 다시 조회해 주세요. 마지막 조회 결과를 유지합니다.";
    if (["unauthorized", "forbidden", "notFound"].includes(error.kind))
      return "대상이 없거나 현재 접근할 수 없습니다.";
    if (error.code === "F3_INPUT_NOT_ELIGIBLE")
      return "분석 조건을 충족하지 않습니다. 원장 정보를 확인해 주세요.";
    if (error.code === "F3_UNAVAILABLE")
      return "새 분석 접수가 잠시 중단되었습니다. 저장된 결과는 확인할 수 있습니다.";
    if (error.kind === "contract")
      return "응답 형식을 확인하지 못했습니다. 잠시 후 다시 조회해 주세요.";
  }
  return "판정 정보를 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.";
}
export function isInvalidCursor(error: unknown): boolean {
  return error instanceof ApiError && error.code === "F3_CURSOR_INVALID";
}
export function isDenied(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    ["unauthorized", "forbidden", "notFound"].includes(error.kind)
  );
}
export function useJudgmentTarget(
  type: AnchorType | null,
  id: number | null,
  enabled = true,
  onSessionExpired?: () => void,
) {
  const [target, setTarget] = useState<JudgmentTarget | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const sessionRef = useRef(onSessionExpired);
  sessionRef.current = onSessionExpired;
  const command = useRef<AbortController | null>(null);
  const commandLock = useRef(false);
  useEffect(() => {
    setTarget(null);
    setUnavailable(false);
    setError("");
    setSending(false);
    command.current?.abort();
    commandLock.current = false;
    return () => command.current?.abort();
  }, [type, id, enabled]);
  useEffect(() => {
    if (!enabled || type == null || id == null) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const start = Date.now();
    let interval = 1000;
    setLoading(true);
    setPaused(false);
    const read = async () => {
      try {
        const next = await judgmentApi.target(type, id, controller.signal);
        if (controller.signal.aborted) return;
        setTarget(next);
        setUnavailable(false);
        setError("");
        if (["QUEUED", "RUNNING"].includes(next.generation)) {
          if (Date.now() - start >= 60_000) setPaused(true);
          else {
            timer = setTimeout(() => {
              if (document.hidden) setPaused(true);
              else void poll(next.run_id);
            }, interval);
            interval = Math.min(interval * 2, 5000);
          }
        }
      } catch (cause) {
        if (controller.signal.aborted || isCanceled(cause)) return;
        if (isDenied(cause)) {
          setTarget(null);
          setUnavailable(true);
        }
        setError(judgmentError(cause));
        if (cause instanceof ApiError && cause.kind === "unauthorized")
          sessionRef.current?.();
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    const poll = async (runId: number | null) => {
      if (runId == null) {
        void read();
        return;
      }
      try {
        const state = await f3Transport.getRunStatus(runId, controller.signal);
        if (controller.signal.aborted) return;
        if (isTerminal(state.status)) {
          void read();
          return;
        }
        setTarget((previous) =>
          previous
            ? {
                ...previous,
                generation: state.status === "QUEUED" ? "QUEUED" : "RUNNING",
              }
            : previous,
        );
        if (Date.now() - start >= 60_000 || document.hidden) setPaused(true);
        else {
          timer = setTimeout(() => void poll(runId), interval);
          interval = interval === 1000 ? 2000 : 5000;
        }
      } catch (cause) {
        if (!controller.signal.aborted && !isCanceled(cause)) {
          if (isDenied(cause)) {
            setTarget(null);
            setUnavailable(true);
          }
          setError(judgmentError(cause));
          setPaused(true);
          if (cause instanceof ApiError && cause.kind === "unauthorized")
            sessionRef.current?.();
        }
      }
    };
    void read();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [type, id, enabled, refresh]);
  const reload = useCallback(() => setRefresh((v) => v + 1), []);
  const ensure = async () => {
    if (!enabled || type == null || id == null || commandLock.current) return;
    commandLock.current = true;
    const controller = new AbortController();
    command.current = controller;
    setSending(true);
    setError("");
    try {
      await f3Transport.createRun(
        { anchorType: type, anchorId: id },
        controller.signal,
      );
      if (!controller.signal.aborted) reload();
    } catch (cause) {
      if (!controller.signal.aborted && !isCanceled(cause)) {
        if (isDenied(cause)) {
          setTarget(null);
          setUnavailable(true);
        }
        setError(judgmentError(cause));
        if (cause instanceof ApiError && cause.kind === "unauthorized")
          sessionRef.current?.();
      }
    } finally {
      if (!controller.signal.aborted) {
        commandLock.current = false;
        setSending(false);
      }
    }
  };
  return {
    target,
    unavailable,
    error,
    loading,
    sending,
    paused,
    reload,
    ensure,
  };
}
