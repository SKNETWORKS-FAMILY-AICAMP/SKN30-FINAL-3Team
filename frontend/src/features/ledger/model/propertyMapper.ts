/**
 * 매물장 DTO ↔ 화면 행 변환.
 *
 * DB 연동에서 실제로 값이 깨지는 곳은 거의 전부 이 파일이다.
 * React에 의존하지 않는 순수 함수로 두고 단위 테스트로 왕복을 검증한다.
 */

import { LIFECYCLE_STATUS, ORIENTATION, TENANCY_STATUS, toCode, toLabel } from "./codes.ts";
import { formatPyeong, parsePyeong } from "./area.ts";
import { formatDate, formatTimestampAsDate, parseDate } from "./dates.ts";
import { formatMoney, formatMoneyPair, parseMoney, parseMoneyPair } from "./money.ts";
import { formatPhone } from "./phone.ts";
import type {
  PropertyListingCreateDto,
  PropertyListingUpdateDto,
  PropertyUnitCreateDto,
  PropertyUnitDetailDto,
  PropertyUnitRowDto,
  PropertyUnitUpdateDto,
  UnitPartyRelationDto,
} from "./dto.ts";
import type { PropertyRow } from "./row.ts";
import { SYNCED } from "./row.ts";

/** 공동명의 표시 구분자. F1-GR-06이 `박이서, 송경련` 형태를 지정한다. */
const NAME_SEPARATOR = ", ";

/** 전용 컬럼이 없어 custom_fields에 실리는 열. */
const CUSTOM_KEYS = { spec: "spec", brokerageName: "brokerage_name" } as const;

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

/**
 * 「현매물」 열에 보여줄 단일 거래 유형.
 *
 * DB는 매매·전세·월세를 각각 boolean으로 두어 동시에 참일 수 있다.
 * 단일 값으로 접어야 하는 열이므로 매매 > 전세 > 월세 우선순위로 대표값을 고른다.
 * 원본 세 값은 flag 필드에 그대로 남아 정보가 사라지지 않는다.
 */
function primaryListingType(isSale: boolean, isJeonse: boolean, isMonthly: boolean): string {
  if (isSale) return "매매";
  if (isJeonse) return "전세";
  if (isMonthly) return "월세";
  return "";
}

function relationsWithRole(relations: readonly UnitPartyRelationDto[], role: string): UnitPartyRelationDto[] {
  return relations
    .filter((relation) => relation.role === role)
    .slice()
    .sort((left, right) => left.role_index - right.role_index);
}

function joinNames(relations: readonly UnitPartyRelationDto[]): string {
  return relations
    .map((relation) => relation.party.alternate_name || relation.party.name)
    .filter(Boolean)
    .join(NAME_SEPARATOR);
}

function primaryContact(relation: UnitPartyRelationDto | undefined): string {
  if (relation == null) return "";
  const contact = relation.party.contacts.find((entry) => entry.is_primary) ?? relation.party.contacts[0];
  return formatPhone(contact?.contact_value);
}

function consentLabel(relation: UnitPartyRelationDto | undefined): string {
  if (relation == null) return "미확인";
  return relation.party.privacy_consent_at == null ? "미확인" : "동의";
}

/**
 * 목록 행을 화면 행으로.
 *
 * 목록 응답에는 인물과 상담 로그가 없다. 해당 열은 비어 있고 `partiesLoaded`가 false다.
 * 상세를 열 때 `applyUnitDetail`로 채운다.
 */
