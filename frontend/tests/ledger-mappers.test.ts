/**
 * 장부 경계 변환 테스트.
 *
 * DB 연동에서 값이 실제로 깨지는 곳은 표시 문자열 ↔ 저장 값 변환이다.
 * 화면을 띄우지 않고 이 변환만 빠르게 검증한다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { formatMoney, formatMoneyPair, parseMoney, parseMoneyPair } from "../src/features/ledger/model/money.ts";
import { formatPyeong, formatPyeongList, parsePyeong, parsePyeongList } from "../src/features/ledger/model/area.ts";
import { addYears, formatTimestampAsDate, parseDate } from "../src/features/ledger/model/dates.ts";
import { formatPhone, formatPhoneInput, isSamePhone, maskPhone, nextPhoneInput, normalizePhone } from "../src/features/ledger/model/phone.ts";
import { LIFECYCLE_STATUS, toCode, toLabel } from "../src/features/ledger/model/codes.ts";
import {
  applyUnitDetail,
  createPropertyDraftRow,
  hasListingValues,
  newInteractionContent,
  toListingCreatePayload,
  toPropertyRow,
  toUnitCreatePayload,
  toUnitUpdatePayload,
} from "../src/features/ledger/model/propertyMapper.ts";
import {
  createBuyerDraftRow,
  parseBudgetRange,
  toBuyerRow,
  toRequirementCreatePayload,
} from "../src/features/ledger/model/buyerMapper.ts";
import {
  createRequirementRowDtos,
  createUnitRowDtos,
  relationsFor,
} from "../src/features/ledger/mock/fixtures.ts";

const EOK = 100_000_000;
const MAN = 10_000;

/* ------------------------------------------------------------------ */
/* 금액 (F1-GR-09)                                                     */
/* ------------------------------------------------------------------ */

test("금액을 억·만 표기로 바꾼다", () => {
  assert.equal(formatMoney(2_150_000_000), "21.5억");
  assert.equal(formatMoney(15 * EOK), "15억");
  assert.equal(formatMoney(380 * MAN), "380만");
  assert.equal(formatMoney(0), "0원");
  assert.equal(formatMoney(null), "");
});

test("표시 금액을 원 단위로 되돌린다", () => {
  assert.equal(parseMoney("21.5억"), 2_150_000_000);
  assert.equal(parseMoney("12억 8,000만"), 1_280_000_000);
  assert.equal(parseMoney("28억선"), 28 * EOK);
  // 숫자가 없으면 null이다. 0과 구분된다.
  assert.equal(parseMoney("협의"), null);
  assert.equal(parseMoney(""), null);
});

test("보증금/차임이 한 칸에 들어와도 앞 값만 읽는다", () => {
  // 합산하면 9억 3,800만이 되어 완전히 다른 금액이 된다.
  assert.equal(parseMoney("9억/380만"), 9 * EOK);
  const pair = parseMoneyPair("9억/380만");
  assert.equal(pair.first, 9 * EOK);
  assert.equal(pair.second, 380 * MAN);
  assert.equal(formatMoneyPair(pair.first, pair.second), "9억 / 380만");
});

test("만 단위로 떨어지는 금액은 손실 없이 왕복한다", () => {
  for (const amount of [1 * EOK, 2_150_000_000, 105_000_000, 380 * MAN, 12 * EOK + 3456 * MAN]) {
    assert.equal(parseMoney(formatMoney(amount)), amount, `${amount}원이 왕복에서 달라졌습니다.`);
  }
});

/* ------------------------------------------------------------------ */
/* 평형·예산·날짜·연락처                                                */
/* ------------------------------------------------------------------ */

test("평형 단일 값과 복수 값을 모두 다룬다", () => {
  assert.equal(formatPyeong(33), "33평");
  assert.equal(parsePyeong("33평"), 33);
  // F1-DM-12: 희망 평형 복수 입력
  assert.deepEqual(parsePyeongList("25 33평"), [25, 33]);
  assert.equal(formatPyeongList([25, 33]), "25 33평");
});

test("예산 원문을 하한·상한으로 읽는다", () => {
  assert.deepEqual(parseBudgetRange("12억 이하"), { min: null, max: 12 * EOK });
  assert.deepEqual(parseBudgetRange("20억 이상"), { min: 20 * EOK, max: null });
  assert.deepEqual(parseBudgetRange("28억선"), { min: null, max: 28 * EOK });
  // "24~28억"의 24는 24원이 아니라 24억이다.
  assert.deepEqual(parseBudgetRange("24~28억"), { min: 24 * EOK, max: 28 * EOK });
  assert.deepEqual(parseBudgetRange("협의"), { min: null, max: null });
});

