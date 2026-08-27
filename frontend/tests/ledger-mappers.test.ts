/**
 * 장부 경계 변환 테스트.
 *
 * DB 연동에서 값이 실제로 깨지는 곳은 표시 문자열 ↔ 저장 값 변환이다.
 * 화면을 띄우지 않고 이 변환만 빠르게 검증한다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { formatMoney, formatMoneyPair, parseMoney, parseMoneyPair } from "../src/shared/format/money.ts";
import { formatPyeong, formatPyeongList, parsePyeong, parsePyeongList } from "../src/shared/format/area.ts";
import { addYears, formatTimestampAsDate, parseDate } from "../src/features/ledger/model/dates.ts";
import { formatPhone, formatPhoneInput, isSamePhone, maskPhone, nextPhoneInput, normalizePhone } from "../src/features/ledger/model/phone.ts";
import { LIFECYCLE_STATUS, toCode, toLabel } from "../src/features/ledger/model/codes.ts";
import {
  applyServerIdentity,
  applyUnitDetail,
  createPropertyDraftRow,
  hasListingValues,
  newInteractionContent,
  toListingCreatePayload,
  toPartyWritePayload,
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
import { isEmptyDraft } from "../src/features/ledger/model/draft.ts";
import {
  createRequirementRowDtos,
  createUnitRowDtos,
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

test("목록 행이 임대인·임차인 열을 채운다", () => {
  /*
   * 그리드가 임대인·임차인을 고정 열로 갖고 있어 목록 응답이 인물을 함께 싣는다.
   * 이 열이 비면 값이 없는 것인지 아직 안 불러온 것인지 화면에서 구분할 수 없다.
   */
  const unit = createUnitRowDtos(30).find((row) => row.parties.length > 0);
  assert.ok(unit != null);
  const landlords = unit.parties.filter((relation) => relation.role === "LANDLORD");
  const row = toPropertyRow(unit);

  assert.equal(row.partiesLoaded, true);
  assert.equal(row.owner, landlords.map((relation) => relation.party.name).join(", "));
  assert.equal(row.parties.length, unit.parties.length);
});

test("임대인 역할 코드는 LANDLORD다", () => {
  // 서버가 쓰는 코드와 어긋나면 필터가 아무것도 못 골라 임대인 열이 조용히 빈다.
  const unit = createUnitRowDtos(30).find((row) =>
    row.parties.some((relation) => relation.role === "LANDLORD"),
  );
  assert.ok(unit != null);
  assert.notEqual(toPropertyRow(unit).owner, "");
});

test("공동명의는 한 행으로 접힌다", () => {
  // F1-GR-06: 명의자가 2인 이상이어도 세대당 1행
  const unit = createUnitRowDtos(30).find(
    (row) => row.parties.filter((relation) => relation.role === "LANDLORD").length > 1,
  );
  assert.ok(unit != null);
  const landlords = unit.parties.filter((relation) => relation.role === "LANDLORD");
  const row = applyUnitDetail(toPropertyRow(unit), {
    unit,
    listings: [],
    parties: unit.parties,
  });

  assert.equal(row.partiesLoaded, true);
  assert.equal(row.owner, landlords.map((relation) => relation.party.name).join(", "));
  assert.equal(row.isCoOwned, true);
});

test("임대인·임차인 입력이 인물 쓰기 요청으로 나간다", () => {
  /*
   * 이 열들이 payload에 실리지 않으면 저장은 성공하고 값만 사라진다.
   * 화면은 "저장 완료"를 보여주므로 사용자가 손실을 알아차릴 방법이 없다.
   */
  const row = {
    ...createPropertyDraftRow("DRAFT-1"),
    complexId: 1,
    unit: "203",
    owner: "박이서, 송경련",
    ownerPhone: "010-1234-5678",
    tenant: "김임차",
    tenantPhone: "010-2222-3333",
  };

  assert.deepEqual(toPartyWritePayload(row), [
    { role: "LANDLORD", role_index: 1, name: "박이서", phone: "010-1234-5678", is_co_owner: true },
    { role: "LANDLORD", role_index: 2, name: "송경련", phone: null, is_co_owner: true },
    { role: "TENANT", role_index: 1, name: "김임차", phone: "010-2222-3333", is_co_owner: false },
  ]);

  const created = toUnitCreatePayload(row);
  assert.ok(created != null);
  assert.equal(created.parties?.length, 3);
});