export function toPropertyRow(dto: PropertyUnitRowDto, assigneeName = ""): PropertyRow {
  const listing = dto.current_listing;

  const isSale = listing?.is_sale_available ?? false;
  const isJeonse = listing?.is_jeonse_available ?? false;
  const isMonthly = listing?.is_monthly_rent_available ?? false;
  const listingType = primaryListingType(isSale, isJeonse, isMonthly);

  const salePrice = formatMoney(listing?.sale_price ?? null);
  const leaseDeposit = formatMoney(listing?.jeonse_deposit_amount ?? null);
  const rentCondition = formatMoneyPair(
    listing?.monthly_rent_deposit_amount ?? null,
    listing?.monthly_rent_amount ?? null,
  );

  const price =
    listingType === "매매"
      ? salePrice
      : listingType === "전세"
        ? leaseDeposit
        : listingType === "월세"
          ? rentCondition
          : "";

  return {
    id: String(dto.id),
    ledgerType: "property",
    rowKind: "property",

    serverId: dto.id,
    rowVersion: dto.row_version,
    sync: SYNCED,
    customFields: dto.custom_fields,

    // 서버에 존재하는 행은 저장 완료다. 임시저장은 아직 저장되지 않은 화면 상태에만 쓴다.
    saveState: "저장 완료",

    complexId: dto.complex.id,
    complex: dto.complex.name,
    building: textOrEmpty(dto.building_number),
    unit: dto.unit_number,
    floor: textOrEmpty(dto.floor_number),
    area: formatPyeong(dto.pyeong),
    direction: toLabel(ORIENTATION, dto.orientation),

    householdState: toLabel(LIFECYCLE_STATUS, dto.lifecycle_status),
    listingType,
    receivedAt: formatDate(listing?.received_at ?? null),
    clearance: textOrEmpty(listing?.handover_condition),

    listingId: listing?.id ?? null,
    listingRowVersion: listing?.row_version ?? null,

    saleFlag: isSale ? "Y" : "",
    leaseFlag: isJeonse ? "Y" : "",
    monthlyFlag: isMonthly ? "Y" : "",
    salePrice,
    leaseDeposit,
    rentCondition,
    price,

    deposit: formatMoney(dto.current_deposit_amount),
    rent: formatMoney(dto.current_monthly_rent_amount),
    loan: formatMoney(dto.loan_amount),
    expiry: formatDate(dto.tenancy_expiry_date),

    assigneeId: dto.assigned_user_id,
    assignee: assigneeName,
    lastContact: formatTimestampAsDate(dto.last_contact_at),
    // 목록 응답이 최신 상담 로그 1건을 함께 싣는다. 상세를 열면 같은 값으로 덮어쓴다.
    log: textOrEmpty(dto.latest_interaction_content),
    memo: textOrEmpty(dto.memo),

    owner: "",
    ownerPhone: "",
    tenant: "",
    tenantPhone: "",
    consent: "미확인",
    parties: [],
    isCoOwned: false,
    partiesLoaded: false,

    type: textOrEmpty(dto.unit_type),
    spec: readCustomText(dto.custom_fields, CUSTOM_KEYS.spec),
    builtIn: textOrEmpty(dto.built_in_features),
    facilityState: textOrEmpty(dto.facility_condition),
    brokerage: readCustomText(dto.custom_fields, CUSTOM_KEYS.brokerageName),

    raw: {
      price: textOrEmpty(listing?.price_raw_text),
      tenancy: textOrEmpty(dto.tenancy_raw_text),
    },
  };
}

/** 상세 응답으로 인물 정보를 채운다. 목록 행에는 인물이 없기 때문에 별도 단계가 필요하다. */
export function applyUnitDetail(row: PropertyRow, detail: PropertyUnitDetailDto): PropertyRow {
  const owners = relationsWithRole(detail.parties, "OWNER");
  const tenants = relationsWithRole(detail.parties, "TENANT");

  return {
    ...row,
    owner: joinNames(owners),
    ownerPhone: primaryContact(owners[0]),
    tenant: joinNames(tenants),
    tenantPhone: primaryContact(tenants[0]),
    consent: consentLabel(owners[0]),
    parties: detail.parties,
    isCoOwned: owners.length > 1 || owners.some((relation) => relation.is_co_owner),
    partiesLoaded: true,
  };
}