test("날짜와 연락처를 안전하게 다룬다", () => {
  assert.equal(parseDate("2027-07-26"), "2027-07-26");
  assert.equal(parseDate(""), null);
  assert.equal(parseDate("2027/07/26"), null);
  // 주택임대차 기본 2년 (F1-DM-10)
  assert.equal(addYears("2026-08-17", 2), "2028-08-17");
  assert.equal(formatTimestampAsDate("잘못된 값"), "");

  assert.equal(normalizePhone("010-0000-9009"), "01000009009");
  assert.equal(formatPhone("01000009009"), "010-0000-9009");
  // 규칙을 벗어난 값은 버리지 않는다
  assert.equal(formatPhone("내선 1234"), "내선 1234");
  assert.equal(maskPhone("010-0000-9009"), "010-****-9009");
  assert.equal(isSamePhone("010-0000-9009", "01000009009"), true);
});

test("모르는 코드가 와도 값을 잃지 않는다", () => {
  assert.equal(toLabel(LIFECYCLE_STATUS, "NORMAL"), "일반");
  assert.equal(toCode(LIFECYCLE_STATUS, "일반"), "NORMAL");
  // 표에 없는 코드는 그대로 노출한다. 조용히 빈 값이 되면 안 된다.
  assert.equal(toLabel(LIFECYCLE_STATUS, "SOMETHING_NEW"), "SOMETHING_NEW");
  assert.equal(toLabel(LIFECYCLE_STATUS, null), "");
});

/* ------------------------------------------------------------------ */
/* 매물장 매퍼                                                          */
/* ------------------------------------------------------------------ */

/** 매매 매물이 붙은 세대를 시드에서 고른다. */
function saleUnit() {
  const unit = createUnitRowDtos(8).find((row) => row.current_listing?.is_sale_available === true);
  assert.ok(unit != null, "매매 매물이 있는 시드를 찾지 못했습니다.");
  return unit;
}

test("매물장 DTO를 화면 행으로 바꾼다", () => {
  const dto = saleUnit();
  const row = toPropertyRow(dto, "김이순");

  assert.equal(row.id, String(dto.id));
  assert.equal(row.serverId, dto.id);
  assert.equal(row.saveState, "저장 완료");
  assert.equal(row.complex, dto.complex.name);
  assert.equal(row.area, formatPyeong(dto.pyeong));
  assert.equal(row.listingType, "매매");
  assert.equal(row.saleFlag, "Y");
  assert.equal(row.salePrice, formatMoney(dto.current_listing?.sale_price ?? null));
  assert.equal(row.price, row.salePrice);
  assert.equal(row.assignee, "김이순");
  // 세대와 매물 건은 row_version을 각각 가진다.
  assert.equal(row.rowVersion, dto.row_version);
  assert.equal(row.listingRowVersion, dto.current_listing?.row_version);
});

test("목록 행에는 인물과 상담 로그가 없다", () => {
  // 계약상 목록 응답에 포함되지 않는다. 상세를 열어야 채워진다.
  const row = toPropertyRow(saleUnit());
  assert.equal(row.owner, "");
  assert.equal(row.log, "");
  assert.equal(row.partiesLoaded, false);
});

test("상세를 적용하면 공동명의가 한 행으로 접힌다", () => {
  // F1-GR-06: 명의자가 2인 이상이어도 세대당 1행
  const unit = createUnitRowDtos(30)[26];
  assert.ok(unit != null);
  const relations = relationsFor(unit.id);
  const owners = relations.filter((relation) => relation.role === "OWNER");
  const row = applyUnitDetail(toPropertyRow(unit), {
    unit,
    listings: [],
    parties: relations,
  });

  assert.equal(row.partiesLoaded, true);
  assert.equal(row.owner, owners.map((relation) => relation.party.name).join(", "));
  assert.equal(row.isCoOwned, owners.length > 1);
});

test("매물이 없는 세대도 행으로 표시한다", () => {
  // F1-GR-01: 매매·전세·월세 칸이 모두 빈 행이 다수 존재하는 것이 정상이다
  const unit = createUnitRowDtos(8).find((row) => row.current_listing == null);
  assert.ok(unit != null);
  const row = toPropertyRow(unit);
  assert.equal(row.listingType, "");
  assert.equal(row.salePrice, "");
  assert.equal(row.listingId, null);
  assert.equal(hasListingValues(row), false);
});

test("세대 생성 요청은 필수값이 없으면 만들지 않는다", () => {
  // 계약상 complex_id와 unit_number가 서버 필수값이다.
  const draft = createPropertyDraftRow("DRAFT-1");
  assert.equal(toUnitCreatePayload(draft), null);

  const filled = { ...draft, complexId: 1, unit: "203", area: "33평", direction: "남향" };
  const payload = toUnitCreatePayload(filled);
  assert.ok(payload != null);
  assert.equal(payload.complex_id, 1);
  assert.equal(payload.unit_number, "203");
  assert.equal(payload.pyeong, 33);
  assert.equal(payload.orientation, "SOUTH");
});

