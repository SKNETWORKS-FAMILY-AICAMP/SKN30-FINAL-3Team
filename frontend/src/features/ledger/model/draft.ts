/**
 * 빈 행 판별.
 *
 * F1-GR-30은 값이 없는 빈 행이 화면에 존재할 수 있게 하고, F1-GR-32는 저장하지 않고 닫은
 * 빈 행을 그리드에 남기지 않게 한다. 두 규칙을 잇는 판별이라 매퍼가 아니라 여기에 둔다.
 * (매퍼는 장부별로 나뉘어 있고, 이 판별은 두 장부를 함께 다룬다.)
 */

import { createBuyerDraftRow } from "./buyerMapper.ts";
import { createPropertyDraftRow } from "./propertyMapper.ts";
import type { LedgerRow } from "./row.ts";
import { isBuyerRow, isUnsavedDraft } from "./row.ts";

/**
 * 값이 아니라 행의 신원과 동기화 상태를 담는 필드.
 *
 * 빈 행도 저장 상태는 "임시저장"이고 저장 실패가 남으면 sync가 달라진다.
 * 사용자가 무엇을 적었는지와 무관하므로 비교에서 제외한다.
 */
const META_KEYS = new Set(["id", "serverId", "rowVersion", "sync", "customFields", "saveState"]);

/**
 * 사용자가 값을 하나도 넣지 않은 미저장 행인지.
 *
 * 갓 만든 빈 행과 값을 비교한다. 필드 목록을 따로 적으면 행 모델에 열이 늘 때마다
 * 같이 고쳐야 하고, 빠뜨린 열은 값이 있어도 빈 행으로 취급된다.
 * 상세 화면이 붙이는 화면 전용 필드(`people`, `f2Draft` 등)는 빈 행 원형에 없으므로 보지 않는다.
 */
export function isEmptyDraft(row: LedgerRow | null | undefined): boolean {
  if (row == null || !isUnsavedDraft(row)) return false;

  const blank: Record<string, unknown> = { ...(isBuyerRow(row) ? createBuyerDraftRow(row.id) : createPropertyDraftRow(row.id)) };
  const current = row as unknown as Record<string, unknown>;
  return Object.keys(blank).every(
    (key) => META_KEYS.has(key) || JSON.stringify(current[key] ?? null) === JSON.stringify(blank[key] ?? null),
  );
}