test("인물을 비우면 빈 목록을 보내 관계를 끊는다", () => {
  // 보낸 목록이 곧 전체다. 빈 배열은 "인물 없음"이고, 생략은 "건드리지 않음"이다.
  const loaded = { ...createPropertyDraftRow("DRAFT-2"), rowVersion: 3, owner: "", tenant: "" };
  assert.deepEqual(toUnitUpdatePayload(loaded)?.parties, []);

  // 아직 인물을 모르는 행은 보내지 않는다. 빈 배열이면 서버의 임대인이 지워진다.
  const unloaded = { ...loaded, partiesLoaded: false };
  assert.equal(toUnitUpdatePayload(unloaded)?.parties, undefined);
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


test("서버 식별자 반영은 재시도가 같은 레코드를 다시 만들지 않게 한다", () => {
  /*
   * 저장은 세대·매물·상담 로그로 나뉜 여러 요청이다. 세대만 성공하고 뒤가 실패했을 때
   * serverId가 비어 있으면 재시도가 세대를 다시 POST해 중복이 생긴다.
   */
  const draft = createPropertyDraftRow("DRAFT-1");
  assert.equal(draft.serverId, null);

  const afterUnit = applyServerIdentity(draft, { id: 42, row_version: 3 });
  assert.equal(afterUnit.serverId, 42);
  assert.equal(afterUnit.rowVersion, 3);
  // 매물은 아직 만들지 않았으므로 건드리지 않는다.
  assert.equal(afterUnit.listingId, null);

  const afterListing = applyServerIdentity(afterUnit, { id: 42, row_version: 3 }, { id: 7, row_version: 1 });
  assert.equal(afterListing.listingId, 7);
  assert.equal(afterListing.listingRowVersion, 1);
});

/* ------------------------------------------------------------------ */
/* 빈 행 (F1-GR-30, F1-GR-32)                                          */
/* ------------------------------------------------------------------ */

test("행 추가만 하고 닫은 행은 빈 행이다", () => {
  // 값을 하나도 넣지 않은 행은 저장할 것이 없다. 그리드에 남기면 빈 임시저장 행만 쌓인다.
  assert.equal(isEmptyDraft(createPropertyDraftRow("DRAFT-1")), true);
  assert.equal(isEmptyDraft(createBuyerDraftRow("BUYER-DRAFT-1")), true);
});

test("값을 하나라도 적은 행은 빈 행이 아니다", () => {
  assert.equal(isEmptyDraft({ ...createPropertyDraftRow("DRAFT-1"), unit: "301" }), false);
  assert.equal(isEmptyDraft({ ...createPropertyDraftRow("DRAFT-1"), log: "집주인 통화" }), false);
  // 음성메모 접수로 채운 행은 사용자가 다시 열어 저장할 수 있어야 한다.
  assert.equal(isEmptyDraft({ ...createBuyerDraftRow("BUYER-DRAFT-1"), buyer: "김손님" }), false);
});

test("저장 상태와 동기화 상태만으로는 빈 행 판단이 흔들리지 않는다", () => {
  // 저장에 실패해 sync가 남은 빈 행도 여전히 빈 행이다.
  const failed = {
    ...createPropertyDraftRow("DRAFT-1"),
    sync: { status: "failed", reason: "호는 저장 전에 반드시 입력해야 합니다." } as const,
  };
  assert.equal(isEmptyDraft(failed), true);
});

test("서버에 저장된 행은 값이 비어 보여도 빈 행이 아니다", () => {
  // 이미 서버에 있는 레코드는 화면에서 조용히 지우면 안 된다. 삭제는 별도 경로다.
  const saved = { ...createPropertyDraftRow("DRAFT-1"), serverId: 42, rowVersion: 1 };
  assert.equal(isEmptyDraft(saved), false);
});
