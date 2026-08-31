/**
 * 장부 응답 런타임 검증.
 *
 * 원시 검증기와 `DecodeError`는 `shared/decode`가 소유한다. 여기에는 F1 장부 계약의 DTO를 읽는
 * 도메인 검증기만 둔다. 계약이 바뀌면 이 파일만 따라 바뀐다.
 *
 * 경로와 필드의 정본은 project-wiki `contracts/api.md`의 "F1 장부 계약"이다.
 */

import {
  asArray,
  asBoolean,
  asJsonObject,
  asNullableBoolean,
  asNullableDecimal,
  asNullableNumber,
  asNullableString,
  asNumber,
  asRecord,
  asString,
} from "../../../shared/decode/index.ts";
import type {
  ClientInteractionDto,
  ColumnValuesDto,
  ComplexSummaryDto,
  PageDto,
  PartyContactDto,
  PartySummaryDto,
  PropertyListingDto,
  PropertyRequirementDetailDto,
  PropertyRequirementRowDto,
  PropertyUnitDetailDto,
  PropertyUnitRowDto,
  UnitPartyRelationDto,
} from "./dto.ts";


export function decodeComplexSummary(value: unknown, path = "complex"): ComplexSummaryDto {
  const record = asRecord(value, path);
  return {
    id: asNumber(record["id"], `${path}.id`),
    name: asString(record["name"], `${path}.name`),
    property_type: asString(record["property_type"], `${path}.property_type`),
    road_address: asNullableString(record["road_address"], `${path}.road_address`),
    row_version: typeof record["row_version"] === "number" ? record["row_version"] : 1,
  };
}

function decodePartyContact(value: unknown, path: string): PartyContactDto {
  const record = asRecord(value, path);
  return {
    id: asNumber(record["id"], `${path}.id`),
    contact_method: asString(record["contact_method"], `${path}.contact_method`),
    contact_value: asString(record["contact_value"], `${path}.contact_value`),
    contact_label: asNullableString(record["contact_label"], `${path}.contact_label`),
    is_primary: asBoolean(record["is_primary"], `${path}.is_primary`),
    contactability_status: asString(record["contactability_status"], `${path}.contactability_status`),
  };
}

export function decodePartySummary(value: unknown, path = "party"): PartySummaryDto {
  const record = asRecord(value, path);
  return {
    id: asNumber(record["id"], `${path}.id`),
    party_type: asString(record["party_type"], `${path}.party_type`),
    name: asString(record["name"], `${path}.name`),
    alternate_name: asNullableString(record["alternate_name"], `${path}.alternate_name`),
    privacy_consent_at: asNullableString(record["privacy_consent_at"], `${path}.privacy_consent_at`),
    contacts: asArray(record["contacts"], `${path}.contacts`).map((entry, index) =>
      decodePartyContact(entry, `${path}.contacts[${index}]`),
    ),
  };
}

function decodeUnitPartyRelation(value: unknown, path: string): UnitPartyRelationDto {
  const record = asRecord(value, path);
  return {
    role: asString(record["role"], `${path}.role`),
    role_index: asNumber(record["role_index"], `${path}.role_index`),
    is_primary: asBoolean(record["is_primary"], `${path}.is_primary`),
    is_co_owner: asBoolean(record["is_co_owner"], `${path}.is_co_owner`),
    valid_from: asNullableString(record["valid_from"], `${path}.valid_from`),
    party: decodePartySummary(record["party"], `${path}.party`),
  };
}

export function decodeListing(value: unknown, path = "listing"): PropertyListingDto {
  const record = asRecord(value, path);
  return {
    id: asNumber(record["id"], `${path}.id`),
    unit_id: asNumber(record["unit_id"], `${path}.unit_id`),
    client_party_id: asNullableNumber(record["client_party_id"], `${path}.client_party_id`),
    received_at: asNullableString(record["received_at"], `${path}.received_at`),
    status: asString(record["status"], `${path}.status`),
    is_sale_available: asBoolean(record["is_sale_available"], `${path}.is_sale_available`),
    sale_price: asNullableNumber(record["sale_price"], `${path}.sale_price`),
    is_jeonse_available: asBoolean(record["is_jeonse_available"], `${path}.is_jeonse_available`),
    jeonse_deposit_amount: asNullableNumber(record["jeonse_deposit_amount"], `${path}.jeonse_deposit_amount`),
    is_monthly_rent_available: asBoolean(
      record["is_monthly_rent_available"],
      `${path}.is_monthly_rent_available`,
    ),
    monthly_rent_deposit_amount: asNullableNumber(
      record["monthly_rent_deposit_amount"],
      `${path}.monthly_rent_deposit_amount`,
    ),
    monthly_rent_amount: asNullableNumber(record["monthly_rent_amount"], `${path}.monthly_rent_amount`),
    price_raw_text: asNullableString(record["price_raw_text"], `${path}.price_raw_text`),
    handover_condition: asNullableString(record["handover_condition"], `${path}.handover_condition`),
    assigned_user_id: asNullableNumber(record["assigned_user_id"], `${path}.assigned_user_id`),
    memo: asNullableString(record["memo"], `${path}.memo`),
    custom_fields: asJsonObject(record["custom_fields"], `${path}.custom_fields`),
    row_version: asNumber(record["row_version"], `${path}.row_version`),
  };
}