/**
 * 서버가 확정한 식별자와 버전을 행에 반영한다.
 *
 * 저장은 세대·매물·상담 로그로 나뉜 여러 요청이다. 중간에 실패해도 이미 만들어진 것은
 * 서버에 남으므로, 각 단계가 끝나는 즉시 이 값을 기록해야 재시도가 같은 레코드를
 * 다시 만들지 않고 이어서 고칠 수 있다.
 */
export function applyServerIdentity(
  row: PropertyRow,
  unit: { id: number; row_version: number },
  listing?: { id: number; row_version: number } | null,
): PropertyRow {
  return {
    ...row,
    serverId: unit.id,
    rowVersion: unit.row_version,
    listingId: listing?.id ?? row.listingId,
    listingRowVersion: listing?.row_version ?? row.listingRowVersion,
  };
}

/** 상담 로그 최신 1건을 행에 반영한다(F1-GR-05). */
export function applyLatestInteraction(row: PropertyRow, content: string): PropertyRow {
  return { ...row, log: content };
}

/** 세대 생성 요청. `complex_id`와 `unit_number`가 서버 필수값이다. */
export function toUnitCreatePayload(row: PropertyRow): PropertyUnitCreateDto | null {
  if (row.complexId == null) return null;
  const unitNumber = emptyToNull(row.unit);
  if (unitNumber == null) return null;

  return {
    complex_id: row.complexId,
    unit_number: unitNumber,
    building_number: emptyToNull(row.building),
    floor_number: emptyToNull(row.floor),
    orientation: toCode(ORIENTATION, row.direction),
    unit_type: emptyToNull(row.type),
    pyeong: parsePyeong(row.area),
    tenancy_status: toCode(TENANCY_STATUS, ""),
    current_deposit_amount: parseMoney(row.deposit),
    current_monthly_rent_amount: parseMoney(row.rent),
    loan_amount: parseMoney(row.loan),
    tenancy_expiry_date: parseDate(row.expiry),
    tenancy_raw_text: emptyToNull(row.raw?.tenancy),
    is_expanded: null,
    built_in_features: emptyToNull(row.builtIn),
    facility_condition: emptyToNull(row.facilityState),
    assigned_user_id: row.assigneeId,
    memo: emptyToNull(row.memo),
    custom_fields: {
      ...row.customFields,
      [CUSTOM_KEYS.spec]: row.spec,
      [CUSTOM_KEYS.brokerageName]: row.brokerage,
    },
  };
}

/** 세대 부분 수정 요청. `row_version`이 필수다. */
export function toUnitUpdatePayload(row: PropertyRow): PropertyUnitUpdateDto | null {
  if (row.rowVersion == null) return null;
  return {
    row_version: row.rowVersion,
    building_number: emptyToNull(row.building),
    unit_number: emptyToNull(row.unit) ?? undefined,
    floor_number: emptyToNull(row.floor),
    orientation: toCode(ORIENTATION, row.direction),
    unit_type: emptyToNull(row.type),
    pyeong: parsePyeong(row.area),
    current_deposit_amount: parseMoney(row.deposit),
    current_monthly_rent_amount: parseMoney(row.rent),
    loan_amount: parseMoney(row.loan),
    tenancy_expiry_date: parseDate(row.expiry),
    tenancy_raw_text: emptyToNull(row.raw?.tenancy),
    built_in_features: emptyToNull(row.builtIn),
    facility_condition: emptyToNull(row.facilityState),
    lifecycle_status: toCode(LIFECYCLE_STATUS, row.householdState),
    assigned_user_id: row.assigneeId,
    memo: emptyToNull(row.memo),
    custom_fields: {
      ...row.customFields,
      [CUSTOM_KEYS.spec]: row.spec,
      [CUSTOM_KEYS.brokerageName]: row.brokerage,
    },
  };
}

/** 매물 건에 담을 값이 하나라도 있는지. 없으면 매물을 만들지 않는다(F1-GR-01). */
export function hasListingValues(row: PropertyRow): boolean {
  return (
    row.saleFlag === "Y" ||
    row.leaseFlag === "Y" ||
    row.monthlyFlag === "Y" ||
    row.listingType !== "" ||
    emptyToNull(row.receivedAt) != null
  );
}

