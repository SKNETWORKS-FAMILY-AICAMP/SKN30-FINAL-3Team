/**
 * 상담 유형 → 장부 판정 테스트.
 *
 * 신규 음성메모 접수는 이 판정 하나로 어느 장부에 행이 생길지가 갈린다. 여기서
 * 매도·매수를 잘못 가르면 손님 정보가 매물장에 들어가는 식으로 잘못된 장부에 기록된다.
 *
 * 매도·매수 의뢰가 아닌 유형에서 한쪽 장부를 임의로 고르지 않는 것도 함께 확인한다.
 * 계약상 그 유형들은 어느 장부에서도 필드 제안을 만들지 않아 판정에 근거가 없다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { LEDGER_LABEL, routeConsultation } from "../src/features/f2/model/consultationRouting.ts";

test("매도의뢰는 매물장으로 간다", () => {
  assert.equal(routeConsultation("매도의뢰"), "property");
});

test("매수문의는 구입장으로 간다", () => {
  assert.equal(routeConsultation("매수문의"), "buyer");
});

test("화면에서 매수의뢰로 불려 온 표기도 구입장으로 받는다", () => {
  assert.equal(routeConsultation("매수의뢰"), "buyer");
});

test("공동중개와 단순문의는 장부를 단정하지 않는다", () => {
  assert.equal(routeConsultation("공동중개"), null);
  assert.equal(routeConsultation("단순문의"), null);
});

test("계약에 없는 값이 와도 장부를 추측하지 않는다", () => {
  assert.equal(routeConsultation("임대차상담"), null);
  assert.equal(routeConsultation(""), null);
});

test("앞뒤 공백은 판정을 막지 않는다", () => {
  assert.equal(routeConsultation("  매도의뢰 "), "property");
});

test("장부 표기는 사용자에게 보이는 이름을 쓴다", () => {
  assert.equal(LEDGER_LABEL.property, "매물장");
  assert.equal(LEDGER_LABEL.buyer, "구입장");
});
