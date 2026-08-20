/**
 * 거래유형 표시와 편집.
 *
 * 서버는 매매·전세·월세를 각각 독립된 boolean(`is_sale_available` 등)으로 갖는다.
 * 한 매물이 매매와 전세로 동시에 나올 수 있다는 뜻이다. 그래서 화면에서도 한 가지로 좁히지 않고
 * `매매·전세`처럼 이어 붙여 보여주고, 같은 형태를 그대로 받는다.
 *
 * 그리드와 상세가 이 규칙을 공유해야 한다. 한쪽만 단일 선택으로 두면 상세를 열었다 저장하는
 * 것만으로 다른 유형이 조용히 지워진다.
 */

export const DEAL_TYPES = ["매매", "전세", "월세"] as const;

/**
 * 드롭다운 선택지. 한 매물은 한 가지 유형으로 다룬다는 업무 규칙에 따라 세 가지만 고른다.
 *
 * 서버 스키마는 세 값을 독립 boolean으로 갖고 있어 둘 이상이 켜진 데이터가 들어올 수는 있다.
 * 그런 행은 `dealTypeValue`가 `매매·전세`처럼 이어 붙여 보여주고, 사용자가 유형을 다시 고르면
 * 고른 하나만 남는다.
 */
export const DEAL_TYPE_CHOICES = [...DEAL_TYPES];

interface DealTypeFields {
  saleFlag: string;
  leaseFlag: string;
  monthlyFlag: string;
  listingType: string;
}

/** 화면에 보여줄 거래유형 문자열. 플래그가 비어 있으면 대표 유형으로 떨어진다. */
export function dealTypeValue(row: Partial<DealTypeFields> | null | undefined): string {
  const active = [
    row?.saleFlag === "Y" ? "매매" : "",
    row?.leaseFlag === "Y" ? "전세" : "",
    row?.monthlyFlag === "Y" ? "월세" : "",
  ].filter(Boolean);
  if (active.length > 0) return active.join("·");
  return row?.listingType ?? "";
}

/** 입력값을 플래그와 대표 유형으로 되돌린다. `매매·전세`, `매매, 전세`, `매매 전세` 모두 받는다. */
export function dealTypePatch(next: string | null | undefined): DealTypeFields {
  const tokens = String(next ?? "")
    .split(/[·,/\s]+/)
    .map((token) => token.trim())
    .filter(Boolean);
  const chosen = DEAL_TYPES.filter((type) => tokens.includes(type));

  return {
    saleFlag: chosen.includes("매매") ? "Y" : "",
    leaseFlag: chosen.includes("전세") ? "Y" : "",
    monthlyFlag: chosen.includes("월세") ? "Y" : "",
    // 대표 유형은 금액 표시와 저장 payload가 함께 쓴다.
    listingType: chosen[0] ?? "",
  };
}

/** 그리드 valueSetter용. 행을 그 자리에서 고치고 성공 여부를 돌려준다. */
export function applyDealType(row: Record<string, unknown> | null | undefined, next: string): boolean {
  if (row == null) return false;
  Object.assign(row, dealTypePatch(next));
  return true;
}