export function decodePropertyUnitRow(value: unknown, path = "item"): PropertyUnitRowDto {
  const record = asRecord(value, path);
  const listing = record["current_listing"];
  return {
    id: asNumber(record["id"], `${path}.id`),
    complex: decodeComplexSummary(record["complex"], `${path}.complex`),
    building_number: asNullableString(record["building_number"], `${path}.building_number`),
    unit_number: asString(record["unit_number"], `${path}.unit_number`),
    floor_number: asNullableString(record["floor_number"], `${path}.floor_number`),
    orientation: asNullableString(record["orientation"], `${path}.orientation`),
    unit_type: asNullableString(record["unit_type"], `${path}.unit_type`),
    pyeong: asNullableDecimal(record["pyeong"], `${path}.pyeong`),
    exclusive_area_sqm: asNullableDecimal(record["exclusive_area_sqm"], `${path}.exclusive_area_sqm`),
    supply_area_sqm: asNullableDecimal(record["supply_area_sqm"], `${path}.supply_area_sqm`),
    tenancy_status: asNullableString(record["tenancy_status"], `${path}.tenancy_status`),
    current_deposit_amount: asNullableNumber(record["current_deposit_amount"], `${path}.current_deposit_amount`),
    current_monthly_rent_amount: asNullableNumber(
      record["current_monthly_rent_amount"],
      `${path}.current_monthly_rent_amount`,
    ),
    loan_amount: asNullableNumber(record["loan_amount"], `${path}.loan_amount`),
    tenancy_expiry_date: asNullableString(record["tenancy_expiry_date"], `${path}.tenancy_expiry_date`),
    tenancy_raw_text: asNullableString(record["tenancy_raw_text"], `${path}.tenancy_raw_text`),
    is_expanded: asNullableBoolean(record["is_expanded"], `${path}.is_expanded`),
    built_in_features: asNullableString(record["built_in_features"], `${path}.built_in_features`),
    facility_condition: asNullableString(record["facility_condition"], `${path}.facility_condition`),
    lifecycle_status: asString(record["lifecycle_status"], `${path}.lifecycle_status`),
    assigned_user_id: asNullableNumber(record["assigned_user_id"], `${path}.assigned_user_id`),
    memo: asNullableString(record["memo"], `${path}.memo`),
    custom_fields: asJsonObject(record["custom_fields"], `${path}.custom_fields`),
    last_contact_at: asNullableString(record["last_contact_at"], `${path}.last_contact_at`),
    row_version: asNumber(record["row_version"], `${path}.row_version`),
    current_listing: listing == null ? null : decodeListing(listing, `${path}.current_listing`),
    latest_interaction_content: asNullableString(
      record["latest_interaction_content"],
      `${path}.latest_interaction_content`,
    ),
    parties: asArray(record["parties"] ?? [], `${path}.parties`).map((entry, index) =>
      decodeUnitPartyRelation(entry, `${path}.parties[${index}]`),
    ),
  };
}

export function decodePropertyUnitDetail(value: unknown, path = "response"): PropertyUnitDetailDto {
  const record = asRecord(value, path);
  return {
    unit: decodePropertyUnitRow(record["unit"], `${path}.unit`),
    listings: asArray(record["listings"], `${path}.listings`).map((entry, index) =>
      decodeListing(entry, `${path}.listings[${index}]`),
    ),
    parties: asArray(record["parties"], `${path}.parties`).map((entry, index) =>
      decodeUnitPartyRelation(entry, `${path}.parties[${index}]`),
    ),
  };
}

