import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Skeleton,
} from "@patternfly/react-core";
import { loadSavedInteraction } from "../../ledger/index.ts";
import { ApiError } from "../../../shared/api/index.ts";
import type { TargetIdentity } from "./model.ts";
import { dateLabel } from "./model.ts";
import { judgmentError } from "./useJudgmentTarget.ts";
export function JudgmentEvidenceModal({
  evidence,
  onClose,
  onSessionExpired,
}: {
  evidence: { target: TargetIdentity; interactionId: number } | null;
  onClose: () => void;
  onSessionExpired: () => void;
}) {
  const [record, setRecord] = useState<Awaited<
    ReturnType<typeof loadSavedInteraction>
  > | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    setRecord(null);
    setError("");
    if (!evidence) return;
    const c = new AbortController();
    const scope =
      evidence.target.anchor_type === "LISTING"
        ? { unitId: evidence.target.property_unit_id ?? undefined }
        : { requirementId: evidence.target.anchor_id };
    if (scope.unitId == null && scope.requirementId == null) {
      setError("현재 접근할 수 없는 원본입니다.");
      return;
    }
    void loadSavedInteraction(scope, evidence.interactionId, c.signal)
      .then((value) => {
        if (!c.signal.aborted) setRecord(value);
      })
      .catch((cause) => {
        if (c.signal.aborted) return;
        setError(judgmentError(cause));
        if (cause instanceof ApiError && cause.kind === "unauthorized")
          onSessionExpired();
      });
    return () => c.abort();
  }, [evidence, refresh, onSessionExpired]);
  return (
    <Modal
      isOpen={evidence != null}
      onClose={onClose}
      variant="medium"
      aria-label="판정 근거 원본 상담"
    >
      <ModalHeader
        title="원본 상담"
        description={
          evidence
            ? `${evidence.target.display_name} · 상담 #${evidence.interactionId}`
            : ""
        }
      />
      <ModalBody>
        {record ? (
          <>
            <p>
              {dateLabel(record.interaction_at ?? record.created_at)} · 대상
              일반 상담
            </p>
            <p style={{ whiteSpace: "pre-wrap" }}>
              {record.interaction_content}
            </p>
          </>
        ) : error ? (
          <Alert variant="warning" isInline title={error}>
            <Button
              variant="link"
              isInline
              onClick={() => setRefresh((v) => v + 1)}
            >
              다시 조회
            </Button>
          </Alert>
        ) : (
          <Skeleton screenreaderText="원본 상담 조회 중" />
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onClose}>
          목록으로 돌아가기
        </Button>
      </ModalFooter>
    </Modal>
  );
}
