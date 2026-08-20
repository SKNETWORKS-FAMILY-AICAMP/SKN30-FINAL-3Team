/**
 * 장부 데이터 출처의 공통 인터페이스.
 *
 * 화면과 훅은 이 인터페이스에만 의존한다. 실제 구현이 mock인지 HTTP인지 알지 못한다.
 * 백엔드가 준비되면 `VITE_LEDGER_SOURCE=api` 하나로 갈아끼운다.
 *
 * 계약에서 온 제약
 *
 * - `limit`은 최대 500이다. 전량 로드가 불가능하므로 목록은 페이지 단위로 가져온다.
 * - 통합 검색 파라미터가 없다. 필터는 컬럼별 정확값 목록(OR 결합)만 지원한다.
 * - 세대와 매물 건은 저장 요청이 분리된다.
 */

import type {
  ClientInteractionCreateDto,
  ComplexSummaryDto,
  PropertyComplexCreateDto,
  ClientInteractionDto,
  ColumnValuesDto,
  PageDto,
  PropertyListingCreateDto,
  PropertyListingDto,
  PropertyListingUpdateDto,
  PropertyRequirementCreateDto,
  PropertyRequirementDetailDto,
  PropertyRequirementRowDto,
  PropertyRequirementUpdateDto,
  PropertyUnitCreateDto,
  PropertyUnitDetailDto,
  PropertyUnitRowDto,
  PropertyUnitUpdateDto,
} from "../model/dto.ts";

/** 컬럼별 정확값 필터. 같은 키를 반복하면 서버가 OR로 결합한다. */
export type ColumnFilters = Record<string, readonly string[] | undefined>;

export interface ListQuery {
  filters?: ColumnFilters;
  limit?: number;
  offset?: number;
}

export interface LedgerTransport {
  /** 단지 마스터. 세대를 만들려면 단지가 먼저 있어야 한다. */
  listComplexes(query: ListQuery, signal?: AbortSignal): Promise<PageDto<ComplexSummaryDto>>;
  createComplex(
    payload: PropertyComplexCreateDto,
    signal?: AbortSignal,
  ): Promise<ComplexSummaryDto>;
  /** 단지 삭제. 세대가 남아 있으면 서버가 거절한다. */
  deleteComplex(complexId: number, rowVersion: number, signal?: AbortSignal): Promise<void>;

  listPropertyUnits(query: ListQuery, signal?: AbortSignal): Promise<PageDto<PropertyUnitRowDto>>;
  getPropertyUnit(unitId: number, signal?: AbortSignal): Promise<PropertyUnitDetailDto>;
  createPropertyUnit(payload: PropertyUnitCreateDto, signal?: AbortSignal): Promise<PropertyUnitDetailDto>;
  updatePropertyUnit(
    unitId: number,
    payload: PropertyUnitUpdateDto,
    signal?: AbortSignal,
  ): Promise<PropertyUnitDetailDto>;

  /** 소프트 삭제. 낙관적 잠금을 위해 마지막으로 읽은 row_version을 함께 보낸다. */
  deletePropertyUnit(unitId: number, rowVersion: number, signal?: AbortSignal): Promise<void>;

  createPropertyListing(
    unitId: number,
    payload: PropertyListingCreateDto,
    signal?: AbortSignal,
  ): Promise<PropertyListingDto>;
  updatePropertyListing(
    listingId: number,
    payload: PropertyListingUpdateDto,
    signal?: AbortSignal,
  ): Promise<PropertyListingDto>;

  listRequirements(query: ListQuery, signal?: AbortSignal): Promise<PageDto<PropertyRequirementRowDto>>;
  getRequirement(requirementId: number, signal?: AbortSignal): Promise<PropertyRequirementDetailDto>;
  createRequirement(
    payload: PropertyRequirementCreateDto,
    signal?: AbortSignal,
  ): Promise<PropertyRequirementDetailDto>;
  updateRequirement(
    requirementId: number,
    payload: PropertyRequirementUpdateDto,
    signal?: AbortSignal,
  ): Promise<PropertyRequirementDetailDto>;

  deleteRequirement(requirementId: number, rowVersion: number, signal?: AbortSignal): Promise<void>;

  listClientInteractions(
    scope: { unitId?: number; requirementId?: number; partyId?: number; limit?: number },
    signal?: AbortSignal,
  ): Promise<PageDto<ClientInteractionDto>>;
  createClientInteraction(
    payload: ClientInteractionCreateDto,
    signal?: AbortSignal,
  ): Promise<ClientInteractionDto>;

  /**
   * 값 목록 필터(F1-GR-38). 한 요청에 한 컬럼만 조회한다.
   * 현재 필터 결과 범위 안에 실재하는 값만 서버가 계산해 돌려준다.
   */
  listUnitColumnValues(
    column: string,
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ColumnValuesDto>;
  listRequirementColumnValues(
    column: string,
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ColumnValuesDto>;
}
