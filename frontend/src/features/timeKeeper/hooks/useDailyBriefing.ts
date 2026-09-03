/**
 * 하루 한 번, 업무 시작 시각이 지나면 브리핑을 알린다.
 *
 * 정각 한 번만 노리는 타이머 대신 짧은 주기로 확인한다. 긴 `setTimeout`은 PC가 절전에 들어갔다
 * 깨거나 시스템 시계가 바뀌면 어긋나는데, 사무소 PC는 밤새 꺼져 있다가 아침에 켜지는 것이
 * 보통이라 그 경우가 예외가 아니라 기본이다. 확인은 날짜 비교 두 번이라 비용이 없다.
 */

import { useEffect, useRef } from "react";
import { businessDateKey, isBriefingDue, readLastBriefing, writeLastBriefing } from "../model/briefing.ts";

/** 확인 주기. 9시 이후 첫 접속은 mount에서 곧바로 걸리므로 이 값이 지연을 좌우하지 않는다. */
const CHECK_INTERVAL_MS = 60_000;

export interface DailyBriefingOptions {
  enabled: boolean;
  /**
   * 브리핑을 띄울 때가 되었을 때 한 번 호출된다.
   *
   * 호출 직전에 "오늘 띄웠다"를 저장한다. 실제로 창을 열지는 호출자가 정한다 — 알릴 것이
   * 없는 날까지 매일 빈 창을 띄우면 다음 날부터 아무도 읽지 않는다.
   */
  onDue: () => void;
}

export function useDailyBriefing({ enabled, onDue }: DailyBriefingOptions): void {
  // 콜백이 매 렌더마다 새로 만들어져도 확인 주기를 다시 걸지 않는다.
  const callback = useRef(onDue);
  callback.current = onDue;

  useEffect(() => {
    if (!enabled) return undefined;

    const check = () => {
      const now = new Date();
      if (!isBriefingDue(now, readLastBriefing())) return;
      // 먼저 기록한다. 여기서 실패해 다시 도는 것보다 하루에 한 번을 지키는 쪽이 중요하다.
      writeLastBriefing(businessDateKey(now));
      callback.current();
    };

    check();
    const timer = setInterval(check, CHECK_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [enabled]);
}
