import { useEffect, useRef, useState } from "react";
import { loadSavedBuyer, loadSavedProperty } from "../../ledger/index.ts";
import type { BuyerRow, PropertyRow } from "../../ledger/index.ts";
import { ApiError } from "../../../shared/api/index.ts";
import { judgmentError } from "./useJudgmentTarget.ts";
import type { TargetIdentity } from "./model.ts";
export function useJudgmentLedgerNavigation(
  userKey: string,
  onOpen: (row: BuyerRow | PropertyRow) => void,
  onSessionExpired: () => void,
  onError: (message: string) => void,
) {
  const controller = useRef<AbortController | null>(null);
  const [evidence, setEvidence] = useState<{
    target: TargetIdentity;
    interactionId: number;
  } | null>(null);
  useEffect(() => {
    setEvidence(null);
    return () => controller.current?.abort();
  }, [userKey]);
  const open = async (target: TargetIdentity, interactionId?: number) => {
    if (interactionId != null) {
      setEvidence({ target, interactionId });
      return;
    }
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    try {
      if (target.anchor_type === "LISTING" && target.property_unit_id == null)
        throw new ApiError({ kind: "notFound", message: "장부 없음" });
      const row =
        target.anchor_type === "LISTING"
          ? await loadSavedProperty(
              target.property_unit_id!,
              c.signal,
              target.anchor_id,
            )
          : await loadSavedBuyer(target.anchor_id, c.signal);
      if (!c.signal.aborted) onOpen(row);
    } catch (cause) {
      if (c.signal.aborted) return;
      if (cause instanceof ApiError && cause.kind === "unauthorized")
        onSessionExpired();
      else onError(judgmentError(cause));
    }
  };
  return { open, evidence, closeEvidence: () => setEvidence(null) };
}
