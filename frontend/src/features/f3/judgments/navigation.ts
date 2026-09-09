import type { AnchorType } from "../model/dto.ts";
export interface JudgmentSelection {
  anchor_type: AnchorType;
  anchor_id: number;
  result_id: number | null;
  candidate_id?: number;
}
function positive(value: string | null): number | null {
  if (value == null || !/^[1-9]\d*$/.test(value)) return null;
  const n = Number(value);
  return Number.isSafeInteger(n) ? n : null;
}
export function readJudgmentLocation(search: string): {
  active: boolean;
  selection: JudgmentSelection | null;
} {
  const p = new URLSearchParams(search);
  const active = p.get("view") === "f3-judgments";
  const type = p.get("anchor_type");
  const id = positive(p.get("anchor_id"));
  return {
    active,
    selection:
      active && (type === "LISTING" || type === "REQUIREMENT") && id != null
        ? {
            anchor_type: type,
            anchor_id: id,
            result_id: positive(p.get("result_id")),
            ...(positive(p.get("candidate_id")) != null
              ? { candidate_id: positive(p.get("candidate_id"))! }
              : {}),
          }
        : null,
  };
}
export function writeJudgmentLocation(
  selection: JudgmentSelection | null,
  active = true,
): void {
  const p = new URLSearchParams(window.location.search);
  for (const key of [
    "view",
    "anchor_type",
    "anchor_id",
    "result_id",
    "candidate_id",
  ])
    p.delete(key);
  if (active) {
    p.set("view", "f3-judgments");
    if (selection) {
      p.set("anchor_type", selection.anchor_type);
      p.set("anchor_id", String(selection.anchor_id));
      if (selection.result_id) p.set("result_id", String(selection.result_id));
      if (selection.candidate_id)
        p.set("candidate_id", String(selection.candidate_id));
    }
  }
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${p.size ? `?${p}` : ""}${window.location.hash}`,
  );
}
