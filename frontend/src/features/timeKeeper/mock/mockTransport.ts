/**
 * 백엔드 없이 화면을 확인하기 위한 일정 데이터.
 *
 * 팀 공통 기본값이 `VITE_LEDGER_SOURCE=mock`이므로 이 구현이 없으면 알림이 늘 오류 상태가 된다.
 *
 * 날짜는 고정 문자열이 아니라 오늘 기준으로 만든다. 고정해 두면 며칠만 지나도 전부 "지남"이
 * 되어 D-day 표시와 정렬을 확인할 수 없다.
 */

import { APP_ENV } from "../../../config/env.ts";
import type { AgendaItemDto, AgendaPageDto, PartyContactDto } from "../model/dto.ts";
import type { TimeKeeperTransport } from "../api/transport.ts";

function isoDate(offsetDays: number): string {
  const moment = new Date();
  moment.setHours(12, 0, 0, 0);
  moment.setDate(moment.getDate() + offsetDays);
  return moment.toISOString().slice(0, 10);
}

function phone(value: string): PartyContactDto {
  return {
    id: Number(value.replace(/\D/g, "").slice(-6)),
    contact_method: "PHONE",
    contact_value: value,
    contact_label: null,
    is_primary: true,
    contactability_status: "UNKNOWN",
  };
}

interface MockParty {
  role: string | null;
  name: string;
  phone: string;
}

function base(category: string, daysUntilDue: number, parties: MockParty[]): AgendaItemDto {
  return {
    category,
    due_date: isoDate(daysUntilDue),
    days_until_due: daysUntilDue,
    unit_id: null,
    listing_id: null,
    complex_name: null,
    building_number: null,
    unit_number: null,
    tenancy_status: null,
    requirement_id: null,
    demand_type: null,
    requirement_status: null,
    assigned_user_id: null,
    last_contact_at: null,
    contacts: parties.map((party, index) => ({
      role: party.role,
      is_primary: index === 0,
      party: {
        id: index + 1,
        party_type: "PERSON",
        name: party.name,
        alternate_name: null,
        privacy_consent_at: new Date().toISOString(),
        contacts: [phone(party.phone)],
      },
    })),
  };
}

function unitItem(
  category: string,
  daysUntilDue: number,
  building: string,
  unit: string,
  parties: MockParty[],
): AgendaItemDto {
  return {
    ...base(category, daysUntilDue, parties),
    unit_id: Number(`${building}${unit}`),
    complex_name: "헬리오시티",
    building_number: building,
    unit_number: unit,
    tenancy_status: "입주",
  };
}

function clientItem(
  category: string,
  daysUntilDue: number,
  requirementId: number,
  name: string,
  value: string,
): AgendaItemDto {
  return {
    ...base(category, daysUntilDue, [{ role: null, name, phone: value }]),
    requirement_id: requirementId,
    demand_type: "매수",
    requirement_status: "ACTIVE",
  };
}

/** 기한이 이른 순. 지난 건, 오늘, 앞으로가 모두 한 번씩 나오게 둔다. */
const ITEMS: readonly AgendaItemDto[] = [
  unitItem("TENANCY_EXPIRY", -2, "101", "1503", [
    { role: "TENANT", name: "박임차", phone: "010-2345-6789" },
  ]),
  clientItem("CLIENT_RECONTACT", 0, 41, "이손님", "010-3456-7890"),
  {
    ...unitItem("LISTING_REVALIDATION", 4, "103", "902", [
      { role: "LANDLORD", name: "김임대", phone: "010-1234-5678" },
    ]),
    listing_id: 9021,
  },
  clientItem("MOVE_IN", 12, 44, "정손님", "010-7890-1234"),
  unitItem("LISTING_RECONTACT", 18, "102", "204", [
    { role: "LANDLORD", name: "한임대", phone: "010-6789-0123" },
  ]),
  clientItem("CLIENT_TENANCY_EXPIRY", 31, 58, "최손님", "010-5678-9012"),
  clientItem("REQUEST_EXPIRY", 62, 58, "최손님", "010-5678-9012"),
];

export const mockTransport: TimeKeeperTransport = {
  async listAgenda(query) {
    await new Promise((resolve) => setTimeout(resolve, APP_ENV.mockLatencyMs));

    const withinDays = query.withinDays ?? 90;
    const overdueDays = query.overdueDays ?? 7;
    const matched = ITEMS.filter(
      (item) => item.days_until_due >= -overdueDays && item.days_until_due <= withinDays,
    );
    const perCategoryLimit = query.perCategoryLimit ?? 3;
    const offset = query.offset ?? 0;
    const limit = query.limit ?? 50;

    // 서버와 같은 규칙으로 종류마다 앞에서 몇 건씩만 남긴다.
    const used = new Map<string, number>();
    const capped = matched.filter((item) => {
      const taken = used.get(item.category) ?? 0;
      if (taken >= perCategoryLimit) return false;
      used.set(item.category, taken + 1);
      return true;
    });

    // 0건인 종류는 실리지 않는다. 서버 응답과 같은 성질을 mock에서도 지킨다.
    const totals = new Map<string, number>();
    for (const item of matched) totals.set(item.category, (totals.get(item.category) ?? 0) + 1);

    return {
      items: capped.slice(offset, offset + limit),
      categories: [...totals.entries()]
        .map(([category, total]) => ({ category, total }))
        .sort((left, right) => left.category.localeCompare(right.category)),
      total: matched.length,
      limit,
      offset,
      as_of: isoDate(0),
      within_days: withinDays,
      overdue_days: overdueDays,
      per_category_limit: perCategoryLimit,
    } satisfies AgendaPageDto;
  },
};
