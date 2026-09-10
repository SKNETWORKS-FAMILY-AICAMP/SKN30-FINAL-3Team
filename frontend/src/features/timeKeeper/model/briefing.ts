/**
 * 아침 브리핑을 언제 띄울지.
 *
 * 이 판단은 브라우저가 한다. 서버에 스케줄러를 두지 않는 이유는 F3 설계 원칙 4가 정리한 것과
 * 같다 — 정기 실행을 서버에 두면 그 실행만을 위한 쿼터·이월·재시도 장치가 계속 따라붙는다.
 * 만기 목록은 그냥 조회이므로 "9시가 지났고 오늘 아직 안 봤으면 연다"로 충분하다.
 *
 * 기준 시각은 중개사무소 시간대다. 브라우저 로케일을 그대로 쓰면 출장 중이거나 OS 시간대가
 * 다른 PC에서 브리핑이 엉뚱한 시각에 뜬다. 대한민국은 서머타임이 없어 고정 오프셋으로 맞다.
 */

/** 업무 시작 시각. 사무소마다 다르면 설정으로 올릴 자리다. */
export const BRIEFING_HOUR = 9;

const KST_OFFSET_MINUTES = 9 * 60;
const STORAGE_KEY = "time-keeper.last-briefing";

/** 중개사무소 시간대로 옮긴 시각. Date 자체는 UTC 순간이므로 표시용으로만 쓴다. */
function inBusinessTimezone(now: Date): Date {
  return new Date(now.getTime() + KST_OFFSET_MINUTES * 60_000);
}

/** 업무일 키(YYYY-MM-DD). 하루에 한 번만 띄웠는지 판단하는 단위다. */
export function businessDateKey(now: Date): string {
  return inBusinessTimezone(now).toISOString().slice(0, 10);
}

export function businessHour(now: Date): number {
  return inBusinessTimezone(now).getUTCHours();
}

/**
 * 지금 브리핑을 띄워야 하는가.
 *
 * 9시 정각에 화면이 켜져 있지 않아도 그날 처음 접속한 순간에 뜬다. 사무소 PC는 아침에
 * 켜지므로, 정각에만 띄우면 브리핑이 대부분의 날에 사라진다.
 */
export function isBriefingDue(now: Date, lastShownKey: string | null): boolean {
  if (businessHour(now) < BRIEFING_HOUR) return false;
  return lastShownKey !== businessDateKey(now);
}

/**
 * 마지막으로 브리핑을 띄운 업무일.
 *
 * 브라우저 저장소는 사생활 보호 모드나 저장 차단 설정에서 접근 자체가 예외를 던진다. 읽지
 * 못하면 "아직 안 봤다"로 본다. 하루에 한 번 더 뜨는 쪽이 아예 뜨지 않는 것보다 낫다.
 */
export function readLastBriefing(storage: Storage | undefined = globalStorage()): string | null {
  try {
    return storage?.getItem(STORAGE_KEY) ?? null;
  } catch {
    return null;
  }
}

export function writeLastBriefing(
  key: string,
  storage: Storage | undefined = globalStorage(),
): void {
  try {
    storage?.setItem(STORAGE_KEY, key);
  } catch {
    // 저장하지 못해도 브리핑 자체는 떠야 한다. 다음 접속에서 한 번 더 뜨는 것으로 끝난다.
  }
}

export interface DailyBriefingCoordinator {
  /** 지금 새 브리핑 조회를 시작해야 하면 그 업무일을 반환한다. */
  begin(now: Date): string | null;
  /** 해당 업무일의 조회와 표시 대상 확인이 성공적으로 끝났음을 기록한다. */
  complete(key: string): void;
  /** 조회 실패를 알리고 같은 업무일을 다시 시도할 수 있게 한다. */
  fail(key: string): void;
  /** 기능이 비활성화될 때 끝나지 않은 시도를 해제한다. */
  cancelPending(): void;
}

/**
 * 브리핑 조회 한 번의 수명주기.
 *
 * due 판단만으로는 오늘 기록을 쓰지 않는다. 실제 일정 조회가 성공하고 표시 대상 유무까지
 * 확인한 뒤 ``complete``가 호출되어야 소진한다. 저장소가 막혀도 현재 탭에서는 완료 업무일을
 * 기억해 1분마다 같은 브리핑을 다시 열지 않는다.
 */
export function createDailyBriefingCoordinator(
  storage: Storage | undefined = globalStorage(),
): DailyBriefingCoordinator {
  let pendingKey: string | null = null;
  let completedInMemoryKey: string | null = null;

  return {
    begin(now) {
      const key = businessDateKey(now);
      if (pendingKey === key || completedInMemoryKey === key) return null;
      if (!isBriefingDue(now, readLastBriefing(storage))) return null;
      pendingKey = key;
      return key;
    },
    complete(key) {
      if (pendingKey !== key) return;
      pendingKey = null;
      completedInMemoryKey = key;
      writeLastBriefing(key, storage);
    },
    fail(key) {
      if (pendingKey === key) pendingKey = null;
    },
    cancelPending() {
      pendingKey = null;
    },
  };
}

function globalStorage(): Storage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}
