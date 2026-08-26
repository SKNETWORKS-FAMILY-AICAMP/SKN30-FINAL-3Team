/**
 * 표시 형식의 공개 진입점.
 *
 * 억·만 금액과 평형 표기는 어느 화면에서나 같아야 한다. 같은 값이 매물장과 F3 패널에서 다르게
 * 보이면 사용자는 둘 중 무엇이 맞는지 알 수 없다. 규칙을 한 곳에 두고 재사용한다.
 *
 * 이 모듈은 순수하다. 브라우저 API도 설정도 읽지 않으므로 어디서든 가볍게 가져다 쓸 수 있다.
 */

export { formatMoney, formatMoneyPair, parseMoney, parseMoneyPair } from "./money.ts";
export {
  formatPyeong,
  formatPyeongList,
  parsePyeong,
  parsePyeongList,
} from "./area.ts";
