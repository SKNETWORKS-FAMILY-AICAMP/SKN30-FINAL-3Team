/**
 * 아침 브리핑을 언제 띄우는가.
 *
 * 이 판단이 틀리면 브리핑이 하루에 여러 번 뜨거나, 정각에 화면을 켜 두지 않은 날에는 아예
 * 뜨지 않는다. 둘 다 시계와 저장소가 얽혀 눈으로 확인하기 어려우므로 순수 함수로 떼어 검증한다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  BRIEFING_HOUR,
  businessDateKey,
  businessHour,
  isBriefingDue,
  readLastBriefing,
  writeLastBriefing,
} from "../src/features/timeKeeper/model/briefing.ts";

/** 한국 시각을 UTC 순간으로. 브라우저 OS 시간대와 무관하게 같은 결과가 나와야 한다. */
function kst(day: string, hour: number, minute = 0): Date {
  return new Date(`${day}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+09:00`);
}

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

test("업무일과 시각은 사무소 시간대로 읽는다", () => {
  // UTC로 읽으면 아직 전날 23시다. 한국에서는 이미 다음 날 오전 8시다.
  assert.equal(businessDateKey(new Date("2026-09-03T23:00:00Z")), "2026-09-04");
  assert.equal(businessHour(new Date("2026-09-03T23:00:00Z")), 8);

  assert.equal(businessDateKey(kst("2026-09-04", 0, 30)), "2026-09-04");
  assert.equal(businessHour(kst("2026-09-04", 9)), BRIEFING_HOUR);
});

test("업무 시작 전에는 띄우지 않는다", () => {
  assert.equal(isBriefingDue(kst("2026-09-03", 8, 59), null), false);
  assert.equal(isBriefingDue(kst("2026-09-03", 9, 0), null), true);
});

test("9시가 지난 뒤 그날 처음 접속하면 띄운다", () => {
  // 정각에만 띄우면 사무소 PC가 9시 이후에 켜지는 날에는 브리핑이 사라진다.
  assert.equal(isBriefingDue(kst("2026-09-03", 14, 20), null), true);
  assert.equal(isBriefingDue(kst("2026-09-03", 23, 59), "2026-09-02"), true);
});

test("같은 업무일에는 다시 띄우지 않는다", () => {
  assert.equal(isBriefingDue(kst("2026-09-03", 9, 1), "2026-09-03"), false);
  assert.equal(isBriefingDue(kst("2026-09-03", 18, 0), "2026-09-03"), false);
});

test("자정을 넘겨 켜 둔 화면도 다음 날 9시에 다시 띄운다", () => {
  // 어제 브리핑을 본 채 화면을 켜 두었다.
  assert.equal(isBriefingDue(kst("2026-09-04", 3, 0), "2026-09-03"), false);
  assert.equal(isBriefingDue(kst("2026-09-04", 9, 0), "2026-09-03"), true);
});

test("저장소를 읽고 쓴다", () => {
  const storage = memoryStorage();
  assert.equal(readLastBriefing(storage), null);

  writeLastBriefing("2026-09-03", storage);
  assert.equal(readLastBriefing(storage), "2026-09-03");
  assert.equal(isBriefingDue(kst("2026-09-03", 10, 0), readLastBriefing(storage)), false);
});

test("저장소가 막혀 있어도 브리핑이 멈추지 않는다", () => {
  // 사생활 보호 모드나 저장 차단 설정에서는 접근 자체가 예외를 던진다.
  const blocked = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  } as unknown as Storage;

  assert.equal(readLastBriefing(blocked), null);
  assert.doesNotThrow(() => writeLastBriefing("2026-09-03", blocked));
  // 읽지 못하면 "아직 안 봤다"로 본다. 한 번 더 뜨는 쪽이 아예 뜨지 않는 것보다 낫다.
  assert.equal(isBriefingDue(kst("2026-09-03", 9, 30), readLastBriefing(blocked)), true);
});

test("저장소가 없는 실행 환경에서도 읽기가 실패하지 않는다", () => {
  assert.equal(readLastBriefing(undefined), null);
  assert.doesNotThrow(() => writeLastBriefing("2026-09-03", undefined));
});
