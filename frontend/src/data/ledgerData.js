export const initialComplexes = ["래미안 원베일리", "아크로리버파크", "반포자이", "래미안 퍼스티지"];
const complexes = initialComplexes;
const owners = ["박이서", "이정민", "윤서준", "최유진", "한도윤", "서예린", "장현우", "문소율"];
const assignees = ["김이순", "실장", "박소장"];
const directions = ["남향", "남동향", "남서향", "동향"];
const listingTypes = ["", "매매", "전세", "월세"];
// 장부 목록에서 노출하는 저장 상태는 F2 처리 상태와 독립적인 두 값만 사용한다.
const saveStates = ["저장 완료", "저장 완료", "저장 완료", "임시저장", "임시저장"];
const aiStates = ["대기", "대기", "분석 완료", "분석 실패"];

const seedRows = [
  {
    id: "H-0001",
    complex: "래미안 원베일리",
    building: "101",
    unit: "203",
    saveState: "저장 완료",
    aiState: "대기",
    householdState: "일반",
    area: "33평",
    listingType: "매매",
    price: "28.8억",
    deposit: "",
    rent: "",
    expiry: "2027-07-26",
    owner: "박이서·송경련",
    tenant: "김우진",
    phone: "010-4278-7118",
    direction: "남향",
    floor: "2/35",
    rooms: 3,
    baths: 2,
    lastContact: "2026-08-11",
    log: "매도 조건 재확인, 명도는 협의 가능",
    assignee: "김이순",
    source: "전화",
    consent: "동의",
    memo: "주차 2대 가능",
  },
  {
    id: "H-0002",
    complex: "래미안 원베일리",
    building: "101",
    unit: "204",
    saveState: "임시저장",
    aiState: "분석 완료",
    householdState: "매물화",
    area: "33평",
    listingType: "전세",
    price: "15억",
    expiry: "2026-11-30",
    owner: "이정민",
    tenant: "",
    phone: "010-7509-3171",
    direction: "남동향",
    floor: "2/35",
    rooms: 3,
    baths: 2,
    lastContact: "2026-08-10",
    log: "금액 확인 필요 · 분석 제안 검토 대기",
    assignee: "실장",
    source: "음성메모",
    consent: "확인 필요",
    memo: "",
  },
  {
    id: "H-0003",
    complex: "래미안 원베일리",
    building: "101",
    unit: "205",
    saveState: "임시저장",
    aiState: "대기",
    householdState: "일반",
    area: "33평",
    listingType: "",
    price: "",
    expiry: "",
    owner: "",
    tenant: "",
    phone: "",
    direction: "남향",
    floor: "2/35",
    rooms: 3,
    baths: 2,
    lastContact: "",
    log: "미완성 데이터 보존 · 이어서 작성",
    assignee: "김이순",
    source: "직접 입력",
    consent: "미확인",
    memo: "",
  },
  {
    id: "H-0004",
    complex: "래미안 원베일리",
    building: "101",
    unit: "206",
    saveState: "저장 완료",
    aiState: "분석 실패",
    householdState: "거래진행",
    area: "33평",
    listingType: "월세",
    price: "9억/380만",
    expiry: "2026-09-15",
    owner: "최유진",
    tenant: "박하늘",
    phone: "010-9182-3014",
    direction: "남서향",
    floor: "2/35",
    rooms: 3,
    baths: 2,
    lastContact: "2026-08-09",
    log: "음성 분석 실패 · F1 저장은 정상 완료",
    assignee: "실장",
    source: "음성메모",
    consent: "동의",
    memo: "반려동물 협의",
  },
];

