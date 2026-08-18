/**
 * 장부 기능 모듈의 공개 진입점.
 *
 * 다른 기능은 이 파일이 내보내는 것만 쓴다. 내부 파일을 깊은 경로로 가져가지 않는다.
 * 그래야 transport 교체, DTO 형태 변경, 매퍼 수정이 모듈 밖으로 새지 않는다.
 */

export { usePropertyLedger } from "./hooks/usePropertyLedger.ts";
export type { PropertyLedger, UserNameLookup } from "./hooks/usePropertyLedger.ts";
export { useBuyerLedger } from "./hooks/useBuyerLedger.ts";
export type { BuyerLedger } from "./hooks/useBuyerLedger.ts";
export { useComplexOptions } from "./hooks/useComplexOptions.ts";
export type { ComplexOption } from "./hooks/useComplexOptions.ts";
export type { CollectionState, CollectionStatus, LedgerCollection } from "./hooks/useLedgerCollection.ts";

export type { ColumnFilters, ListQuery } from "./api/transport.ts";
export { LedgerApiError, describeForUser, isCanceled } from "./api/errors.ts";
export type { LedgerErrorKind } from "./api/errors.ts";
export { canMutate, setCsrfToken } from "./api/session.ts";

export { EMPTY_VALUE, MAX_PAGE_SIZE } from "./model/dto.ts";
export type { BuyerRow, LedgerRow, PropertyRow, RowSyncState, SaveState } from "./model/row.ts";
export { isBuyerRow, isPropertyRow, isUnsavedDraft } from "./model/row.ts";

export { formatMoney, parseMoney } from "./model/money.ts";
export { formatPyeong, formatPyeongList, parsePyeong, parsePyeongList } from "./model/area.ts";
export { addYears, todayDate } from "./model/dates.ts";
export { formatPhone, isSamePhone, maskPhone, normalizePhone } from "./model/phone.ts";
export {
  CONTACTABILITY,
  DEMAND_TYPE,
  LIFECYCLE_STATUS,
  ORIENTATION,
  REQUIREMENT_STATUS,
  labelsOf,
} from "./model/codes.ts";
