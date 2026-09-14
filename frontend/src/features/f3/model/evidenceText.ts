/** F3 내부 카드 필드의 화면 용어. 저장된 응답과 상담 인용 원문은 변경하지 않는다. */
const FIELD_LABELS: Readonly<Record<string, string>> = {
  intent: "거래 의향",
  "intent.value": "거래 의향",
  price: "가격",
  "price.SALE": "매매가",
  "price.JEONSE": "전세 보증금",
  "price.MONTHLY_RENT": "월세 가격",
  "price.BUDGET": "예산",
  "price.price_kind": "가격 구분",
  "price.stated_amount": "제시 금액",
  "price.stated_monthly_amount": "제시 월세",
  "price.estimated_amount": "추정 금액",
  "price.estimated_monthly_amount": "추정 월세",
  "price.basis": "가격 근거",
  urgency: "긴급도",
  "urgency.value": "긴급도",
  timing: "일정",
  "timing.hard_deadline": "확정 기한",
  "timing.constraints": "일정 조건",
  "timing.constraints.description": "일정 조건",
  flexible: "조율 가능한 조건",
  "flexible.description": "조율 가능한 조건",
  inflexible: "조율이 어려운 조건",
  "inflexible.description": "조율이 어려운 조건",
  contactability: "연락 가능 여부",
  "contactability.status": "연락 가능 상태",
  "contactability.note": "연락 관련 참고 사항",
  hard_deadline: "확정 기한",
  constraints: "일정 조건",
  price_kind: "가격 구분",
  stated_amount: "제시 금액",
  stated_monthly_amount: "제시 월세",
  estimated_amount: "추정 금액",
  estimated_monthly_amount: "추정 월세",
};

// 과거 결과의 analysis 접두사와 배열 경로도 같은 의미로 표시한다.
function normalizedField(field: string): string {
  return field.replace(/^analysis\./, "").replace(/\[\d+\]|\.\d+(?=\.|$)/g, "");
}

function knownLabel(field: string): string | undefined {
  const key = normalizedField(field);
  return Object.hasOwn(FIELD_LABELS, key) ? FIELD_LABELS[key] : undefined;
}

export function evidenceFieldLabel(field: string | null): string | null {
  if (field == null || field.trim() === "") return null;
  const trimmed = field.trim();
  const label = knownLabel(trimmed);
  if (label != null) return label;
  // 새 내부 키의 뜻을 추측하지 않는다. 이미 한국어인 항목명은 그대로 표시한다.
  return /[a-z]/i.test(trimmed) ? "판정 근거" : trimmed;
}

const fieldPatterns = Object.keys(FIELD_LABELS)
  .sort((a, b) => b.length - a.length)
  .map((field) => field.split(".").join("(?:\\[\\d+\\]|\\.\\d+)?\\."));
const INTERNAL_FIELD = new RegExp(
  // 한글 조사는 허용하되 다른 식별자·경로의 일부를 번역하지 않는다.
  `(?<![a-zA-Z0-9_.\\[\\]])(?:analysis\\.)?(?:${fieldPatterns.join("|")})(?:\\[\\d+\\]|\\.\\d+)?(?![a-zA-Z0-9_\\[\\]]|\\.[a-zA-Z0-9_])`,
  "g",
);

/** 생성된 설명에서 알려진 내부 식별자만 치환한다. 금액·날짜·일반 영문은 보존한다. */
export function judgmentText(text: string | null): string | null {
  if (text == null) return null;
  return text.replace(INTERNAL_FIELD, (field) => knownLabel(field) ?? field);
}
