/**
 * 후보 표시 이름을 이미 불러온 F1 장부에서 찾는다.
 *
 * 결과 조회 응답은 후보의 성명·연락처·표시 이름을 싣지 않는다(`contracts/api.md`). 사람이
 * 식별할 이름이 필요하지만, 후보마다 장부 단건 조회를 하면 화면이 쓰지 않는 인물 정보까지
 * 응답으로 받게 되고 후보 수만큼 요청이 나간다. 개인정보 정책의 "목적에 필요한 최소
 * 개인정보만 수집한다"와 어긋난다.
 *
 * 그래서 이미 화면에 올라와 있는 장부 행에서만 찾는다. 없으면 식별자만 보여주고 판정 내용은
 * 그대로 그린다. 제목 하나 때문에 이미 받은 판정을 감추지 않는다.
 *
 * 장부 종류별로 맵을 나눈다. 매물 ID와 구입장 ID는 각자 다른 테이블의 식별자라 한 맵에 담으면
 * 서로 다른 행이 같은 키로 겹친다.
 */

import type { BuyerRow, PropertyRow } from "../../ledger/index.ts";
import type { AnchorType } from "./dto.ts";

/** 후보 한 건의 표시값. 장부에서 찾지 못하면 `found`가 false다. */
export interface CandidateLabel {
  title: string;
  /** 부제. 매물이면 평형·거래 유형, 구입장이면 희망 평형이다. 없으면 빈 문자열이다. */
  subtitle: string;
  /**
   * 문자 작성에 넘길 연락처.
   *
   * 매물장 목록 응답에는 인물이 없어 매물 후보는 항상 빈 값이다. 화면은 "연락처 없음"으로
   * 표시하고, 실제 발송은 F1이 최신 연락처와 동의를 다시 확인하는 시점에 한다.
   */
  phone: string;
  found: boolean;
}

/**
 * 후보 식별자로 장부 행을 찾기 위한 색인.
 *
 * `requirements`의 키는 `property_requirement.id`, `listings`의 키는 `property_listing.id`다.
 * 매물장 행의 서버 식별자는 **세대** ID이고 후보 식별자는 **매물 건** ID이므로 `listingId`로
 * 색인한다. 세대 ID로 색인하면 조용히 아무것도 찾지 못한다.
 */
export interface LedgerIndex {
  requirements: Map<number, BuyerRow>;
  listings: Map<number, PropertyRow>;
}

export const EMPTY_LEDGER_INDEX: LedgerIndex = {
  requirements: new Map(),
  listings: new Map(),
};

export function indexLedgerRows(
  propertyRows: readonly PropertyRow[],
  buyerRows: readonly BuyerRow[],
): LedgerIndex {
  const requirements = new Map<number, BuyerRow>();
  for (const row of buyerRows) {
    if (row.serverId != null) requirements.set(row.serverId, row);
  }

  const listings = new Map<number, PropertyRow>();
  for (const row of propertyRows) {
    if (row.listingId != null) listings.set(row.listingId, row);
  }

  return { requirements, listings };
}

/** 후보 장부 종류. 앵커의 반대편이다. */
export function candidateSideOf(anchorType: AnchorType): AnchorType {
  return anchorType === "LISTING" ? "REQUIREMENT" : "LISTING";
}

/**
 * 후보 표시값.
 *
 * 앵커가 매물이면 후보는 구입장이고, 앵커가 구입장이면 후보는 매물이다. 한쪽 표기를 양쪽에
 * 쓰면 손님 상세에서 매물을 "구입장"이라고 부르게 된다.
 */
export function labelFor(
  candidateId: number,
  anchorType: AnchorType,
  ledger: LedgerIndex,
): CandidateLabel {
  if (candidateSideOf(anchorType) === "REQUIREMENT") {
    return requirementLabel(candidateId, ledger.requirements.get(candidateId));
  }
  return listingLabel(candidateId, ledger.listings.get(candidateId));
}

function requirementLabel(candidateId: number, row: BuyerRow | undefined): CandidateLabel {
  if (row == null) {
    return { title: `구입장 #${candidateId}`, subtitle: "", phone: "", found: false };
  }
  // 장부 표기 그대로 쓴다. 별칭이 있으면 별칭이 이름 자리에 온다(F1 매퍼 규칙).
  const name = row.buyer || "별칭 미입력";
  const complex = row.complex || "희망 단지 없음";
  return {
    title: `${name} · ${complex}`,
    subtitle: [row.category, row.area].filter(Boolean).join(" · "),
    phone: row.phone,
    found: true,
  };
}

function listingLabel(candidateId: number, row: PropertyRow | undefined): CandidateLabel {
  if (row == null) {
    return { title: `매물 #${candidateId}`, subtitle: "", phone: "", found: false };
  }
  const complex = row.complex || "단지 미입력";
  const building = row.building ? `${row.building}동` : "";
  const unit = row.unit ? `${row.unit}호` : "";
  return {
    title: [complex, building, unit].filter(Boolean).join(" "),
    subtitle: [row.area, row.listingType].filter(Boolean).join(" · "),
    // 목록 응답에는 인물이 없다. 상세를 연 행만 채워져 있다.
    phone: row.ownerPhone,
    found: true,
  };
}
