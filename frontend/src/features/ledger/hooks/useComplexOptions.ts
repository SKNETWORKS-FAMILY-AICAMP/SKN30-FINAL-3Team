/**
 * 단지 선택지.
 *
 * 알려진 제약: 계약에 **단지 목록 엔드포인트가 없다**.
 * 그래서 마스터를 직접 조회하지 못하고, 이미 불러온 매물장 행에 실려 온 `complex`에서 추려 쓴다.
 *
 * 한계가 분명하다. 세대가 한 건도 없는 단지는 목록에 나타나지 않고,
 * 새 단지를 만들 방법도 없다. 단지 마스터 API가 생기면 이 파일만 교체한다.
 */

import { useMemo } from "react";
import type { PropertyRow } from "../model/row.ts";

export interface ComplexOption {
  id: number;
  name: string;
  address: string;
}

/** 불러온 매물장 행에서 단지를 추린다. 이름 오름차순으로 중복 없이 돌려준다. */
export function useComplexOptions(rows: readonly PropertyRow[]): ComplexOption[] {
  return useMemo(() => {
    const byId = new Map<number, ComplexOption>();
    for (const row of rows) {
      if (row.complexId == null || row.complex === "") continue;
      if (!byId.has(row.complexId)) {
        byId.set(row.complexId, { id: row.complexId, name: row.complex, address: "" });
      }
    }
    return [...byId.values()].sort((left, right) => left.name.localeCompare(right.name, "ko"));
  }, [rows]);
}
