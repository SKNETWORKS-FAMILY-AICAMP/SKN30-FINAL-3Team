import type { ChatbotRequest } from "./types.ts";

const STAGES: Record<string, string> = {
  accepted: "질문을 접수했어요", interpreting: "검색 조건 해석 중", searching: "장부 조회 중",
  searching_properties: "매물장 조회 중", searching_buyers: "구입장 조회 중", searching_agenda: "일정·할 일 조회 중",
  completed: "답변 완료", failed: "답변 실패", cancelled: "처리 중지됨", interrupted: "처리 중단됨",
};
export function progressLabel(request: ChatbotRequest | null): string {
  if (request === null) return "질문을 입력해 주세요";
  if (request.status === "FAILED") {
    const failures: Record<string, string> = {
      CHATBOT_CONTEXT_LIMIT: "참고할 내용이 입력 한도를 넘었어요. 질문을 줄이거나 검색 조건을 초기화한 뒤 다시 보내 주세요. 대화 이력은 유지돼요.",
      CHATBOT_INVALID_OUTPUT: "답변의 검색 조건을 확인하지 못했어요. 조건을 구체적으로 적어 다시 보내 주세요.",
      CHATBOT_TIMEOUT: "답변 준비 시간이 초과됐어요. 조건을 좁히거나 잠시 후 다시 시도해 주세요.",
      CHATBOT_BUSY: "지금 다른 요청을 처리하고 있어요. 잠시 후 다시 시도해 주세요.",
      CHATBOT_UNAVAILABLE: "지금 답변 서비스를 사용할 수 없어요. 잠시 후 다시 시도하거나 장부 화면을 이용해 주세요.",
    };
    return failures[request.failure_code ?? ""] ?? "답변을 완료하지 못했어요. 질문을 확인하고 다시 시도해 주세요.";
  }
  if (request.status === "INTERRUPTED") return "서버가 중단되어 답변을 완료하지 못했어요. 다시 시도해 주세요.";
  if (request.status === "CANCELLED") return "요청을 중지했어요.";
  if (request.status === "COMPLETED") return "답변을 저장했어요.";
  return STAGES[request.stage] ?? "질문 처리 중";
}
const LABELS: Record<string, string> = {
  tool: "조회 대상", kind: "조회 대상", intent: "조회 대상", complex_name: "단지", complex_id: "단지 번호",
  transaction_type: "거래", transaction_types: "거래", trade_type: "거래", property_type: "매물 종류",
  min_price: "최소 금액", max_price: "최대 금액", min_price_amount: "최소 금액", max_price_amount: "최대 금액",
  min_budget: "최소 예산", max_budget: "최대 예산", budget_min: "최소 예산", budget_max: "최대 예산",
  min_area_sqm: "최소 면적(㎡)", max_area_sqm: "최대 면적(㎡)", area_basis: "면적 기준",
  date_from: "시작일", date_to: "종료일", start_date: "시작일", end_date: "종료일",
  category: "일정 종류", categories: "일정 종류", sort: "정렬", status: "상태",
  price_expression: "금액", deposit_expression: "보증금", rent_expression: "월세", area_expression: "면적", date_expression: "기간",
};
const VALUES: Record<string, string> = {
  properties: "매물장", buyers: "구입장", agenda: "일정·할 일", SALE: "매매", JEONSE: "전세", MONTHLY: "월세",
  sale: "매매", jeonse: "전세", monthly: "월세", exclusive: "전용", supply: "공급", exclusive_area_sqm: "전용", supply_area_sqm: "공급",
  RENT: "월세", recent: "최근 순", RECEIVED: "접수", ACTIVE: "진행",
  price_asc: "가격 낮은 순", price_desc: "가격 높은 순", date_asc: "날짜 빠른 순", latest: "최근 순",
  TENANCY_EXPIRY: "임대차 만기", CLIENT_TENANCY_EXPIRY: "손님 임대차 만기", REQUEST_EXPIRY: "의뢰 만료",
  MOVE_IN: "입주", LISTING_RECONTACT: "매물 재연락", CLIENT_RECONTACT: "손님 재연락", LISTING_REVALIDATION: "매물 재확인",
};
export function filterLabels(filters: Record<string, unknown>): string[] {
  const result: string[] = [];
  for (const [key, value] of Object.entries(filters)) {
    if ((key === "filters" || key === "conditions") && value && typeof value === "object" && !Array.isArray(value)) {
      result.push(...filterLabels(value as Record<string, unknown>));
      continue;
    }
    const label = LABELS[key];
    if (!label || value === null || value === undefined || value === "") continue;
    const values = Array.isArray(value) ? value : [value];
    const texts = values.filter((entry): entry is string | number => typeof entry === "string" || typeof entry === "number")
      .map((entry) => typeof entry === "number" ? entry.toLocaleString("ko-KR") : VALUES[entry] ?? entry);
    if (texts.length) result.push(`${label}: ${texts.join(", ")}`);
  }
  return result;
}
export function formatChatTime(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
