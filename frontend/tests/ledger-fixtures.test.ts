/**
 * 모의 데이터 정합성 검사.
 *
 * mock이 실제 DB 제약이나 API 계약을 어기면, 화면이 현실에서 불가능한 상태를 정상으로 학습한다.
 * 여기서 검증하는 것은 화면 동작이 아니라 "이 시드가 실제 스키마와 계약에 맞는가"다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  MOCK_COMPLEXES,
  createRequirementRowDtos,
  createUnitRowDtos,
} from "../src/features/ledger/mock/fixtures.ts";
import {
  decodePropertyUnitRow,
  decodeRequirementRow,
} from "../src/features/ledger/model/decode.ts";
import { toPropertyRow } from "../src/features/ledger/model/propertyMapper.ts";
import { toBuyerRow } from "../src/features/ledger/model/buyerMapper.ts";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** "2026-13-15"처럼 달력에 없는 날짜를 걸러낸다. 형식만 맞고 실재하지 않는 값이 흔한 실수다. */
function isRealDate(value: string): boolean {
  if (!DATE_ONLY.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (year == null || month == null || day == null) return false;
  const parsed = new Date(year, month - 1, day);
  return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === day;
}

test("매물장 시드의 모든 날짜가 실재하는 날짜다", () => {
  for (const row of createUnitRowDtos(400)) {
    for (const value of [row.tenancy_expiry_date, row.current_listing?.received_at ?? null]) {
      if (value == null) continue;
      assert.ok(isRealDate(value), `존재하지 않는 날짜가 있습니다: ${value}`);
    }
  }
});

test("구입장 시드의 모든 날짜가 실재하는 날짜다", () => {
  for (const row of createRequirementRowDtos(60)) {
    for (const value of [row.received_at, row.desired_move_in_date, row.request_expiry_date]) {
      if (value == null) continue;
      assert.ok(isRealDate(value), `존재하지 않는 날짜가 있습니다: ${value}`);
    }
  }
});

test("같은 단지 안에서 동·호가 중복되지 않는다", () => {
  // 실제 스키마의 uq_property_unit_location과 같은 제약이다.
  const seen = new Set<string>();
  for (const row of createUnitRowDtos(1200)) {
    const key = `${row.complex.id}/${row.building_number}/${row.unit_number}`;
    assert.equal(seen.has(key), false, `동·호가 중복됩니다: ${key}`);
    seen.add(key);
  }
});

test("시드가 모든 단지를 사용한다", () => {
  const used = new Set(createUnitRowDtos(40).map((row) => row.complex.id));
  assert.equal(used.size, MOCK_COMPLEXES.length);
});

test("시드가 검증기와 매퍼를 그대로 통과한다", () => {
  // mock과 실제 API가 같은 경로를 지나는지 확인한다. 여기서 걸리면 계약이 어긋난 것이다.
  for (const row of createUnitRowDtos(50)) {
    const decoded = decodePropertyUnitRow(JSON.parse(JSON.stringify(row)));
    const mapped = toPropertyRow(decoded);
    assert.equal(mapped.id, String(row.id));
    assert.equal(mapped.saveState, "저장 완료");
  }

  for (const row of createRequirementRowDtos(20)) {
    const decoded = decodeRequirementRow(JSON.parse(JSON.stringify(row)));
    assert.equal(toBuyerRow(decoded).id, String(row.id));
  }
});

test("NUMERIC 값이 문자열로 와도 검증기가 흡수한다", () => {
  // Pydantic이 Decimal을 JSON 문자열로 직렬화할 수 있다. 여기서 막지 않으면 화면이 깨진다.
  const row = createUnitRowDtos(1)[0];
  assert.ok(row != null);
  const asJson = JSON.parse(JSON.stringify(row)) as Record<string, unknown>;
  asJson["pyeong"] = "33.00";

  const decoded = decodePropertyUnitRow(asJson);
  assert.equal(decoded.pyeong, 33);
  assert.equal(toPropertyRow(decoded).area, "33평");
});

test("매물이 없는 세대가 실제로 존재한다", () => {
  // F1-GR-01: 매물이 아닌 세대도 행으로 표시되어야 하므로 시드에 반드시 섞여 있어야 한다.
  const rows = createUnitRowDtos(40);
  assert.ok(rows.some((row) => row.current_listing == null), "매물 없는 세대가 시드에 없습니다.");
  assert.ok(rows.some((row) => row.current_listing != null), "매물 있는 세대가 시드에 없습니다.");
});

test("연락처가 전부 가짜 대역이다", () => {
  // 규칙으로 생성한 그럴듯한 번호는 우연히 실사용 번호와 겹칠 수 있다.
  for (const row of createRequirementRowDtos(24)) {
    for (const contact of row.party.contacts) {
      assert.match(contact.contact_value, /^010-0000-\d{4}$/, contact.contact_value);
    }
  }
});
