/**
 * 음성 메모를 상담 로그에 쌓는 규칙 테스트.
 *
 * 상담 로그는 덮어쓰지 않고 계속 이어 붙는 기록이라, 시각 표기가 빠지거나 형식이 흔들리면
 * 나중에 어느 대목이 언제 들어온 음성 메모인지 되짚을 수 없다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { appendVoiceMemoToLog, formatLogStamp, stampVoiceMemo } from "../src/features/f2/model/consultationLog.ts";

const AT = new Date(2026, 7, 27, 9, 5);

test("시각 표기는 정본 로그 포맷과 같은 두 자리 연도를 쓴다", () => {
  assert.equal(formatLogStamp(AT), "26-08-27 09:05");
});

test("음성 메모 앞에 날짜와 시각을 붙인다", () => {
  assert.equal(stampVoiceMemo("현 임차인 만기 후 입주", AT), "[26-08-27 09:05]현 임차인 만기 후 입주");
});

test("기존 로그가 있으면 새 줄로 이어 붙인다", () => {
  assert.equal(
    appendVoiceMemoToLog("[26-08-26 14:00]첫 상담", "만기일 확인 필요", AT),
    "[26-08-26 14:00]첫 상담\n[26-08-27 09:05]만기일 확인 필요",
  );
});

test("기존 로그가 비어 있으면 앞에 빈 줄을 만들지 않는다", () => {
  assert.equal(appendVoiceMemoToLog("", "첫 상담", AT), "[26-08-27 09:05]첫 상담");
  assert.equal(appendVoiceMemoToLog(null, "첫 상담", AT), "[26-08-27 09:05]첫 상담");
});

test("기존 로그 끝의 빈 줄이 쌓이지 않는다", () => {
  assert.equal(appendVoiceMemoToLog("첫 상담\n\n", "두 번째 상담", AT), "첫 상담\n[26-08-27 09:05]두 번째 상담");
});

test("빈 메모는 시각만 남기지 않고 기존 로그를 그대로 둔다", () => {
  assert.equal(appendVoiceMemoToLog("첫 상담", "   ", AT), "첫 상담");
  assert.equal(appendVoiceMemoToLog("", "", AT), "");
});
