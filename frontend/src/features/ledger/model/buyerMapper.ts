/**
 * 구입장 DTO ↔ 화면 행 변환.
 *
 * 구입장은 매물장보다 원문 보존이 중요하다. 「금액」과 「평형」에 "28억선", "25 33" 같은 값이
 * 실제로 들어오고, 숫자로만 저장하면 뉘앙스가 사라진다(F1-DM-11).
 * 표시는 원문을 우선하고 파싱값은 검색·매칭용으로 함께 보낸다.
 *
 * 매물장과 달리 인물과 연락처가 목록 응답에 포함된다.
 */

import { DEMAND_TYPE, REQUIREMENT_STATUS, toCode, toLabel } from "./codes.ts";
import { formatPyeongList, parsePyeongList } from "../../../shared/format/index.ts";
import { formatDate, parseDate } from "./dates.ts";
import { formatMoney, parseMoney } from "../../../shared/format/index.ts";
import { formatPhone } from "./phone.ts";
import type {
  PartySummaryDto,
  PropertyRequirementCreateDto,
  PropertyRequirementRowDto,
  PropertyRequirementUpdateDto,
} from "./dto.ts";
import type { BuyerRow } from "./row.ts";
import { SYNCED } from "./row.ts";
import { newInteractionContent } from "./propertyMapper.ts";

const RANGE_SEPARATOR = /[~〜–—]|(?<=\d)\s*-\s*(?=\d)/;
const UPPER_BOUND_WORDS = /이하|미만|까지/;
const LOWER_BOUND_WORDS = /이상|초과|부터/;

/** 전용 컬럼이 없어 custom_fields에 실리는 열. */
const CUSTOM_KEYS = { brokerageName: "brokerage_name", background: "background" } as const;

function readCustomText(fields: Record<string, unknown>, key: string): string {
  const value = fields[key];
  return typeof value === "string" ? value : "";
}

function textOrEmpty(value: string | null | undefined): string {
  return value ?? "";
}

