import { APP_ENV } from "../../../config/env.ts";
import { getCsrfToken } from "../../ledger/api/session.ts";

type LedgerType = "property" | "buyer";

interface AnalyzeVoiceMemoInput {
  audio: File;
  ledgerType: LedgerType;
  draft: Record<string, unknown>;
  signal?: AbortSignal;
}

export interface VoiceProposal {
  id: string;
  field: string;
  fieldKey: string | null;
  current: string;
  proposal: string;
  evidence: string;
  status: string;
  selected: boolean;
}

export interface VoiceAnalysis {
  consultationType: string;
  ledgerMismatch: boolean;
  proposals: VoiceProposal[];
  uncertainties: string[];
  privacyConfirmedAt: string;
}

interface FieldBinding {
  fieldKey: string;
  label: string;
}

const PROPERTY_FIELDS: Record<string, FieldBinding> = {
  "단지": { fieldKey: "complex", label: "단지" },
  "평형": { fieldKey: "area", label: "평형" },
  "동": { fieldKey: "building", label: "동" },
  "호": { fieldKey: "unit", label: "호" },
  "타입": { fieldKey: "listingType", label: "거래 유형" },
  "방향": { fieldKey: "direction", label: "방향" },
  "현상태": { fieldKey: "householdState", label: "현 상태" },
  "현재 보증금": { fieldKey: "deposit", label: "현재 보증금" },
  "현재 차임": { fieldKey: "rent", label: "현재 차임" },
  "만기일": { fieldKey: "expiry", label: "계약 만기일" },
  "매매가": { fieldKey: "price", label: "매매가" },
  "전세보증금": { fieldKey: "deposit", label: "전세보증금" },
  "월세 보증금": { fieldKey: "deposit", label: "월세 보증금" },
  "월세 차임": { fieldKey: "rent", label: "월세 차임" },
  "명도 조건": { fieldKey: "moveIn", label: "명도 조건" },
  "임대인": { fieldKey: "owner", label: "임대인" },
  "임대인 전화": { fieldKey: "phone", label: "임대인 전화" },
  "임차인": { fieldKey: "tenant", label: "임차인" },
  "담당자": { fieldKey: "assignee", label: "담당자" },
  "비고": { fieldKey: "memo", label: "비고" },
};

const BUYER_FIELDS: Record<string, FieldBinding> = {
  "접수일": { fieldKey: "date", label: "접수일" },
  "거래 구분": { fieldKey: "category", label: "거래 구분" },
  "희망 단지": { fieldKey: "complex", label: "희망 단지" },
  "희망 지역": { fieldKey: "complex", label: "희망 지역" },
  "희망 평형": { fieldKey: "area", label: "희망 평형" },
  "금액 원문": { fieldKey: "budget", label: "금액 조건" },
  "이사일 원문": { fieldKey: "moveDate", label: "이사일" },
  "구입자 이름": { fieldKey: "buyer", label: "손님 이름" },
  "구입자 별칭": { fieldKey: "buyer", label: "손님 별칭" },
  "전화번호": { fieldKey: "phone", label: "전화번호" },
  "관련 중개업소": { fieldKey: "brokerage", label: "관련 부동산" },
  "진행단계": { fieldKey: "stage", label: "진행 단계" },
  "완료 여부": { fieldKey: "completion", label: "완료 여부" },
  "담당자": { fieldKey: "assignee", label: "담당자" },
  "분류": { fieldKey: "classification", label: "분류" },
  "비고": { fieldKey: "memo", label: "비고" },
};

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function currentFields(ledgerType: LedgerType, draft: Record<string, unknown>): Record<string, string | null> {
  const bindings = ledgerType === "buyer" ? BUYER_FIELDS : PROPERTY_FIELDS;
  return Object.fromEntries(
    Object.entries(bindings).map(([serverField, binding]) => {
      const value = stringValue(draft[binding.fieldKey]).trim();
      return [serverField, value === "" ? null : value];
    }),
  );
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} 응답 형식이 올바르지 않습니다.`);
  }
  return value as Record<string, unknown>;
}

function requiredString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`F2 응답의 ${key} 값이 올바르지 않습니다.`);
  }
  return value;
}

function decodeAnalysis(value: unknown, ledgerType: LedgerType, draft: Record<string, unknown>): VoiceAnalysis {
  const body = asRecord(value, "F2");
  const rawProposals = body["proposals"];
  const rawUncertainties = body["uncertainties"];
  if (!Array.isArray(rawProposals) || !Array.isArray(rawUncertainties)) {
    throw new Error("F2 제안 응답 형식이 올바르지 않습니다.");
  }

  const bindings = ledgerType === "buyer" ? BUYER_FIELDS : PROPERTY_FIELDS;
  const proposals = rawProposals.map((raw, index): VoiceProposal => {
    const proposal = asRecord(raw, "F2 제안");
    const fieldName = requiredString(proposal, "field_name");
    const binding = bindings[fieldName];
    const current = proposal["current_value"];
    const selectedByDefault = proposal["selected_by_default"];
    return {
      id: `${fieldName}-${index}`,
      field: binding?.label ?? fieldName,
      fieldKey: binding?.fieldKey ?? null,
      current: typeof current === "string" && current.trim() !== "" ? current : "미입력",
      proposal: requiredString(proposal, "proposed_value"),
      evidence: requiredString(proposal, "evidence"),
      status: requiredString(proposal, "status"),
      selected: binding != null && selectedByDefault === true,
    };
  });

  const logFieldKey = ledgerType === "buyer" ? "content" : "log";
  const logCurrent = stringValue(draft[logFieldKey]);
  const logDraft = requiredString(body, "consultation_log_draft");
  proposals.push({
    id: "consultation-log",
    field: "상담 로그",
    fieldKey: logFieldKey,
    current: logCurrent.trim() === "" ? "미입력" : logCurrent,
    proposal: logDraft,
    evidence: "음성메모 전체 내용의 요약",
    status: logCurrent.trim() === "" ? "확인됨" : "변경",
    selected: logCurrent.trim() === "",
  });

  return {
    consultationType: requiredString(body, "consultation_type"),
    ledgerMismatch: body["ledger_mismatch"] === true,
    proposals,
    uncertainties: rawUncertainties.filter((item): item is string => typeof item === "string"),
    privacyConfirmedAt: requiredString(body, "privacy_confirmed_at"),
  };
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = asRecord(await response.json(), "오류");
    if (typeof body["message"] === "string") return body["message"];
  } catch {
    // JSON 오류 계약이 아니면 상태 코드만 사용한다.
  }
  return `음성메모 분석 요청이 실패했습니다 (HTTP ${response.status}).`;
}

export async function analyzeVoiceMemo(input: AnalyzeVoiceMemoInput): Promise<VoiceAnalysis> {
  const csrfToken = getCsrfToken();
  if (csrfToken == null) throw new Error("세션을 확인한 뒤 다시 시도해 주세요.");

  const form = new FormData();
  form.append("audio", input.audio, input.audio.name);
  form.append("ledger_type", input.ledgerType === "buyer" ? "구입장" : "매물장");
  form.append("current_fields", JSON.stringify(currentFields(input.ledgerType, input.draft)));
  form.append("privacy_confirmed", "true");

  const response = await fetch(
    `${APP_ENV.apiBaseUrl.replace(/\/$/, "")}/f2/analyses`,
    {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfToken },
      body: form,
      signal: input.signal,
    },
  );
  if (!response.ok) throw new Error(await errorMessage(response));
  return decodeAnalysis(await response.json(), input.ledgerType, input.draft);
}