test("세대 수정 요청은 row_version을 반드시 싣는다", () => {
  const row = toPropertyRow(saleUnit());
  const payload = toUnitUpdatePayload(row);
  assert.ok(payload != null);
  assert.equal(payload.row_version, row.rowVersion);
  assert.equal(payload.lifecycle_status, "NORMAL");
});

test("매물 건 요청은 금액을 원 단위로 되돌린다", () => {
  const dto = saleUnit();
  const row = toPropertyRow(dto);
  const payload = toListingCreatePayload(row);
  assert.equal(payload.is_sale_available, true);
  assert.equal(payload.sale_price, dto.current_listing?.sale_price);
  assert.equal(payload.is_jeonse_available, false);
});

test("상담 로그는 바뀌었을 때만 새 로그로 보낸다", () => {
  // client_interaction은 추가 전용이므로 같은 내용이 중복 적재되면 안 된다.
  assert.equal(newInteractionContent("같음", "같음"), null);
  assert.equal(newInteractionContent("  같음  ", "같음"), null);
  assert.equal(newInteractionContent("", null), null);
  assert.equal(newInteractionContent("새 내용", "이전"), "새 내용");
});

/* ------------------------------------------------------------------ */
/* 구입장 매퍼                                                          */
/* ------------------------------------------------------------------ */

test("구입장은 원문을 우선 표시한다", () => {
  // F1-DM-11: "28억선"을 "28억"으로 바꿔 표시하면 뉘앙스를 잃는다
  const dto = createRequirementRowDtos(4)[0];
  assert.ok(dto != null);
  const row = toBuyerRow(dto);

  assert.equal(row.budget, dto.budget_raw_text);
  assert.equal(row.category, "매수");
  assert.equal(row.buyer, dto.party.alternate_name);
  // 진행단계와 완료여부는 별개 필드다(F1-DM-13)
  assert.equal(row.stage, dto.workflow_stage);
  assert.equal(row.completion, dto.status === "COMPLETED" ? "완료" : "진행");
  // 접수일과 최종접촉일은 분리되어 있다(F1-DM-07)
  assert.equal(row.date, dto.received_at);
  assert.match(row.lastContact, /^\d{4}-\d{2}-\d{2}$/);
});

test("희망 단지는 목록 응답에 없다", () => {
  // 상세(desired_complexes)에서만 온다.
  const dto = createRequirementRowDtos(2)[0];
  assert.ok(dto != null);
  assert.equal(toBuyerRow(dto).complex, "");
});

test("인물이 없는 구입장은 저장 요청을 만들지 않는다", () => {
  // 계약상 party_id가 필수인데 인물 생성 엔드포인트가 없다.
  const draft = createBuyerDraftRow("BUYER-DRAFT-1");
  assert.equal(toRequirementCreatePayload(draft), null);

  const withParty = { ...draft, partyId: 500, budget: "28억선", area: "25 33평" };
  const payload = toRequirementCreatePayload(withParty);
  assert.ok(payload != null);
  assert.equal(payload.party_id, 500);
  assert.equal(payload.demand_type, "BUY");
  // 원문과 파싱값이 함께 실린다
  assert.equal(payload.budget_raw_text, "28억선");
  assert.equal(payload.max_budget_amount, 28 * EOK);
  assert.deepEqual(payload.desired_pyeongs, [25, 33]);
});


test("전화번호 입력은 타이핑 도중에도 하이픈으로 끊는다", () => {
  assert.equal(formatPhoneInput("010"), "010");
  assert.equal(formatPhoneInput("0101234"), "010-1234");
  assert.equal(formatPhoneInput("01012345678"), "010-1234-5678");
  assert.equal(formatPhoneInput("0212345678"), "02-1234-5678");
  assert.equal(formatPhoneInput(""), "");
});

test("규칙을 벗어난 연락처는 손대지 않는다", () => {
  // 내선·국제번호는 실제 장부에 섞여 있다. 형식을 강제하면 적을 자리가 없어진다.
  assert.equal(formatPhoneInput("+82 10 1234 5678"), "+82 10 1234 5678");
  assert.equal(formatPhoneInput("내선 302"), "내선 302");
});

test("지우는 중에는 형식을 다시 붙이지 않는다", () => {
  // 하이픈이 곧바로 되붙으면 백스페이스가 먹지 않는 것처럼 보인다.
  assert.equal(nextPhoneInput("010-1234-5678", "010-1234-567"), "010-1234-567");
  assert.equal(nextPhoneInput("010-1234", "010-12345"), "010-1234-5");
});
