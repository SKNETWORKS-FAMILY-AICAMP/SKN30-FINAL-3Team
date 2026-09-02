import { APP_ENV } from "../../../config/env.ts";
import { ApiError, apiErrorFromResponse, getCsrfToken } from "../../../shared/api/index.ts";
import type { LedgerType } from "../model/consultationRouting.ts";
import { routeConsultation } from "../model/consultationRouting.ts";

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
  // 상세의 명도 칸이다. 예전 `moveIn`은 같은 값을 받던 중복 칸이라 없앴다.
  "명도 조건": { fieldKey: "clearance", label: "명도 조건" },
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

export async function analyzeVoiceMemo(input: AnalyzeVoiceMemoInput): Promise<VoiceAnalysis> {
  const csrfToken = getCsrfToken();
  if (csrfToken == null) {
    throw new ApiError({
      kind: "unauthorized",
      message: "CSRF 토큰이 없습니다.",
      code: "UNAUTHENTICATED",
    });
  }

  const form = new FormData();
  form.append("audio", input.audio, input.audio.name);
  form.append("ledger_type", input.ledgerType === "buyer" ? "구입장" : "매물장");
  form.append("current_fields", JSON.stringify(currentFields(input.ledgerType, input.draft)));
  form.append("privacy_confirmed", "true");

  let response: Response;
  try {
    response = await fetch(`${APP_ENV.apiBaseUrl.replace(/\/$/, "")}/f2/analyses`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfToken },
      body: form,
      signal: input.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw new ApiError({ kind: "canceled", message: "요청이 취소되었습니다.", cause });
    }
    throw new ApiError({ kind: "offline", message: "네트워크 요청에 실패했습니다.", cause });
  }

  if (!response.ok) throw await apiErrorFromResponse(response);

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (cause) {
    throw new ApiError({
      kind: "contract",
      message: "F2 응답을 JSON으로 해석하지 못했습니다.",
      status: response.status,
      cause,
    });
  }

  try {
    return decodeAnalysis(payload, input.ledgerType, input.draft);
  } catch (cause) {
    throw new ApiError({
      kind: "contract",
      message: cause instanceof Error ? cause.message : "F2 응답이 계약과 다릅니다.",
      status: response.status,
      cause,
    });
  }
}

export interface IntakeAnalysis extends VoiceAnalysis {
  /** 이 분석 결과로 신규 행을 만들 장부. */
  ledgerType: LedgerType;
  /**
   * 상담 유형이 매도·매수 의뢰가 아니어서 장부를 판정하지 못하고 기본 장부를 쓴 경우.
   * 화면은 이 값이 true면 사용자에게 직접 확인하라고 알린다.
   */
  usedFallbackLedger: boolean;
}

/**
 * 장부를 정하지 않은 신규 접수의 기준 장부.
 *
 * 어떤 장부로 보낼지는 분석 결과를 봐야 알 수 있으므로 한쪽을 먼저 정해 보낸다.
 * 매도의뢰가 매물장 기본 흐름이라 매물장을 기준으로 둔다.
 */
const PROBE_LEDGER: LedgerType = "property";

/**
 * 장부를 정하지 않은 신규 음성메모 접수.
 *
 * 상담 유형으로 장부를 고르고 그 장부의 필드 제안을 돌려준다.
 * 계약상 장부와 상담 유형이 어긋난 분석은 필드 제안을 만들지 않으므로,
 * 기준 장부와 판정이 다르면 판정된 장부로 한 번 더 분석해야 손님·세대 정보를 제안으로 받는다.
 * 매수문의 한 유형에서만 요청이 두 번 나간다.
 */
export async function analyzeNewIntake(input: { audio: File; signal?: AbortSignal }): Promise<IntakeAnalysis> {
  const probe = await analyzeVoiceMemo({
    audio: input.audio,
    ledgerType: PROBE_LEDGER,
    draft: {},
    signal: input.signal,
  });

  const routed = routeConsultation(probe.consultationType);
  if (routed == null) return { ...probe, ledgerType: PROBE_LEDGER, usedFallbackLedger: true };
  if (routed === PROBE_LEDGER) return { ...probe, ledgerType: routed, usedFallbackLedger: false };

  const matched = await analyzeVoiceMemo({
    audio: input.audio,
    ledgerType: routed,
    draft: {},
    signal: input.signal,
  });
  return { ...matched, ledgerType: routed, usedFallbackLedger: false };
}