function buildGeneratedRow(index) {
  const ordinal = index + 1;
  const complex = complexes[index % complexes.length];
  const building = String(101 + (Math.floor(index / 84) % 8));
  const unit = String(201 + (index % 84));
  const listingType = listingTypes[index % listingTypes.length];
  return {
    id: `H-${String(ordinal).padStart(4, "0")}`,
    complex,
    building,
    unit,
    saveState: saveStates[index % saveStates.length],
    aiState: aiStates[index % aiStates.length],
    householdState: index % 9 === 0 ? "매물화" : "일반",
    area: `${[24, 33, 42, 50][index % 4]}평`,
    listingType,
    price: listingType === "" ? "" : listingType === "매매" ? `${24 + (index % 9)}.${index % 10}억` : listingType === "전세" ? `${12 + (index % 8)}억` : `${5 + (index % 5)}억/${240 + (index % 8) * 20}만`,
    deposit: listingType === "월세" ? `${5 + (index % 5)}억` : "",
    rent: listingType === "월세" ? `${240 + (index % 8) * 20}만` : "",
    expiry: index % 5 === 0 ? "" : `202${6 + (index % 2)}-${String((index % 12) + 1).padStart(2, "0")}-${String((index % 27) + 1).padStart(2, "0")}`,
    owner: index % 11 === 0 ? "" : owners[index % owners.length],
    tenant: index % 3 === 0 ? owners[(index + 3) % owners.length] : "",
    phone: index % 11 === 0 ? "" : `010-${String(1000 + (index * 37) % 9000)}-${String(1000 + (index * 71) % 9000)}`,
    direction: directions[index % directions.length],
    floor: `${2 + (index % 30)}/35`,
    rooms: 3 + (index % 2),
    baths: 2,
    lastContact: index % 7 === 0 ? "" : `2026-08-${String((index % 12) + 1).padStart(2, "0")}`,
    log: index % 4 === 0 ? "매물 의사 없음 · 6개월 후 재확인" : "상담 조건을 확인하고 후속 연락 예정",
    assignee: assignees[index % assignees.length],
    source: index % 5 === 0 ? "음성메모" : "전화",
    consent: index % 8 === 0 ? "확인 필요" : "동의",
    memo: index % 6 === 0 ? "일정 협의 필요" : "",
    createdAt: `2026-07-${String((index % 27) + 1).padStart(2, "0")}`,
    updatedAt: `2026-08-${String((index % 12) + 1).padStart(2, "0")}`,
    createdBy: assignees[(index + 1) % assignees.length],
    updatedBy: assignees[index % assignees.length],
    parking: `${1 + (index % 2)}대`,
    moveIn: index % 3 === 0 ? "즉시" : "협의",
    tax: index % 4 === 0 ? "확인 필요" : "일반",
  };
}

/**
 * 13.1 매물장 33개 컬럼에 맞춘 표시용 필드를 보완한다.
 * 기존 상세 화면이 사용하는 필드명은 호환을 위해 그대로 보존한다.
 */
function withPropertyColumns(row) {
  const listingType = row.listingType || "";
  return {
    ...row,
    type: row.type || "J1",
    loan: row.loan || "",
    receivedAt: row.receivedAt || row.createdAt || "",
    clearance: row.clearance || row.moveIn || "",
    saleFlag: row.saleFlag || (listingType === "매매" ? "Y" : ""),
    leaseFlag: row.leaseFlag || (listingType === "전세" ? "Y" : ""),
    monthlyFlag: row.monthlyFlag || (listingType === "월세" ? "Y" : ""),
    salePrice: row.salePrice || (listingType === "매매" ? row.price || "" : ""),
    leaseDeposit: row.leaseDeposit || (listingType === "전세" ? row.price || "" : ""),
    rentCondition: row.rentCondition || (listingType === "월세" ? [row.deposit, row.rent].filter(Boolean).join(" / ") : ""),
    spec: row.spec || [row.rooms && `${row.rooms}실`, row.baths && `${row.baths}욕실`].filter(Boolean).join(" "),
    builtIn: row.builtIn || "",
    facilityState: row.facilityState || row.tax || "",
    ownerPhone: row.ownerPhone || row.phone || "",
    brokerage: row.brokerage || "",
    tenantPhone: row.tenantPhone || "",
    user1: row.user1 || "",
  };
}

export function createLedgerRows(count) {
  if (!Number.isInteger(count) || count < 0) {
    throw new TypeError("createLedgerRows에는 0 이상의 행 수를 명시적으로 전달해야 합니다.");
  }
  const generated = Array.from({ length: Math.max(0, count - seedRows.length) }, (_, index) =>
    buildGeneratedRow(index + seedRows.length),
  );
  return [...seedRows, ...generated].map(withPropertyColumns);
}

export const emptyDraftRow = {
  id: "DRAFT-NEW",
  complex: "",
  building: "",
  unit: "",
  saveState: "임시저장",
  aiState: "대기",
  householdState: "일반",
  area: "",
  listingType: "",
  price: "",
  owner: "",
  tenant: "",
  phone: "",
  log: "",
  assignee: "김이순",
  consent: "미확인",
  type: "",
  loan: "",
  receivedAt: "",
  clearance: "",
  saleFlag: "",
  leaseFlag: "",
  monthlyFlag: "",
  salePrice: "",
  leaseDeposit: "",
  rentCondition: "",
  spec: "",
  builtIn: "",
  facilityState: "",
  ownerPhone: "",
  brokerage: "",
  tenantPhone: "",
  user1: "",
};

