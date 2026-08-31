/**
 * 음성 메모를 상담 로그에 쌓는 규칙.
 *
 * 상담 로그는 덮어쓰지 않고 이어 붙는다(F1-LG-01). 나중에 읽을 때 어느 대목이 언제 들어온
 * 음성 메모인지 구분할 수 있도록 반영 시점의 날짜와 시각을 메모 앞에 붙인다(F1-LG-02).
 *
 * 표기는 요구사항 정본의 로그 포맷 `[YY-MM-DD HH:MM 주②]본문`을 따르되 상대 역할·인물 인덱스는
 * 붙이지 않는다. 음성 메모는 어느 인물과의 상담인지 정하지 않으므로 마커를 붙이면 사람을 단정하게
 * 된다. 인덱스가 없는 로그는 미지정으로 두는 것이 정본의 규칙이다(F1-LG-33).
 *
 * 시각은 사용자가 체감하는 로컬 시간을 쓴다. 이 값은 서버로 보내는 타임스탬프가 아니라
 * 사람이 읽는 로그 본문이라 API 계약의 ISO 8601 표기를 따르지 않는다.
 */

/** 로그 본문에 남기는 시각 표기. 예: `26-08-27 14:32` */
export function formatLogStamp(at: Date = new Date()): string {
  const year = String(at.getFullYear()).slice(-2);
  const month = String(at.getMonth() + 1).padStart(2, "0");
  const day = String(at.getDate()).padStart(2, "0");
  const hours = String(at.getHours()).padStart(2, "0");
  const minutes = String(at.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

/** 음성 메모 한 건에 시각을 붙인다. 빈 메모에는 시각만 남기지 않는다. */
export function stampVoiceMemo(memo: string, at: Date = new Date()): string {
  const text = String(memo ?? "").trim();
  if (text === "") return "";
  return `[${formatLogStamp(at)}]${text}`;
}

/**
 * 기존 상담 로그 뒤에 음성 메모를 이어 붙인다.
 *
 * 앞 기록의 끝에 빈 줄이 있어도 줄이 계속 늘어나지 않도록 꼬리 공백은 정리하고,
 * 기존 기록이 없으면 앞에 빈 줄을 만들지 않는다.
 */
export function appendVoiceMemoToLog(current: string | null | undefined, memo: string, at: Date = new Date()): string {
  const entry = stampVoiceMemo(memo, at);
  const previous = String(current ?? "").replace(/\s+$/, "");
  if (entry === "") return previous;
  return previous === "" ? entry : `${previous}\n${entry}`;
}
