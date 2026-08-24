/**
 * DB 코드값과 화면 라벨의 상호 변환.
 *
 * 주의: 여기 나열한 코드 문자열은 `docs/db/migrate/002_CREATE_PROPERTY_LEDGER.sql`의
 * DEFAULT 값에서 확인된 것을 제외하면 아직 백엔드와 합의되지 않았다.
 * `docs/db/README.md`도 "업무 상태값의 최종 목록과 상태 전이 규칙"을 미확정으로 둔다.
 *
 * 확정되면 이 파일의 표만 고치면 되고 다른 계층은 건드리지 않는다.
 * 확정 전까지는 매핑에 없는 코드가 와도 값을 잃지 않도록 원본 코드를 그대로 라벨로 노출한다.
 */

/** 양방향 코드 표. `codeToLabel`이 정본이고 역방향은 여기서 파생한다. */
export interface CodeTable<Code extends string> {
  readonly codeToLabel: Readonly<Record<Code, string>>;
  /** 백엔드와 아직 합의되지 않은 추측값이면 true. */
  readonly provisional: boolean;
}

function createTable<const Code extends string>(
  codeToLabel: Readonly<Record<Code, string>>,
  options: { provisional: boolean },
): CodeTable<Code> {
  return { codeToLabel, provisional: options.provisional };
}

/**
 * 코드를 라벨로 바꾼다. 표에 없는 코드는 값을 버리지 않고 원본을 그대로 돌려준다.
 * null/빈 문자열은 빈 문자열이 된다(그리드의 "(비어 있음)" 항목과 같은 의미).
 */
export function toLabel<Code extends string>(table: CodeTable<Code>, code: string | null | undefined): string {
  if (code == null || code === "") return "";
  const known = (table.codeToLabel as Record<string, string | undefined>)[code];
  return known ?? code;
}

/**
 * 라벨을 코드로 되돌린다. 표에 없는 라벨은 null을 반환한다.
 * 호출부가 "보낼 수 없는 값"을 조용히 넘기지 않고 명시적으로 처리하게 하려는 의도다.
 */
export function toCode<Code extends string>(table: CodeTable<Code>, label: string | null | undefined): Code | null {
  if (label == null || label === "") return null;
  for (const [code, mapped] of Object.entries(table.codeToLabel) as [Code, string][]) {
    if (mapped === label) return code;
  }
  // 라벨 자리에 이미 코드가 들어온 경우(미매핑 코드를 그대로 표시한 값의 왕복)를 허용한다.
  if (label in table.codeToLabel) return label as Code;
  return null;
}

/** 표에 실제로 존재하는 라벨 목록. 셀 편집기의 선택지로 쓴다. */
export function labelsOf<Code extends string>(table: CodeTable<Code>): string[] {
  return Object.values(table.codeToLabel) as string[];
}

/* ------------------------------------------------------------------ */
/* property_unit                                                       */
/* ------------------------------------------------------------------ */

/** property_unit.lifecycle_status — DDL DEFAULT 'NORMAL'만 확인됨. */
export const LIFECYCLE_STATUS = createTable(
  {
    NORMAL: "일반",
    LISTED: "매물화",
    IN_PROGRESS: "거래진행",
    CLOSED: "거래완료",
  },
  { provisional: true },
);

/** property_unit.tenancy_status */
export const TENANCY_STATUS = createTable(
  {
    VACANT: "공실",
    OWNER_OCCUPIED: "자가",
    JEONSE: "전세",
    MONTHLY_RENT: "월세",
  },
  { provisional: true },
);

/** property_unit.orientation */
export const ORIENTATION = createTable(
  {
    SOUTH: "남향",
    SOUTH_EAST: "남동향",
    SOUTH_WEST: "남서향",
    EAST: "동향",
    WEST: "서향",
    NORTH: "북향",
  },
  { provisional: true },
);

/* ------------------------------------------------------------------ */
/* property_listing                                                    */
/* ------------------------------------------------------------------ */

/** property_listing.status — DDL DEFAULT 'RECEIVED'만 확인됨. */
export const LISTING_STATUS = createTable(
  {
    RECEIVED: "접수",
    ACTIVE: "공개",
    ON_HOLD: "보류",
    CONTRACTED: "계약",
    CLOSED: "종료",
  },
  { provisional: true },
);

/* ------------------------------------------------------------------ */
/* property_requirement (구입장)                                        */
/* ------------------------------------------------------------------ */

/** property_requirement.demand_type — 구입장 「구분」 열. */
export const DEMAND_TYPE = createTable(
  {
    BUY: "매수",
    SELL: "매도",
    JEONSE: "전세",
    MONTHLY_RENT: "월세",
  },
  { provisional: true },
);

/**
 * property_requirement.status — 구입장 「완료여부」 열. DDL DEFAULT 'ACTIVE'만 확인됨.
 * F1-DM-13에 따라 「진행단계」(자유 입력)와는 별개 필드다.
 */
export const REQUIREMENT_STATUS = createTable(
  {
    ACTIVE: "진행",
    COMPLETED: "완료",
    CANCELLED: "취소",
  },
  { provisional: true },
);

/* ------------------------------------------------------------------ */
/* party / party_contact                                               */
/* ------------------------------------------------------------------ */

/**
 * property_unit_party_relation.role
 *
 * 서버가 실제로 쓰는 코드는 `LANDLORD`다. `client_interaction.counterparty_role`도 같다.
 * 임대차 관계를 가리키는 값이라 소유권을 뜻하는 `OWNER`와 구분한다.
 */
export const PARTY_ROLE = createTable(
  {
    LANDLORD: "임대인",
    TENANT: "임차인",
  },
  { provisional: false },
);

/**
 * party_contact.contactability_status — DDL DEFAULT 'UNKNOWN'만 확인됨.
 * F1-DM-16(동의 없이 저장 불가) 판정의 근거 필드이므로 확정 전까지 저장을 막는 쪽으로 해석한다.
 */
export const CONTACTABILITY = createTable(
  {
    CONSENTED: "동의",
    NEEDS_CHECK: "확인 필요",
    UNKNOWN: "미확인",
    RESTRICTED: "연락 제한",
  },
  { provisional: true },
);

/** 연락 가능 동의가 확인된 상태인지. 문자 발송 대상 판정과 저장 차단에 함께 쓴다. */
export function isContactConsented(code: string | null | undefined): boolean {
  return code === "CONSENTED";
}
