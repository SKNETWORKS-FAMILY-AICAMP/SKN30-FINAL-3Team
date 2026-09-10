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

/** 금액 칸 하나와 그 칸이 뜻하는 거래유형. */
export type PriceField = "salePrice" | "leaseDeposit" | "rentCondition";

const PRICE_FIELD_TYPE: Record<PriceField, string> = {
  salePrice: "매매",
  leaseDeposit: "전세",
  rentCondition: "월세",
};

/**
 * 금액 칸 입력 하나를 행 변경으로 바꾼다.
 *
 * 거래유형을 고르지 않은 채 금액만 적는 경로가 있다. 그대로 두면 저장 payload가 세 플래그를
 * 모두 false로 보내 방금 적은 금액이 조용히 사라진다. 매매가를 적는 행위 자체가 매매 건이라는
 * 뜻이므로 그 유형을 함께 켠다. 값을 지우는 입력은 유형을 켜지 않는다.
 *
 * 이미 고른 유형은 건드리지 않는다. 여기서 유형을 바꿔 버리면 매매 건의 전세보증금을 참고로
 * 적어 두는 것만으로 매물이 전세로 뒤집힌다.
 */
export function priceFieldPatch(
  row: Partial<DealTypeFields> | null | undefined,
  field: PriceField,
  value: string,
): Record<string, string> {
  const listingType = PRICE_FIELD_TYPE[field];
  if (value.trim() !== "" && dealTypeValue(row) === "") {
    return { [field]: value, ...dealTypePatch(listingType), price: value };
  }
  // 대표 금액은 지금 고른 유형의 금액만 따라간다.
  return row?.listingType === listingType ? { [field]: value, price: value } : { [field]: value };
}