const buyerSeedRows = [
  {
    id: "B-0001", date: "2026-08-12", area: "33평", category: "매수", budget: "28억선",
    complex: "래미안 원베일리", buyer: "인천사모님", phone: "010-3312-8871", brokerage: "대송",
    moveDate: "2026-10-01", content: "남향, 10월 입주 희망", stage: "매물 탐색", completion: "진행",
    assignee: "김이순", background: "", expiry: "2028-01-31", classification: "실거주", memo: "",
  },
  {
    id: "B-0002", date: "2026-07-30", area: "25 33평", category: "전세", budget: "12억 이하",
    complex: "아크로리버파크", buyer: "414동 세입자", phone: "010-5521-3409", brokerage: "",
    moveDate: "2026-09-15", content: "입주일 조정 가능", stage: "조건 확인", completion: "진행",
    assignee: "실장", background: "", expiry: "2026-09-30", classification: "전세", memo: "만기 임박",
  },
];

function buildBuyerRow(index) {
  const ordinal = index + 1;
  const category = ["매수", "전세", "월세", "매도"][index % 4];
  return {
    id: `B-${String(ordinal).padStart(4, "0")}`,
    date: `2026-08-${String((index % 12) + 1).padStart(2, "0")}`,
    area: ["25평", "33평", "25 33평"][index % 3],
    category,
    budget: category === "매수" ? `${24 + (index % 8)}억선` : category === "전세" ? `${10 + (index % 5)}억 이하` : "협의",
    complex: complexes[index % complexes.length],
    buyer: ["인천사모님", "414동 세입자", "30억이하 엄마", "김손님"][index % 4],
    phone: `010-${String(2000 + (index * 31) % 7000)}-${String(1200 + (index * 53) % 7000)}`,
    brokerage: index % 3 === 0 ? "대송" : "",
    moveDate: `2026-${String((index % 6) + 8).padStart(2, "0")}-15`,
    content: index % 2 ? "가격 협의 가능" : "입주 시점 우선",
    stage: ["매물 탐색", "조건 확인", "방문 일정"][index % 3],
    completion: index % 5 === 0 ? "완료" : "진행",
    assignee: assignees[index % assignees.length],
    background: "",
    expiry: index % 4 === 0 ? `2026-${String((index % 8) + 8).padStart(2, "0")}-30` : "",
    classification: category,
    memo: index % 6 === 0 ? "후속 연락 필요" : "",
  };
}

export function createBuyerRows(count = 12) {
  if (!Number.isInteger(count) || count < 0) {
    throw new TypeError("createBuyerRows에는 0 이상의 행 수를 명시적으로 전달해야 합니다.");
  }
  const generated = Array.from({ length: Math.max(0, count - buyerSeedRows.length) }, (_, index) => buildBuyerRow(index + buyerSeedRows.length));
  return [...buyerSeedRows, ...generated];
}

export const emptyBuyerRow = {
  id: "BUYER-DRAFT-NEW", date: "", area: "", category: "매수", budget: "", complex: "", buyer: "", phone: "",
  brokerage: "", moveDate: "", content: "", stage: "", completion: "진행", assignee: "김이순", background: "",
  expiry: "", classification: "", memo: "", saveState: "임시저장", consent: "미확인",
};

export const candidateMatches = [
  {
    id: "C-01",
    grade: "강함",
    rank: 1,
    title: "김정우 · 실거주 매수",
    summary: "예산과 입주 시점이 모두 일치",
    phone: "010-4102-6651",
    budget: "27~30억",
    timing: "2026년 10월",
    blocker: "남향 선호가 강해 방향 확인 필요",
    concession: "매도자 0.3억 조정 시 즉시 방문 가능",
    evidence: "8/11 상담: 33평, 30억 이하, 10월 입주 희망",
  },
  {
    id: "C-02",
    grade: "강함",
    rank: 2,
    title: "서하윤 · 갈아타기",
    summary: "단지와 평형 선호가 정확히 일치",
    phone: "010-8820-1934",
    budget: "28억 전후",
    timing: "협의",
    blocker: "기존 주택 처분 일정 미확정",
    concession: "계약일을 3주 유예하면 검토 가능",
    evidence: "8/09 상담: 원베일리 33평만 검토, 남향 우선",
  },
  {
    id: "C-03",
    grade: "약함",
    rank: 3,
    title: "이도현 · 투자",
    summary: "가격은 맞지만 입주 조건이 다름",
    phone: "010-7341-5520",
    budget: "29억 이하",
    timing: "임대 승계 선호",
    blocker: "실입주 조건과 임대 승계 선호가 충돌",
    concession: "잔금 전 임차인 확보 시 관심도 상승",
    evidence: "8/02 상담: 공실보다 임대 승계 물건 우선",
  },
  {
    id: "C-04",
    grade: "기각",
    rank: 4,
    title: "박민서 · 실거주",
    summary: "최대 예산을 2억 초과",
    phone: "010-6204-8481",
    budget: "25~27억",
    timing: "즉시",
    blocker: "현재 희망가가 최대 예산을 초과",
    concession: "희망가가 27억 이하로 내려가면 재검토",
    evidence: "8/06 상담: 대출 포함 최대 27억",
  },
];
