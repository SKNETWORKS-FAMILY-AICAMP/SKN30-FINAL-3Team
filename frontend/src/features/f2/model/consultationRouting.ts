/**
 * 상담 유형에서 신규 행을 만들 장부를 고르는 정책.
 *
 * 계약상 상담 유형은 매도의뢰·매수문의·공동중개·단순문의 네 가지이고, 필드 제안은
 * `매물장 + 매도의뢰`와 `구입장 + 매수문의`에서만 만들어진다. 나머지 두 유형은 어느 장부로
 * 분석해도 필드 제안이 없으므로 여기서 장부를 단정하지 않고 `null`을 돌려준다.
 * 기본 장부를 무엇으로 할지는 호출부가 정한다.
 */

export type LedgerType = "property" | "buyer";

/** 상담 유형별 장부. 계약값 외에 화면에서 같은 뜻으로 불려 온 표기도 함께 받는다. */
const LEDGER_BY_CONSULTATION: ReadonlyMap<string, LedgerType> = new Map([
  ["매도의뢰", "property"],
  ["매도문의", "property"],
  ["매수문의", "buyer"],
  ["매수의뢰", "buyer"],
]);

export const LEDGER_LABEL: Record<LedgerType, string> = {
  property: "매물장",
  buyer: "구입장",
};

/**
 * 상담 유형에 대응하는 장부. 매도·매수 의뢰가 아니면 `null`.
 *
 * 입력은 서버 응답 문자열이므로 열거형으로 좁히지 않고 문자열 그대로 받는다.
 */
export function routeConsultation(consultationType: string): LedgerType | null {
  return LEDGER_BY_CONSULTATION.get(consultationType.trim()) ?? null;
}
