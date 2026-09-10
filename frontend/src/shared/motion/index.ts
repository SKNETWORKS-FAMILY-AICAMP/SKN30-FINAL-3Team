/**
 * 동작 감소 설정을 다루는 공개 진입점.
 *
 * 화면은 `scrollIntoViewRespectingMotion` 하나만 쓰면 된다. 설정을 읽는 방법이 바뀌어도
 * 호출부는 그대로 둔다.
 */

export { prefersReducedMotion, scrollIntoViewRespectingMotion } from "./scroll.ts";
