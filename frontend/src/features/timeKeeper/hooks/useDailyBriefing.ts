/**
 * 하루 한 번, 업무 시작 시각이 지나면 브리핑을 알린다.
 *
 * 정각 한 번만 노리는 타이머 대신 짧은 주기로 확인한다. 긴 `setTimeout`은 PC가 절전에 들어갔다
 * 깨거나 시스템 시계가 바뀌면 어긋나는데, 사무소 PC는 밤새 꺼져 있다가 아침에 켜지는 것이
 * 보통이라 그 경우가 예외가 아니라 기본이다. 확인은 날짜 비교 두 번이라 비용이 없다.
 */

import { useCallback, useEffect, useRef } from "react";
import {
  createDailyBriefingCoordinator,
  type DailyBriefingCoordinator,
} from "../model/briefing.ts";

/** 확인 주기. 9시 이후 첫 접속은 mount에서 곧바로 걸리므로 이 값이 지연을 좌우하지 않는다. */
const CHECK_INTERVAL_MS = 60_000;

export interface DailyBriefingOptions {
  enabled: boolean;
  /**
   * 브리핑 조회를 시작할 때 업무일 키와 함께 한 번 호출된다.
   */
  onDue: (businessDateKey: string) => void;
}

export interface DailyBriefingControl {
  complete: (businessDateKey: string) => void;
  fail: (businessDateKey: string) => void;
}

export function useDailyBriefing({ enabled, onDue }: DailyBriefingOptions): DailyBriefingControl {
  // 콜백이 매 렌더마다 새로 만들어져도 확인 주기를 다시 걸지 않는다.
  const callback = useRef(onDue);
  callback.current = onDue;
  const coordinator = useRef<DailyBriefingCoordinator | null>(null);
  if (coordinator.current == null) coordinator.current = createDailyBriefingCoordinator();

  const complete = useCallback((key: string) => coordinator.current?.complete(key), []);
  const fail = useCallback((key: string) => coordinator.current?.fail(key), []);

  useEffect(() => {
    if (!enabled) {
      coordinator.current?.cancelPending();
      return undefined;
    }

    const check = () => {
      const key = coordinator.current?.begin(new Date()) ?? null;
      if (key == null) return;
      try {
        callback.current(key);
      } catch (cause) {
        coordinator.current?.fail(key);
        throw cause;
      }
    };

    check();
    const timer = setInterval(check, CHECK_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [enabled]);

  return { complete, fail };
}
