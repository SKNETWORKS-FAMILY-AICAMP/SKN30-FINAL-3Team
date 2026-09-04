/**
 * 일정 한 행을 화면 문자열로.
 *
 * 서버는 장부 목록과 같이 원본 값만 싣는다. 표시 문자열을 서버가 만들면 같은 데이터를 다른
 * 화면에서 다르게 부를 수 없고, 번역이나 표기 변경이 API 변경이 된다.
 *
 * D-day는 서버가 준 `days_until_due`만 쓴다. 브라우저 시계로 다시 계산하면 자정 근처에서
 * 목록의 정렬과 D-day가 서로 어긋난다.
 */

import type {
  AgendaCategory,
  AgendaCategorySummaryDto,
  AgendaContactDto,
  AgendaItemDto,
} from "./dto.ts";

/**
 * 종류별 화면 문구와, 그 일정이 요구하는 행동.
 *
 * 표에 없는 코드는 값을 버리지 않고 코드를 그대로 보여준다. 서버가 종류를 추가해도 화면이
 * 죽지 않고, 배포가 어긋난 사실은 낯선 코드로 드러난다.
 */
const CATEGORY_LABELS: Readonly<Record<string, string>> = {
  TENANCY_EXPIRY: "세대 임대차 만기",
  CLIENT_TENANCY_EXPIRY: "손님 현 거주지 만기",
  REQUEST_EXPIRY: "구입 의뢰 만기",
  MOVE_IN: "희망 입주일",
  LISTING_RECONTACT: "세대 재연락",
  CLIENT_RECONTACT: "손님 재연락",
  LISTING_REVALIDATION: "매물 조건 재확인",
  ETC: "기타",
};

/** 목록에서 한눈에 "무엇을 하는 날인지" 읽히도록 붙이는 짧은 행동 문구. */
const CATEGORY_ACTIONS: Readonly<Record<string, string>> = {
  TENANCY_EXPIRY: "재계약 의사 확인",
  CLIENT_TENANCY_EXPIRY: "이사 계획 확인",
  REQUEST_EXPIRY: "의뢰 연장 확인",
  MOVE_IN: "입주 일정 점검",
  LISTING_RECONTACT: "안부 연락",
  CLIENT_RECONTACT: "안부 연락",
  LISTING_REVALIDATION: "가격·조건 유효성 확인",
};

const ROLE_LABELS: Readonly<Record<string, string>> = {
  LANDLORD: "임대인",
  TENANT: "임차인",
};

export function agendaCategoryLabel(category: AgendaCategory): string {
  return CATEGORY_LABELS[category] ?? category;
}

/** 아는 종류에만 붙인다. 모르는 종류에 행동을 지어내지 않는다. */
export function agendaActionLabel(category: AgendaCategory): string | null {
  return CATEGORY_ACTIONS[category] ?? null;
}

/** 표에 없는 역할 코드는 값을 버리지 않고 그대로 보여준다. */
export function roleLabel(role: string | null): string {
  if (role == null || role === "") return "손님";
  return ROLE_LABELS[role] ?? role;
}

/**
 * 목록 왼쪽에 세우는 대상 이름.
 *
 * 세대는 부동산을, 구입장은 사람을, 캘린더는 사용자가 붙인 일정 제목을 가리킨다. 세대 행에
 * 인물 이름을 세우면 공동명의나 임대인·임차인이 함께 있는 세대에서 누구를 말하는지 흐려진다.
 */
export function agendaTargetLabel(item: AgendaItemDto): string {
  if (item.event_id != null) {
    return item.title == null || item.title === "" ? "일정" : item.title;
  }
  if (item.unit_id != null) {
    const parts = [
      item.complex_name,
      item.building_number == null ? null : `${item.building_number}동`,
      item.unit_number == null ? null : `${item.unit_number}호`,
    ].filter((part): part is string => part != null && part !== "");
    return parts.length === 0 ? "세대" : parts.join(" ");
  }
  const client = item.contacts[0]?.party.name;
  return client == null || client === "" ? "손님" : client;
}

/** 남은 기간. 이미 지난 건은 며칠 지났는지로 읽는다. */
export function dDayLabel(daysUntilDue: number): string {
  if (daysUntilDue === 0) return "오늘";
  if (daysUntilDue < 0) return `${Math.abs(daysUntilDue)}일 지남`;
  return `D-${daysUntilDue}`;
}

/** 이미 지났거나 오늘인 건은 목록에서 먼저 눈에 띄어야 한다. */
export function isUrgent(daysUntilDue: number): boolean {
  return daysUntilDue <= 0;
}

/**
 * 연락할 번호 한 개.
 *
 * 대표 번호를 우선하고, 없으면 처음 등록된 번호를 쓴다. 수신 제한이 표시된 번호는 고르지
 * 않는다. 발송 가능 여부의 최종 판단은 문자 기능이 하지만, 일정 목록이 제한된 번호를 기본으로
 * 내밀면 그 자리에서 잘못 전화하게 된다.
 */
export function primaryPhone(contact: AgendaContactDto): string | null {
  const usable = contact.party.contacts.filter(
    (entry) => entry.contact_method === "PHONE" && entry.contactability_status !== "BLOCKED",
  );
  const preferred = usable.find((entry) => entry.is_primary) ?? usable[0];
  return preferred?.contact_value ?? null;
}

