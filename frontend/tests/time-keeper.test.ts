/**
 * Time Keeper 경계 테스트.
 *
 * 화면을 띄우지 않고 두 가지만 본다. 서버 응답을 검증 없이 통과시키지 않는지, 그리고 목록에
 * 세우는 문자열이 종류와 대상에 따라 제대로 갈리는지다.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { decodeAgendaItem, decodeAgendaPage } from "../src/features/timeKeeper/model/decode.ts";
import {
  agendaActionLabel,
  groupAgenda,
  hiddenCount,
  agendaCategoryLabel,
  agendaItemKey,
  agendaTargetLabel,
  dDayLabel,
  hasPrivacyConsent,
  isNeglected,
  isUrgent,
  neglectedDismissKey,
  primaryPhone,
  roleLabel,
  visibleAgendaTotal,
} from "../src/features/timeKeeper/model/viewModel.ts";
import { KNOWN_AGENDA_CATEGORIES } from "../src/features/timeKeeper/model/dto.ts";
import type { AgendaContactDto, AgendaItemDto } from "../src/features/timeKeeper/model/dto.ts";

function contact(overrides: Partial<AgendaContactDto> = {}): AgendaContactDto {
  return {
    role: "LANDLORD",
    is_primary: true,
    party: {
      id: 1,
      party_type: "PERSON",
      name: "김임대",
      alternate_name: null,
      privacy_consent_at: "2026-01-01T00:00:00Z",
      contacts: [
        {
          id: 11,
          contact_method: "PHONE",
          contact_value: "010-1234-5678",
          contact_label: null,
          is_primary: true,
          contactability_status: "UNKNOWN",
        },
      ],
    },
    ...overrides,
  };
}

function unitItem(overrides: Partial<AgendaItemDto> = {}): AgendaItemDto {
  return {
    category: "TENANCY_EXPIRY",
    due_date: "2026-11-30",
    days_until_due: 30,
    unit_id: 7,
    listing_id: null,
    complex_name: "헬리오시티",
    building_number: "101",
    unit_number: "1503",
    tenancy_status: "입주",
    requirement_id: null,
    demand_type: null,
    requirement_status: null,
    assigned_user_id: null,
    last_contact_at: null,
    contacts: [contact()],
    ...overrides,
  };
}

test("계약과 다른 응답은 계약 오류로 올린다", () => {
  // days_until_due가 문자열이면 화면이 그대로 "D-NaN"을 그린다.
  assert.throws(() => decodeAgendaItem({ ...unitItem(), days_until_due: "30" }), /days_until_due/);
  assert.throws(() => decodeAgendaItem({ ...unitItem(), contacts: null }), /contacts/);
  assert.throws(() => decodeAgendaItem({ ...unitItem(), due_date: 20261130 }), /due_date/);
  assert.throws(() => decodeAgendaPage({ items: [], categories: [], total: "3" }), /total/);
  assert.throws(() => decodeAgendaPage({ items: [], categories: null }), /categories/);
});

test("계약을 지킨 응답은 필드를 잃지 않고 통과한다", () => {
  const page = decodeAgendaPage({
    items: [unitItem()],
    categories: [{ category: "TENANCY_EXPIRY", total: 1 }],
    total: 1,
    limit: 50,
    offset: 0,
    as_of: "2026-10-31",
    within_days: 90,
    overdue_days: 7,
    per_category_limit: 3,
  });

  assert.equal(page.total, 1);
  assert.equal(page.as_of, "2026-10-31");
  assert.equal(page.items[0]?.unit_number, "1503");
  assert.equal(page.items[0]?.contacts[0]?.party.name, "김임대");
  assert.deepEqual(page.categories, [{ category: "TENANCY_EXPIRY", total: 1 }]);
});

test("해당되는 내용이 없는 종류는 묶음 자체가 생기지 않는다", () => {
  // 임대차 만기 2건만 있는 날. 재연락·입주일 같은 나머지 종류는 흔적도 남기지 않는다.
  const groups = groupAgenda(
    [unitItem({ unit_id: 1 }), unitItem({ unit_id: 2, days_until_due: 40 })],
    [{ category: "TENANCY_EXPIRY", total: 2 }],
  );

  assert.equal(groups.length, 1);
  assert.equal(groups[0]?.category, "TENANCY_EXPIRY");
  assert.equal(groups[0]?.total, 2);
  assert.equal(groups[0]?.items.length, 2);
  assert.equal(hiddenCount(groups[0]!), 0);
});

test("아무것도 없으면 묶음이 하나도 나오지 않는다", () => {
  assert.deepEqual(groupAgenda([], []), []);
});

test("묶음 순서는 종류 이름이 아니라 급한 순을 따른다", () => {
  // 서버가 이미 기한 순으로 보내므로 먼저 나온 종류가 더 급한 종류다.
  const groups = groupAgenda(
    [
      unitItem({ category: "LISTING_RECONTACT", days_until_due: -1 }),
      unitItem({ category: "TENANCY_EXPIRY", days_until_due: 12 }),
    ],
    [
      { category: "LISTING_RECONTACT", total: 1 },
      { category: "TENANCY_EXPIRY", total: 1 },
    ],
  );

  assert.deepEqual(
    groups.map((group) => group.category),
    ["LISTING_RECONTACT", "TENANCY_EXPIRY"],
  );
});

test("상한에 걸려 빠진 건수를 정직하게 알린다", () => {
  const groups = groupAgenda(
    [unitItem({ unit_id: 1 }), unitItem({ unit_id: 2 }), unitItem({ unit_id: 3 })],
    [{ category: "TENANCY_EXPIRY", total: 9 }],
  );

  assert.equal(groups[0]?.items.length, 3);
  assert.equal(hiddenCount(groups[0]!), 6);
});

test("총계가 실린 건수보다 작아도 음수 건수를 만들지 않는다", () => {
  // 조회 사이에 대상이 지워지면 총계가 뒤처질 수 있다. 그때도 "외 -1건"이 뜨면 안 된다.
  const groups = groupAgenda(
    [unitItem({ unit_id: 1 }), unitItem({ unit_id: 2 })],
    [{ category: "TENANCY_EXPIRY", total: 1 }],
  );

  assert.equal(groups[0]?.total, 2);
  assert.equal(hiddenCount(groups[0]!), 0);
});

test("모르는 종류가 와도 화면이 죽지 않는다", () => {
  // 계약·일정 테이블이 생기면 서버 어휘가 늘어난다. 여기서 열거형으로 막으면 그 배포에
  // 화면 전체가 계약 오류가 된다.
  const item = decodeAgendaItem(unitItem({ category: "CONTRACT_SIGNING" }));

  assert.equal(item.category, "CONTRACT_SIGNING");
  // 문구를 모르면 코드를 그대로 보여주고, 행동은 지어내지 않는다.
  assert.equal(agendaCategoryLabel("CONTRACT_SIGNING"), "CONTRACT_SIGNING");
  assert.equal(agendaActionLabel("CONTRACT_SIGNING"), null);
});

test("서버가 열어 둔 상태 문자열은 좁히지 않는다", () => {
  // F1이 아직 값 목록을 확정하지 않았다.
  assert.equal(decodeAgendaItem(unitItem({ tenancy_status: "월환" })).tenancy_status, "월환");
});

test("현재 서버가 내보내는 종류에는 모두 문구와 행동이 있다", () => {
  for (const category of KNOWN_AGENDA_CATEGORIES) {
    assert.notEqual(agendaCategoryLabel(category), category, category);
    assert.notEqual(agendaActionLabel(category), null, category);
  }
});

test("세대는 부동산으로, 손님은 이름으로 세운다", () => {
  assert.equal(agendaTargetLabel(unitItem()), "헬리오시티 101동 1503호");

  const client = unitItem({
    category: "CLIENT_TENANCY_EXPIRY",
    unit_id: null,
    complex_name: null,
    building_number: null,
    unit_number: null,
    requirement_id: 42,
    contacts: [contact({ role: null, party: { ...contact().party, name: "이손님" } })],
  });
  assert.equal(agendaTargetLabel(client), "이손님");
});

test("동 정보가 없는 세대도 있는 값만으로 이름을 만든다", () => {
  assert.equal(agendaTargetLabel(unitItem({ building_number: null })), "헬리오시티 1503호");
});

test("같은 대상이 여러 종류로 걸려도 키가 겹치지 않는다", () => {
  const expiry = unitItem({ category: "TENANCY_EXPIRY" });
  const recontact = unitItem({ category: "LISTING_RECONTACT" });

  assert.notEqual(agendaItemKey(expiry), agendaItemKey(recontact));
});

test("D-day는 지난 건과 오늘을 문구로 구분한다", () => {
  assert.equal(dDayLabel(30), "D-30");
  assert.equal(dDayLabel(0), "오늘");
  assert.equal(dDayLabel(-3), "3일 지남");

  // 색만으로 구분하지 않기 위해 문구와 강조 조건이 같은 기준을 쓴다.
  assert.equal(isUrgent(0), true);
  assert.equal(isUrgent(-3), true);
  assert.equal(isUrgent(1), false);
});

test("종류와 역할은 한국어 업무 표기로 읽는다", () => {
  assert.equal(agendaCategoryLabel("TENANCY_EXPIRY"), "세대 임대차 만기");
  assert.equal(agendaCategoryLabel("MOVE_IN"), "희망 입주일");
  assert.equal(agendaCategoryLabel("LISTING_REVALIDATION"), "매물 조건 재확인");

  assert.equal(roleLabel("LANDLORD"), "임대인");
  assert.equal(roleLabel(null), "손님");
  // 표에 없는 코드는 값을 버리지 않는다.
  assert.equal(roleLabel("GUARANTOR"), "GUARANTOR");
});

test("수신이 막힌 번호는 연락처로 고르지 않는다", () => {
  const blocked = contact({
    party: {
      ...contact().party,
      contacts: [
        {
          id: 12,
          contact_method: "PHONE",
          contact_value: "010-0000-0000",
          contact_label: null,
          is_primary: true,
          contactability_status: "BLOCKED",
        },
        {
          id: 13,
          contact_method: "PHONE",
          contact_value: "010-9999-8888",
          contact_label: null,
          is_primary: false,
          contactability_status: "UNKNOWN",
        },
      ],
    },
  });

  assert.equal(primaryPhone(blocked), "010-9999-8888");
});

test("저장된 날짜 종류는 아무리 지나도 밀린 묶음으로 가지 않는다", () => {
  // TENANCY_EXPIRY 같은 종류는 서버가 이미 되돌아보는 창으로 걸러 보낸다. 여기서 다시
  // 밀린 것으로 취급하면 정상 만기가 "밀린" 묶음에 잘못 섞인다.
  assert.equal(isNeglected(unitItem({ category: "TENANCY_EXPIRY", days_until_due: -400 }), 7), false);
});

test("재연락·재확인은 되돌아보는 기간을 넘겨야만 밀린 것으로 본다", () => {
  const atBoundary = unitItem({ category: "CLIENT_RECONTACT", days_until_due: -7 });
  const pastBoundary = unitItem({ category: "CLIENT_RECONTACT", days_until_due: -8 });
  const wayPast = unitItem({ category: "LISTING_RECONTACT", days_until_due: -370 });

  // 경계값(overdueDays)까지는 "다가오는 일정" 쪽에 남는다. 저장된 날짜 종류의 되돌아보는
  // 창이 양끝을 포함하는 것과 같은 기준이다.
  assert.equal(isNeglected(atBoundary, 7), false);
  assert.equal(isNeglected(pastBoundary, 7), true);
  assert.equal(isNeglected(wayPast, 7), true);
});

test("확인 키는 기한이 바뀌면 함께 바뀐다", () => {
  const first = unitItem({ category: "CLIENT_RECONTACT", due_date: "2026-01-01" });
  const renewed = unitItem({ category: "CLIENT_RECONTACT", due_date: "2026-03-01" });

  // 손님에게 다시 연락하면 서버가 새 기한을 만든다. 예전 확인 기록이 새 기한까지 감추면 안 된다.
  assert.notEqual(neglectedDismissKey(first), neglectedDismissKey(renewed));
});

test("배지 건수는 받아 온 행 중 확인한 만큼만 덜어 낸다", () => {
  const stale = unitItem({ category: "LISTING_RECONTACT", unit_id: 9, days_until_due: -400 });
  const items = [unitItem(), stale];

  assert.equal(
    visibleAgendaTotal(items, 7, 5, () => false),
    5,
    "아무것도 확인하지 않았으면 서버 총계를 그대로 쓴다",
  );
  assert.equal(
    visibleAgendaTotal(items, 7, 5, (key) => key === neglectedDismissKey(stale)),
    4,
    "밀린 한 건을 확인하면 배지에서 그만큼 빠진다",
  );
});

test("배지 건수는 음수로 내려가지 않는다", () => {
  // 조회 사이에 총계가 뒤처지는 경우와 같은 방어다 (총계가 실린 건수보다 작아도 음수를 만들지 않는다).
  const stale = unitItem({ category: "LISTING_RECONTACT", days_until_due: -400 });

  assert.equal(visibleAgendaTotal([stale], 7, 0, () => true), 0);
});

test("번호가 없거나 동의가 없는 인물을 화면이 구분할 수 있다", () => {
  const withoutPhone = contact({ party: { ...contact().party, contacts: [] } });
  assert.equal(primaryPhone(withoutPhone), null);

  assert.equal(hasPrivacyConsent(contact()), true);
  assert.equal(
    hasPrivacyConsent(contact({ party: { ...contact().party, privacy_consent_at: null } })),
    false,
  );
});
