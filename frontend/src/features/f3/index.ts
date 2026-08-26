/**
 * F3 교차 판정 기능의 공개 진입점.
 *
 * 화면은 `CrossMatchSection` 하나만 놓으면 된다. 앵커 도출, 실행 확보, polling, 결과 조립과
 * 패널 표시는 전부 이 모듈 안에서 끝난다. DTO, decoder, HTTP 경로와 mock은 내부 구현이며
 * 어떤 transport를 쓰는지도 밖에서 보이지 않는다.
 *
 * 실제로 밖에서 쓰는 것만 내보낸다. 쓸 사람이 없는 이름을 미리 열어 두면 그것도 계약이 되어
 * 내부를 고칠 때마다 딸려 온다. 필요해지면 그때 넓힌다.
 */

export { CrossMatchSection } from "./CrossMatchSection.tsx";
export type { CrossMatchSectionProps, DetailRow } from "./CrossMatchSection.tsx";

/**
 * 세션이 끝날 때 확보한 실행 registry를 비운다.
 *
 * 사무소 공용 PC를 전제하므로 같은 브라우저에서 계정이 바뀔 수 있다. 실행 식별자는
 * 중개사무소 안에서만 유효하다.
 */
export { resetCrossJudgmentCache } from "./hooks/useCrossJudgment.ts";