export function decodeRequirementRow(value: unknown, path = "item"): PropertyRequirementRowDto {
  const record = asRecord(value, path);
  const pyeongs = record["desired_pyeongs"];
  return {
    id: asNumber(record["id"], `${path}.id`),
    party: decodePartySummary(record["party"], `${path}.party`),
    received_at: asNullableString(record["received_at"], `${path}.received_at`),
    demand_type: asString(record["demand_type"], `${path}.demand_type`),
    desired_pyeongs:
      pyeongs == null
        ? null
        : asArray(pyeongs, `${path}.desired_pyeongs`).map(
            (entry, index) => asNullableDecimal(entry, `${path}.desired_pyeongs[${index}]`) ?? 0,
          ),
    min_area_sqm: asNullableDecimal(record["min_area_sqm"], `${path}.min_area_sqm`),
    max_area_sqm: asNullableDecimal(record["max_area_sqm"], `${path}.max_area_sqm`),
    area_requirement_raw_text: asNullableString(
      record["area_requirement_raw_text"],
      `${path}.area_requirement_raw_text`,
    ),
    min_budget_amount: asNullableNumber(record["min_budget_amount"], `${path}.min_budget_amount`),
    max_budget_amount: asNullableNumber(record["max_budget_amount"], `${path}.max_budget_amount`),
    budget_raw_text: asNullableString(record["budget_raw_text"], `${path}.budget_raw_text`),
    desired_move_in_date: asNullableString(record["desired_move_in_date"], `${path}.desired_move_in_date`),
    move_in_date_raw_text: asNullableString(record["move_in_date_raw_text"], `${path}.move_in_date_raw_text`),
    request_expiry_date: asNullableString(record["request_expiry_date"], `${path}.request_expiry_date`),
    current_tenancy_expiry_date: asNullableString(
      record["current_tenancy_expiry_date"],
      `${path}.current_tenancy_expiry_date`,
    ),
    co_broker_party_id: asNullableNumber(record["co_broker_party_id"], `${path}.co_broker_party_id`),
    classification: asNullableString(record["classification"], `${path}.classification`),
    workflow_stage: asNullableString(record["workflow_stage"], `${path}.workflow_stage`),
    status: asString(record["status"], `${path}.status`),
    assigned_user_id: asNullableNumber(record["assigned_user_id"], `${path}.assigned_user_id`),
    memo: asNullableString(record["memo"], `${path}.memo`),
    custom_fields: asJsonObject(record["custom_fields"], `${path}.custom_fields`),
    last_contact_at: asNullableString(record["last_contact_at"], `${path}.last_contact_at`),
    row_version: asNumber(record["row_version"], `${path}.row_version`),
  };
}

export function decodeRequirementDetail(value: unknown, path = "response"): PropertyRequirementDetailDto {
  const record = asRecord(value, path);
  return {
    requirement: decodeRequirementRow(record["requirement"], `${path}.requirement`),
    desired_complexes: asArray(record["desired_complexes"], `${path}.desired_complexes`).map(
      (entry, index) => {
        const entryPath = `${path}.desired_complexes[${index}]`;
        const entryRecord = asRecord(entry, entryPath);
        return {
          complex: decodeComplexSummary(entryRecord["complex"], `${entryPath}.complex`),
          preference_order: asNullableNumber(entryRecord["preference_order"], `${entryPath}.preference_order`),
        };
      },
    ),
  };
}

export function decodeClientInteraction(value: unknown, path = "item"): ClientInteractionDto {
  const record = asRecord(value, path);
  return {
    id: asNumber(record["id"], `${path}.id`),
    interaction_at: asNullableString(record["interaction_at"], `${path}.interaction_at`),
    interaction_channel: asString(record["interaction_channel"], `${path}.interaction_channel`),
    communication_direction: asNullableString(
      record["communication_direction"],
      `${path}.communication_direction`,
    ),
    interaction_result: asNullableString(record["interaction_result"], `${path}.interaction_result`),
    counterparty_role: asNullableString(record["counterparty_role"], `${path}.counterparty_role`),
    counterparty_index: asNullableNumber(record["counterparty_index"], `${path}.counterparty_index`),
    interaction_content: asString(record["interaction_content"], `${path}.interaction_content`),
    party_id: asNullableNumber(record["party_id"], `${path}.party_id`),
    unit_id: asNullableNumber(record["unit_id"], `${path}.unit_id`),
    listing_id: asNullableNumber(record["listing_id"], `${path}.listing_id`),
    requirement_id: asNullableNumber(record["requirement_id"], `${path}.requirement_id`),
    source_type: asString(record["source_type"], `${path}.source_type`),
    approval_status: asString(record["approval_status"], `${path}.approval_status`),
    created_by: asNullableNumber(record["created_by"], `${path}.created_by`),
    created_at: asNullableString(record["created_at"], `${path}.created_at`),
  };
}

export function decodeColumnValues(value: unknown, path = "response"): ColumnValuesDto {
  const record = asRecord(value, path);
  return {
    column: asString(record["column"], `${path}.column`),
    items: asArray(record["items"], `${path}.items`).map((entry, index) => {
      const entryPath = `${path}.items[${index}]`;
      const entryRecord = asRecord(entry, entryPath);
      return {
        value: asString(entryRecord["value"], `${entryPath}.value`),
        count: asNumber(entryRecord["count"], `${entryPath}.count`),
      };
    }),
  };
}

export function decodePage<T>(
  value: unknown,
  decodeItem: (item: unknown, path: string) => T,
  path = "response",
): PageDto<T> {
  const record = asRecord(value, path);
  return {
    items: asArray(record["items"], `${path}.items`).map((item, index) =>
      decodeItem(item, `${path}.items[${index}]`),
    ),
    total: asNumber(record["total"], `${path}.total`),
    limit: asNumber(record["limit"], `${path}.limit`),
    offset: asNumber(record["offset"], `${path}.offset`),
  };
}
