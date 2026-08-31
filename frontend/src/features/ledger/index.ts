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
export type { ComplexCreateInput, ComplexOption, ComplexOptions } from "./hooks/useComplexOptions.ts";
export type { CollectionState, CollectionStatus, LedgerCollection } from "./hooks/useLedgerCollection.ts";

export type { ColumnFilters, ListQuery } from "./api/transport.ts";
// 오류 분류(`ApiError`, `isCanceled`)와 CSRF 보관소는 `shared/api`가 소유한다. 장부를 거쳐
// 가져가면 다른 기능이 장부에 의존하게 되므로 여기서 다시 내보내지 않는다.
export { describeForUser } from "./api/errors.ts";

export { EMPTY_VALUE, MAX_PAGE_SIZE } from "./model/dto.ts";
export type { BuyerRow, LedgerRow, PropertyRow, RowSyncState, SaveState } from "./model/row.ts";
export { carrySavedIdentity, isBuyerRow, isPropertyRow, isUnsavedDraft } from "./model/row.ts";
export { isEmptyDraft } from "./model/draft.ts";

export { formatMoney, parseMoney } from "../../shared/format/index.ts";
export { formatPyeong, formatPyeongList, parsePyeong, parsePyeongList } from "../../shared/format/index.ts";
export { addYears, todayDate } from "./model/dates.ts";
export { formatPhone, formatPhoneInput, isSamePhone, maskPhone, nextPhoneInput, normalizePhone } from "./model/phone.ts";
export {
  CONTACTABILITY,
  DEMAND_TYPE,
  LIFECYCLE_STATUS,
  ORIENTATION,
  REQUIREMENT_STATUS,
  labelsOf,
} from "./model/codes.ts";