function listingFields(row: PropertyRow): PropertyListingCreateDto {
  const isSale = row.saleFlag === "Y" || row.listingType === "매매";
  const isJeonse = row.leaseFlag === "Y" || row.listingType === "전세";
  const isMonthly = row.monthlyFlag === "Y" || row.listingType === "월세";
  const rentPair = parseMoneyPair(row.rentCondition);

  return {
    received_at: parseDate(row.receivedAt),
    is_sale_available: isSale,
    sale_price: isSale ? parseMoney(row.salePrice || row.price) : null,
    is_jeonse_available: isJeonse,
    jeonse_deposit_amount: isJeonse ? parseMoney(row.leaseDeposit || row.price) : null,
    is_monthly_rent_available: isMonthly,
    monthly_rent_deposit_amount: isMonthly ? (rentPair.first ?? parseMoney(row.deposit)) : null,
    monthly_rent_amount: isMonthly ? (rentPair.second ?? parseMoney(row.rent)) : null,
    // 사용자가 마지막으로 본 대표 금액 문자열을 원문으로 남긴다(F1-DM-11).
    price_raw_text: emptyToNull(row.raw?.price || row.price),
    handover_condition: emptyToNull(row.clearance),
    memo: null,
    custom_fields: {},
  };
}

export function toListingCreatePayload(row: PropertyRow): PropertyListingCreateDto {
  return listingFields(row);
}

export function toListingUpdatePayload(row: PropertyRow): PropertyListingUpdateDto | null {
  if (row.listingRowVersion == null) return null;
  return { row_version: row.listingRowVersion, ...listingFields(row) };
}

/**
 * 상담 로그가 실제로 바뀌었을 때만 새 로그 내용을 반환한다.
 * `client_interaction`은 추가 전용이라 수정이 아니라 새 로그 추가로 처리한다.
 */
export function newInteractionContent(
  current: string,
  previous: string | null | undefined,
): string | null {
  const next = current.trim();
  if (next === "") return null;
  if (next === (previous ?? "").trim()) return null;
  return next;
}

/** 접어 표시한 이름을 다시 나눈다. 실사용 장부에 쉼표·가운뎃점·슬래시가 섞여 있다. */
export function splitNames(value: string | null | undefined): string[] {
  return String(value ?? "")
    .split(/[·,/\n]+/)
    .map((name) => name.trim())
    .filter((name) => name !== "");
}

/**
 * 빈 행(F1-GR-30).
 *
 * 계약상 빈 행은 서버로 보내지 않는다. 저장 시점에 필수값을 갖춘 POST 한 번으로 확정한다.
 * 그때까지는 화면 상태로만 존재한다.
 */
export function createPropertyDraftRow(localId: string): PropertyRow {
  return {
    id: localId,
    ledgerType: "property",
    rowKind: "property",

    serverId: null,
    rowVersion: null,
    sync: SYNCED,
    customFields: {},

    saveState: "임시저장",

    complexId: null,
    complex: "",
    building: "",
    unit: "",
    floor: "",
    area: "",
    direction: "",

    householdState: "일반",
    listingType: "",
    receivedAt: "",
    clearance: "",

    listingId: null,
    listingRowVersion: null,

    saleFlag: "",
    leaseFlag: "",
    monthlyFlag: "",
    salePrice: "",
    leaseDeposit: "",
    rentCondition: "",
    price: "",

    deposit: "",
    rent: "",
    loan: "",
    expiry: "",

    assigneeId: null,
    assignee: "",
    lastContact: "",
    log: "",
    memo: "",

    owner: "",
    ownerPhone: "",
    tenant: "",
    tenantPhone: "",
    consent: "미확인",
    parties: [],
    isCoOwned: false,
    partiesLoaded: true,

    type: "",
    spec: "",
    builtIn: "",
    facilityState: "",
    brokerage: "",

    raw: { price: "", tenancy: "" },
  };
}
