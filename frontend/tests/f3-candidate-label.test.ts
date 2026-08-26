/**
 * 후보 표시 이름 조인 테스트.
 *
 * 결과 조회 응답은 후보의 표시 이름을 싣지 않는다. 화면은 이미 불러온 F1 장부에서 찾는데,
 * 여기서 틀리기 쉬운 것이 **어느 식별자로 찾느냐**다. 매물장 행의 서버 식별자는 세대 ID이고
 * 후보 식별자는 매물 건 ID다. 잘못 색인하면 조용히 아무것도 찾지 못하고 화면은 그냥 `매물 #12`가
 * 되어 버그로 보이지 않는다.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EMPTY_LEDGER_INDEX,
  candidateSideOf,
  indexLedgerRows,
  labelFor,
} from "../src/features/f3/model/candidateLabel.ts";
import type { BuyerRow, PropertyRow } from "../src/features/ledger/model/row.ts";

function buyerRow(overrides: Partial<BuyerRow> = {}): BuyerRow {
  return {
    id: "227",
    ledgerType: "buyer",
    rowKind: "buyer",
    serverId: 227,
    rowVersion: 1,
    sync: { status: "synced" },
    customFields: {},
    saveState: "저장 완료",
    buyer: "김정우",
    complex: "래미안 원베일리",
    category: "매수",
    area: "33평",
    phone: "010-0000-0008",
    ...overrides,
  } as BuyerRow;
}

function propertyRow(overrides: Partial<PropertyRow> = {}): PropertyRow {
  return {
    id: "10",
    ledgerType: "property",
    rowKind: "property",
    // 세대 ID와 매물 건 ID는 다른 값이다. 이 테스트의 핵심이다.
    serverId: 10,
    listingId: 555,
    rowVersion: 1,
    sync: { status: "synced" },
    customFields: {},
    saveState: "저장 완료",
    complex: "래미안 원베일리",
    building: "103",
    unit: "1204",
    area: "33평",
    listingType: "매매",
    ownerPhone: "",
    ...overrides,
  } as PropertyRow;
}

test("후보 장부는 앵커의 반대편이다", () => {
  assert.equal(candidateSideOf("LISTING"), "REQUIREMENT");
  assert.equal(candidateSideOf("REQUIREMENT"), "LISTING");
});

test("매물 앵커의 후보는 구입장에서 이름과 연락처를 찾는다", () => {
  const ledger = indexLedgerRows([], [buyerRow()]);

  const label = labelFor(227, "LISTING", ledger);

  assert.equal(label.title, "김정우 · 래미안 원베일리");
  assert.equal(label.subtitle, "매수 · 33평");
  assert.equal(label.phone, "010-0000-0008");
  assert.equal(label.found, true);
});

test("구입장 앵커의 후보는 매물 건 ID로 찾는다", () => {
  const ledger = indexLedgerRows([propertyRow()], []);

  const found = labelFor(555, "REQUIREMENT", ledger);
  assert.equal(found.title, "래미안 원베일리 103동 1204호");
  assert.equal(found.subtitle, "33평 · 매매");
  assert.equal(found.found, true);

  // 세대 ID로는 찾히지 않아야 한다. 찾히면 색인 키를 잘못 잡은 것이다.
  assert.equal(labelFor(10, "REQUIREMENT", ledger).found, false);
});

test("매물 후보의 연락처는 비어 있다", () => {
  const ledger = indexLedgerRows([propertyRow()], []);
  // 매물장 목록 응답에는 인물이 없다. 없는 값을 지어내지 않고 화면이 그 사실을 밝힌다.
  assert.equal(labelFor(555, "REQUIREMENT", ledger).phone, "");
});

test("장부에 없는 후보는 식별자만 보여준다", () => {
  const requirement = labelFor(999, "LISTING", EMPTY_LEDGER_INDEX);
  assert.equal(requirement.title, "구입장 #999");
  assert.equal(requirement.found, false);
  assert.equal(requirement.phone, "");

  // 한쪽 표기를 양쪽에 쓰지 않는다. 손님 상세에서 매물을 "구입장"이라 부르면 안 된다.
  const listing = labelFor(999, "REQUIREMENT", EMPTY_LEDGER_INDEX);
  assert.equal(listing.title, "매물 #999");
});

test("저장되지 않은 행은 색인에 넣지 않는다", () => {
  const ledger = indexLedgerRows(
    [propertyRow({ listingId: null })],
    [buyerRow({ serverId: null })],
  );

  assert.equal(ledger.listings.size, 0);
  assert.equal(ledger.requirements.size, 0);
});

test("값이 비어 있어도 무엇인지 알 수 있게 표기한다", () => {
  const ledger = indexLedgerRows(
    [propertyRow({ complex: "", building: "", unit: "" })],
    [buyerRow({ buyer: "", complex: "" })],
  );

  assert.equal(labelFor(227, "LISTING", ledger).title, "별칭 미입력 · 희망 단지 없음");
  assert.equal(labelFor(555, "REQUIREMENT", ledger).title, "단지 미입력");
});