/** 동의가 없는 인물은 연락 대상으로 내세우지 않는다는 표시를 화면이 걸 수 있게 한다. */
export function hasPrivacyConsent(contact: AgendaContactDto): boolean {
  return contact.party.privacy_consent_at != null;
}

/**
 * 목록 안에서 행을 구분하는 안정된 키. 같은 대상이 여러 종류로 걸릴 수 있다.
 *
 * `event_id`를 넣지 않으면 캘린더 행은 세대·구입장 id가 모두 null이라 같은 종류의 캘린더
 * 일정끼리 키가 겹친다.
 */
export function agendaItemKey(item: AgendaItemDto): string {
  return [
    item.category,
    item.unit_id,
    item.listing_id,
    item.requirement_id,
    item.event_id,
  ].join("-");
}

/**
 * 주기로 만드는 재연락·재확인 종류.
 *
 * 서버가 이 종류에는 아래쪽 경계를 두지 않는다 (F4-TK-04·F4-TK-07). "다가오는 일정"과 나란히
 * 두면 1년 전 접촉한 손님이 오늘 만기와 같은 줄에 서므로, 되돌아보는 기간을 넘긴 것만 따로
 * 뗀다.
 */
const NEGLECTABLE_CATEGORIES: ReadonlySet<string> = new Set([
  "LISTING_RECONTACT",
  "CLIENT_RECONTACT",
  "LISTING_REVALIDATION",
]);

/** 되돌아보는 기간을 넘겨 밀린 재연락·재확인인지. 저장된 날짜 종류는 항상 아니다. */
export function isNeglected(item: AgendaItemDto, overdueDays: number): boolean {
  return NEGLECTABLE_CATEGORIES.has(item.category) && item.days_until_due < -overdueDays;
}

/**
 * "확인" 상태를 저장할 때 쓰는 키. 기한(``due_date``)까지 포함한다.
 *
 * 손님에게 다시 연락하면 서버의 ``last_contact_at``이 바뀌어 기한도 새로 생긴다. 키에 기한을
 * 넣어 두면 그 새 기한은 다른 키가 되어 다시 보이고, 확인 기록은 지금 감춘 그 기한에만 남는다.
 */
export function neglectedDismissKey(item: AgendaItemDto): string {
  return `${agendaItemKey(item)}-${item.due_date}`;
}

/**
 * 배지·브리핑에 쓰는 눈에 보이는 건수.
 *
 * 서버의 ``total``은 창 전체의 참값이라 사용자가 "다시 보지 않기"로 감춘 항목도 그대로
 * 세어져 있다. 지금 받아 온 행 중 감춘 만큼만 덜어 낸다 — 상한에 걸려 애초에 받지 못한 행은
 * 셀 방법이 없어 그대로 둔다.
 */
export function visibleAgendaTotal(
  items: readonly AgendaItemDto[],
  overdueDays: number,
  total: number,
  isDismissed: (key: string) => boolean,
): number {
  const dismissedAmongFetched = items.filter(
    (item) => isNeglected(item, overdueDays) && isDismissed(neglectedDismissKey(item)),
  ).length;
  return Math.max(0, total - dismissedAmongFetched);
}

/** 한 종류로 묶인 일정. 창 전체 건수와 실제로 실린 행을 함께 갖는다. */
export interface AgendaGroup {
  category: AgendaCategory;
  /** 창 안의 참 건수. 종류별 상한에 걸려 `items`보다 클 수 있다. */
  total: number;
  items: AgendaItemDto[];
}

/**
 * 받은 행을 종류로 묶는다.
 *
 * **해당되는 내용이 없는 종류는 묶음 자체가 생기지 않는다.** 고정된 8칸을 그려 놓고 빈 칸을
 * "0건"으로 채우면, 대부분이 빈 목록이 되어 실제로 할 일이 있는 줄이 묻힌다.
 *
 * 묶음 순서는 그 안에서 가장 급한 건을 따른다. 종류 이름 순으로 세우면 오늘 지난 건이 한참
 * 아래에 놓인다. 서버가 이미 기한 순으로 보내므로 먼저 나온 종류가 곧 더 급한 종류다.
 */
export function groupAgenda(
  items: readonly AgendaItemDto[],
  categories: readonly AgendaCategorySummaryDto[],
): AgendaGroup[] {
  const totals = new Map(categories.map((entry) => [entry.category, entry.total]));
  const groups = new Map<AgendaCategory, AgendaGroup>();

  for (const item of items) {
    const existing = groups.get(item.category);
    if (existing == null) {
      groups.set(item.category, {
        category: item.category,
        // 총계가 없으면 실린 만큼만 사실로 말한다. 없는 숫자를 지어내지 않는다.
        total: totals.get(item.category) ?? 0,
        items: [item],
      });
    } else {
      existing.items.push(item);
    }
  }

  return [...groups.values()].map((group) => ({
    ...group,
    total: Math.max(group.total, group.items.length),
  }));
}

/** 상한에 걸려 빠진 건수. 0이면 전부 실린 것이다. */
export function hiddenCount(group: AgendaGroup): number {
  return Math.max(0, group.total - group.items.length);
}
