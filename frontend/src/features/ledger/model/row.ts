/**
 * 화면 모델(그리드 행).
 *
 * 전송 DTO를 화면에 그대로 확산시키지 않기 위한 경계다. 이름·단위·null 표현이 여기서 정리된다.
 *
 * 값 표현 원칙
 *
 * - 표시 가능한 값은 문자열로 둔다. 그리드 셀과 상세 입력이 모두 문자열을 다룬다.
 * - 숫자·코드로 되돌리는 책임은 매퍼가 진다.
 * - 파싱으로 잃는 원문은 `raw`에 보존한다(F1-DM-11).
 * - 서버 왕복에 필요한 식별자와 `rowVersion`은 명시적 필드로 두고 화면에 표시하지 않는다.
 *
 * 계약에서 온 제약
 *
 * - 세대와 매물 건은 `row_version`을 각각 가지므로 저장도 두 요청으로 나뉜다.
 * - 빈 행은 서버로 보내지 않는다. 저장 시점에 필수값을 갖춘 POST 한 번으로 확정한다.
 */

import type { PartySummaryDto, UnitPartyRelationDto } from "./dto.ts";

/** 장부 목록에 노출하는 저장 상태. F2 처리 상태와는 독립이다. */
export type SaveState = "임시저장" | "저장 완료";

/** 낙관적 저장(F1-GR-26)과 연결 단절 처리(F1-GR-35)를 위한 행 단위 동기화 상태. */
export type RowSyncState =
  | { status: "synced" }
  | { status: "saving" }
  | { status: "failed"; reason: string }
  /** 서버 값이 더 최신이라 사용자 변경을 적용하지 못한 상태(row_version 충돌). */
  | { status: "conflict"; reason: string };

export const SYNCED: RowSyncState = { status: "synced" };

/** 서버 왕복에 필요하지만 화면에는 나타나지 않는 값. */
export interface LedgerRowMeta {
  /** 정식 레코드의 서버 id. 아직 저장되지 않은 빈 행이면 null. */
  serverId: number | null;
  /** 낙관적 잠금용. 서버가 준 값을 그대로 되돌려 보낸다. */
  rowVersion: number | null;
  sync: RowSyncState;
  customFields: Record<string, unknown>;
}

export interface PropertyRawText {
  price: string;
  tenancy: string;
}

export interface BuyerRawText {
  budget: string;
  area: string;
  moveIn: string;
}

/** 매물장 행. 필드 이름은 기존 화면(`LedgerGrid`, `DetailWorkspace`)이 쓰던 이름을 유지한다. */
export interface PropertyRow extends LedgerRowMeta {
  /** 그리드 행 키. 저장된 행은 서버 id 문자열, 빈 행은 "DRAFT-..." 형태다. */
  id: string;
  ledgerType: "property";
  rowKind: "property";

  saveState: SaveState;

  complexId: number | null;
  complex: string;
  building: string;
  unit: string;
  floor: string;
  area: string;
  direction: string;

  householdState: string;
  listingType: string;
  receivedAt: string;
  clearance: string;

  /** 매물 건은 세대와 별도 레코드이며 `row_version`도 따로 관리된다. */
  listingId: number | null;
  listingRowVersion: number | null;

  saleFlag: string;
  leaseFlag: string;
  monthlyFlag: string;
  salePrice: string;
  leaseDeposit: string;
  rentCondition: string;
  /** 현재 거래 유형의 대표 금액. 상세 화면이 쓰는 파생 표시값이다. */
  price: string;

  deposit: string;
  rent: string;
  loan: string;
  expiry: string;

  assigneeId: number | null;
  assignee: string;
  lastContact: string;
  log: string;
  memo: string;

  /**
   * 인물 정보.
   *
   * 목록 응답에는 인물이 없다. 목록에서는 비어 있고 상세를 열 때 채워진다.
   * `GET /property-units/{id}`가 `parties`를 반환한다.
   */
  owner: string;
  ownerPhone: string;
  tenant: string;
  tenantPhone: string;
  consent: string;
  parties: UnitPartyRelationDto[];
  isCoOwned: boolean;
  /** 인물 정보를 아직 불러오지 않은 상태인지. 목록 행은 true다. */
  partiesLoaded: boolean;

  /** 전용 컬럼으로 승격된 열들. migration 009에서 추가되었다. */
  type: string;
  spec: string;
  builtIn: string;
  facilityState: string;
  brokerage: string;

  raw: PropertyRawText;
}

/** 구입장 행. 매물장과 달리 인물이 목록 응답에 포함된다. */
export interface BuyerRow extends LedgerRowMeta {
  id: string;
  ledgerType: "buyer";
  rowKind: "buyer";

  saveState: SaveState;

  /** 접수일. 정렬 기준인 최종접촉일과 분리한다(F1-DM-07). */
  date: string;
  lastContact: string;

  category: string;
  completion: string;

  area: string;
  budget: string;
  moveDate: string;
  expiry: string;

  complexId: number | null;
  complex: string;

  partyId: number | null;
  buyer: string;
  phone: string;
  consent: string;
  /** 개인정보 활용 동의 시각. null이면 저장이 거절된다(F1-DM-16). */
  privacyConsentAt: string | null;
  party: PartySummaryDto | null;

  assigneeId: number | null;
  assignee: string;

  content: string;
  memo: string;

  /** 전용 컬럼으로 승격된 열들. */
  brokerage: string;
  stage: string;
  classification: string;
  background: string;

  raw: BuyerRawText;
}

export type LedgerRow = PropertyRow | BuyerRow;

export function isBuyerRow(row: LedgerRow | null | undefined): row is BuyerRow {
  return row?.ledgerType === "buyer";
}

export function isPropertyRow(row: LedgerRow | null | undefined): row is PropertyRow {
  return row?.ledgerType === "property";
}

/** 아직 서버에 저장되지 않은 행인지. 저장 안 함으로 닫으면 그리드에서 제거한다(F1-GR-32). */
export function isUnsavedDraft(row: LedgerRow | null | undefined): boolean {
  return row != null && row.serverId == null;
}

/**
 * 다음 저장에 필요한 서버 신원만 골라내는 열.
 *
 * 세대와 매물 건은 각각 `row_version`을 갖고(위 계약 주석), 손님 행은 인물 id를 갖는다.
 * 저장이 끝나면 이 값들이 모두 새 값으로 바뀐다.
 */
const SAVED_IDENTITY_KEYS = [
  "serverId",
  "rowVersion",
  "listingId",
  "listingRowVersion",
  "partyId",
  "customFields",
] as const;

/**
 * 저장 응답의 서버 신원을 작성값에 얹는다.
 *
 * 상세 화면은 열릴 때 복사한 작성값을 들고 있어, 저장이 끝나도 서버가 올린 `row_version`을
 * 모른다. 그대로 두면 같은 상세에서 두 번째로 저장할 때 낡은 `row_version`을 보내
 * 혼자 쓰고 있어도 "다른 사용자가 먼저 저장했습니다"(409)를 받는다.
 *
 * 사용자가 적은 값은 건드리지 않는다. 저장 중에 이어서 입력한 내용을 응답으로 덮으면
 * 방금 친 글자가 사라진다.
 */
export function carrySavedIdentity<T extends object>(draft: T, persisted: unknown): T {
  if (persisted == null || typeof persisted !== "object") return draft;
  const source = persisted as Record<string, unknown>;
  const carried: Record<string, unknown> = {};
  for (const key of SAVED_IDENTITY_KEYS) {
    if (key in source) carried[key] = source[key];
  }
  return { ...draft, ...carried };
}
