/**
 * 밀린 재연락·재확인의 "다시 보지 않기" 상태.
 *
 * 서버 목록에서는 빼지 않는다 — 지운다는 뜻이 아니라 이 브라우저 화면에서만 감춘다는 뜻이다
 * (F4-TK-04는 "목록에서 빼지 않는다"를 서버 쪽 이야기로 못박는다). 키에 기한이 들어가므로
 * 다시 연락해 기한이 새로 생기면 감춘 기록과 무관하게 다시 보인다.
 *
 * 브라우저 저장소는 사생활 보호 모드에서 접근 자체가 예외를 던진다. 읽기·쓰기 모두 실패해도
 * 이번 세션에서는 메모리에 남은 값으로 "다시 보지 않기"가 계속 동작한다 — 브리핑
 * (`model/briefing.ts`)과 같은 방침이다.
 */

const STORAGE_KEY = "time-keeper.dismissed-neglected";

function globalStorage(): Storage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

function readDismissed(storage: Storage | undefined): ReadonlySet<string> {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    if (raw == null) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((entry): entry is string => typeof entry === "string"));
  } catch {
    return new Set();
  }
}

function writeDismissed(keys: ReadonlySet<string>, storage: Storage | undefined): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify([...keys]));
  } catch {
    // 저장하지 못해도 이번 세션의 메모리 값으로 감춘 상태는 유지된다.
  }
}

export interface DismissedNeglectedStore {
  isDismissed(key: string): boolean;
  dismiss(key: string): void;
}

export function createDismissedNeglectedStore(
  storage: Storage | undefined = globalStorage(),
): DismissedNeglectedStore {
  let dismissed = readDismissed(storage);

  return {
    isDismissed: (key) => dismissed.has(key),
    dismiss: (key) => {
      if (dismissed.has(key)) return;
      dismissed = new Set(dismissed).add(key);
      writeDismissed(dismissed, storage);
    },
  };
}
