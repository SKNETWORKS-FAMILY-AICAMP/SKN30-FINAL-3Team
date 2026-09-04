/**
 * 밀린 재연락·재확인의 "다시 보지 않기" 저장소.
 *
 * 브리핑과 같은 이유로 순수 함수로 뗐다 — 저장소가 막혀도 감춘 상태가 이번 세션에서는
 * 유지되어야 하고, 그 동작은 화면 없이도 확인할 수 있다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { createDismissedNeglectedStore } from "../src/features/timeKeeper/model/dismissed.ts";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(initial));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => void map.set(key, value),
  } as Storage;
}

test("확인하지 않은 키는 감춰지지 않는다", () => {
  const store = createDismissedNeglectedStore(memoryStorage());
  assert.equal(store.isDismissed("CLIENT_RECONTACT-null-null-42-2026-01-01"), false);
});

test("확인한 키는 감춰지고 저장소에 남는다", () => {
  const storage = memoryStorage();
  const store = createDismissedNeglectedStore(storage);
  const key = "CLIENT_RECONTACT-null-null-42-2026-01-01";

  store.dismiss(key);

  assert.equal(store.isDismissed(key), true);
  assert.equal(JSON.parse(storage.getItem("time-keeper.dismissed-neglected") ?? "[]").includes(key), true);
});

test("같은 저장소로 다시 만들면 이전 확인 기록을 읽는다", () => {
  const storage = memoryStorage();
  const key = "LISTING_RECONTACT-9-null-null-2025-08-01";
  createDismissedNeglectedStore(storage).dismiss(key);

  const reopened = createDismissedNeglectedStore(storage);
  assert.equal(reopened.isDismissed(key), true);
});

test("저장소가 막혀 있어도 이번 세션에서는 확인 상태가 유지된다", () => {
  const blocked = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  } as unknown as Storage;
  const store = createDismissedNeglectedStore(blocked);
  const key = "CLIENT_RECONTACT-null-null-7-2026-02-01";

  assert.doesNotThrow(() => store.dismiss(key));
  assert.equal(store.isDismissed(key), true);
});

test("저장소에 손상된 값이 있어도 빈 상태로 시작한다", () => {
  const storage = memoryStorage({ "time-keeper.dismissed-neglected": "{not json" });
  const store = createDismissedNeglectedStore(storage);

  assert.equal(store.isDismissed("아무-키"), false);
});
