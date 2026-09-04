/**
 * 일정 응답 런타임 검증.
 *
 * HTTP 200과 계약 준수는 별개다. 특히 `days_until_due`는 화면이 D-day로 그대로 그리는 값이라
 * 숫자가 아니면 조용히 `NaN`이 되어 "D-NaN"이 뜬다. 여기서 계약 오류로 올려보낸다.
 *
 * 반대로 **서버가 열거형으로 고정하지 않은 값은 좁히지 않는다.** `category`는 계약과 일정
 * 테이블이 생기면 늘어나는 어휘이고, `tenancy_status`·`requirement_status`·
 * `contactability_status`는 F1이 아직 값 목록을 확정하지 않았다. 문자열로 받고 아는 값만
 * 화면에서 해석한다.
 */

import {
  asArray,
  asBoolean,
  asNullableNumber,
  asNullableString,
  asNumber,
  asRecord,
  asString,
} from "../../../shared/decode/index.ts";
import type {
  AgendaCategorySummaryDto,
  AgendaContactDto,
  AgendaItemDto,
  AgendaPageDto,
  PartyContactDto,
  PartySummaryDto,
} from "./dto.ts";

function decodePartyContact(value: unknown, path: string): PartyContactDto {
  const row = asRecord(value, path);
  return {
    id: asNumber(row["id"], `${path}.id`),
    contact_method: asString(row["contact_method"], `${path}.contact_method`),
    contact_value: asString(row["contact_value"], `${path}.contact_value`),
    contact_label: asNullableString(row["contact_label"], `${path}.contact_label`),
    is_primary: asBoolean(row["is_primary"], `${path}.is_primary`),
    contactability_status: asString(
      row["contactability_status"],
      `${path}.contactability_status`,
    ),
  };
}

function decodeParty(value: unknown, path: string): PartySummaryDto {
  const row = asRecord(value, path);
  return {
    id: asNumber(row["id"], `${path}.id`),
    party_type: asString(row["party_type"], `${path}.party_type`),
    name: asString(row["name"], `${path}.name`),
    alternate_name: asNullableString(row["alternate_name"], `${path}.alternate_name`),
    privacy_consent_at: asNullableString(row["privacy_consent_at"], `${path}.privacy_consent_at`),
    contacts: asArray(row["contacts"], `${path}.contacts`).map((entry, index) =>
      decodePartyContact(entry, `${path}.contacts[${index}]`),
    ),
  };
}

function decodeContact(value: unknown, path: string): AgendaContactDto {
  const row = asRecord(value, path);
  return {
    role: asNullableString(row["role"], `${path}.role`),
    is_primary: asBoolean(row["is_primary"], `${path}.is_primary`),
    party: decodeParty(row["party"], `${path}.party`),
  };
}

export function decodeAgendaItem(value: unknown, path = "item"): AgendaItemDto {
  const row = asRecord(value, path);
  return {
    category: asString(row["category"], `${path}.category`),
    due_date: asString(row["due_date"], `${path}.due_date`),
    days_until_due: asNumber(row["days_until_due"], `${path}.days_until_due`),
    unit_id: asNullableNumber(row["unit_id"], `${path}.unit_id`),
    listing_id: asNullableNumber(row["listing_id"], `${path}.listing_id`),
    complex_name: asNullableString(row["complex_name"], `${path}.complex_name`),
    building_number: asNullableString(row["building_number"], `${path}.building_number`),
    unit_number: asNullableString(row["unit_number"], `${path}.unit_number`),
    tenancy_status: asNullableString(row["tenancy_status"], `${path}.tenancy_status`),
    requirement_id: asNullableNumber(row["requirement_id"], `${path}.requirement_id`),
    demand_type: asNullableString(row["demand_type"], `${path}.demand_type`),
    requirement_status: asNullableString(row["requirement_status"], `${path}.requirement_status`),
    assigned_user_id: asNullableNumber(row["assigned_user_id"], `${path}.assigned_user_id`),
    last_contact_at: asNullableString(row["last_contact_at"], `${path}.last_contact_at`),
    contacts: asArray(row["contacts"], `${path}.contacts`).map((entry, index) =>
      decodeContact(entry, `${path}.contacts[${index}]`),
    ),
    event_id: asNullableNumber(row["event_id"], `${path}.event_id`),
    title: asNullableString(row["title"], `${path}.title`),
    location: asNullableString(row["location"], `${path}.location`),
  };
}

function decodeCategorySummary(value: unknown, path: string): AgendaCategorySummaryDto {
  const row = asRecord(value, path);
  return {
    category: asString(row["category"], `${path}.category`),
    total: asNumber(row["total"], `${path}.total`),
  };
}

export function decodeAgendaPage(value: unknown): AgendaPageDto {
  const page = asRecord(value, "agenda");
  return {
    items: asArray(page["items"], "agenda.items").map((entry, index) =>
      decodeAgendaItem(entry, `agenda.items[${index}]`),
    ),
    categories: asArray(page["categories"], "agenda.categories").map((entry, index) =>
      decodeCategorySummary(entry, `agenda.categories[${index}]`),
    ),
    total: asNumber(page["total"], "agenda.total"),
    limit: asNumber(page["limit"], "agenda.limit"),
    offset: asNumber(page["offset"], "agenda.offset"),
    as_of: asString(page["as_of"], "agenda.as_of"),
    within_days: asNumber(page["within_days"], "agenda.within_days"),
    overdue_days: asNumber(page["overdue_days"], "agenda.overdue_days"),
    per_category_limit: asNumber(page["per_category_limit"], "agenda.per_category_limit"),
  };
}