function emptyToNull(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function primaryContactValue(party: PartySummaryDto | null): string {
  if (party == null) return "";
  const contact = party.contacts.find((entry) => entry.is_primary) ?? party.contacts[0];
  return formatPhone(contact?.contact_value);
}

/**
 * 예산 문자열을 하한·상한으로 파싱한다.
 *
 * - "24~28억"   → { min: 24억, max: 28억 }   (앞 구간에 단위가 없으면 뒤 구간 단위를 물려받는다)
 * - "12억 이하" → { min: null, max: 12억 }
 * - "20억 이상" → { min: 20억, max: null }
 * - "28억선"    → { min: null, max: 28억 }   예산은 상한으로 읽는 쪽이 실무 의미에 가깝다.
 * - "협의"      → { min: null, max: null }   원문은 budget_raw_text로 보존된다.
 */
export function parseBudgetRange(input: string | null | undefined): {
  min: number | null;
  max: number | null;
} {
  if (input == null) return { min: null, max: null };
  const text = String(input).trim();
  if (text === "") return { min: null, max: null };

  const segments = text.split(RANGE_SEPARATOR).map((segment) => segment.trim()).filter(Boolean);

  if (segments.length >= 2) {
    const head = segments[0] ?? "";
    const tail = segments[1] ?? "";
    const inheritedUnit = /억/.test(tail) ? "eok" : /만/.test(tail) ? "man" : "won";
    const min = parseMoney(head, /[억만천]/.test(head) ? "won" : inheritedUnit);
    const max = parseMoney(tail);
    return { min, max };
  }

  const value = parseMoney(text);
  if (value == null) return { min: null, max: null };
  if (LOWER_BOUND_WORDS.test(text)) return { min: value, max: null };
  if (UPPER_BOUND_WORDS.test(text)) return { min: null, max: value };
  return { min: null, max: value };
}

/** 원문이 없을 때 파싱값으로 예산 표기를 만든다. */
export function formatBudgetRange(min: number | null, max: number | null): string {
  if (min != null && max != null) return `${formatMoney(min)}~${formatMoney(max)}`;
  if (max != null) return `${formatMoney(max)} 이하`;
  if (min != null) return `${formatMoney(min)} 이상`;
  return "";
}

export function toBuyerRow(
  dto: PropertyRequirementRowDto,
  options: { assigneeName?: string; complexName?: string; complexId?: number | null } = {},
): BuyerRow {
  const party = dto.party;

  return {
    id: String(dto.id),
    ledgerType: "buyer",
    rowKind: "buyer",

    serverId: dto.id,
    rowVersion: dto.row_version,
    sync: SYNCED,
    customFields: dto.custom_fields,

    saveState: "저장 완료",

    date: formatDate(dto.received_at),
    lastContact: formatDate(dto.last_contact_at?.slice(0, 10) ?? null),

    category: toLabel(DEMAND_TYPE, dto.demand_type),
    completion: toLabel(REQUIREMENT_STATUS, dto.status),

    // 표시는 원문 우선. 원문이 없을 때만 파싱값으로 만든다.
    area: dto.area_requirement_raw_text || formatPyeongList(dto.desired_pyeongs ?? []),
    budget: dto.budget_raw_text || formatBudgetRange(dto.min_budget_amount, dto.max_budget_amount),
    moveDate: formatDate(dto.desired_move_in_date),
    expiry: formatDate(dto.request_expiry_date),

    // 희망 단지는 목록 응답에 없다. 상세(desired_complexes)에서만 온다.
    complexId: options.complexId ?? null,
    complex: options.complexName ?? "",

    partyId: party.id,
    // 실명 대신 별칭을 허용한다(F1-DM-08).
    buyer: party.alternate_name || party.name,
    phone: primaryContactValue(party),
    consent: party.privacy_consent_at == null ? "미확인" : "동의",
    privacyConsentAt: party.privacy_consent_at,
    party,

    assigneeId: dto.assigned_user_id,
    assignee: options.assigneeName ?? "",

    // 상담 로그는 별도 엔드포인트에서 가져온다.
    content: "",
    memo: textOrEmpty(dto.memo),

    brokerage: readCustomText(dto.custom_fields, CUSTOM_KEYS.brokerageName),
    stage: textOrEmpty(dto.workflow_stage),
    classification: textOrEmpty(dto.classification),
    background: readCustomText(dto.custom_fields, CUSTOM_KEYS.background),

    raw: {
      budget: textOrEmpty(dto.budget_raw_text),
      area: textOrEmpty(dto.area_requirement_raw_text),
      moveIn: textOrEmpty(dto.move_in_date_raw_text),
    },
  };
}

function requirementFields(row: BuyerRow) {
  const budget = parseBudgetRange(row.budget);
  const pyeongs = parsePyeongList(row.area);

  return {
    received_at: parseDate(row.date),
    desired_pyeongs: pyeongs.length === 0 ? null : pyeongs,
    desired_complex_ids: row.complexId == null ? [] : [row.complexId],
    area_requirement_raw_text: emptyToNull(row.area),
    min_budget_amount: budget.min,
    max_budget_amount: budget.max,
    budget_raw_text: emptyToNull(row.budget),
    desired_move_in_date: parseDate(row.moveDate),
    move_in_date_raw_text: emptyToNull(row.raw?.moveIn),
    request_expiry_date: parseDate(row.expiry),
    classification: emptyToNull(row.classification),
    workflow_stage: emptyToNull(row.stage),
    status: toCode(REQUIREMENT_STATUS, row.completion),
    assigned_user_id: row.assigneeId,
    memo: emptyToNull(row.memo),
    custom_fields: {
      ...row.customFields,
      [CUSTOM_KEYS.brokerageName]: row.brokerage,
      [CUSTOM_KEYS.background]: row.background,
    },
  };
}

/**
 * 구입장 생성 요청.
 *
 * `party_id`가 서버 필수값이다. 인물을 먼저 만들어야 구입장을 만들 수 있는데
 * 인물 생성 엔드포인트가 아직 계약에 없다. 인물 id가 없으면 null을 반환해
 * 호출부가 저장을 보류하고 사용자에게 알리게 한다.
 */
export function toRequirementCreatePayload(row: BuyerRow): PropertyRequirementCreateDto | null {
  if (row.partyId == null) return null;
  const demandType = toCode(DEMAND_TYPE, row.category);
  if (demandType == null) return null;

  return { party_id: row.partyId, demand_type: demandType, ...requirementFields(row) };
}

export function toRequirementUpdatePayload(row: BuyerRow): PropertyRequirementUpdateDto | null {
  if (row.rowVersion == null) return null;
  return {
    row_version: row.rowVersion,
    demand_type: toCode(DEMAND_TYPE, row.category) ?? undefined,
    ...requirementFields(row),
  };
}

export function buyerInteractionContent(row: BuyerRow, previous: string | null): string | null {
  return newInteractionContent(row.content, previous);
}

/** 구입장 빈 행. 저장 전까지 화면 상태로만 존재한다. */
export function createBuyerDraftRow(localId: string): BuyerRow {
  return {
    id: localId,
    ledgerType: "buyer",
    rowKind: "buyer",

    serverId: null,
    rowVersion: null,
    sync: SYNCED,
    customFields: {},

    saveState: "임시저장",

    date: "",
    lastContact: "",

    category: "매수",
    completion: "진행",

    area: "",
    budget: "",
    moveDate: "",
    expiry: "",

    complexId: null,
    complex: "",

    partyId: null,
    buyer: "",
    phone: "",
    consent: "미확인",
    privacyConsentAt: null,
    party: null,

    assigneeId: null,
    assignee: "",

    content: "",
    memo: "",

    brokerage: "",
    stage: "",
    classification: "",
    background: "",

    raw: { budget: "", area: "", moveIn: "" },
  };
}
