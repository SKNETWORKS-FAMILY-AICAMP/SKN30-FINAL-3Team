/**
 * 동작 감소 설정을 존중하는 스크롤 이동.
 *
 * `styles.css`가 `prefers-reduced-motion`에서 `scroll-behavior: auto`를 강제하지만 그 선언은
 * CSS 경로에만 적용된다. `scrollIntoView({ behavior: "smooth" })`처럼 JS가 옵션으로 직접
 * 지정한 값은 CSS를 이기므로, 동작 감소를 켠 사용자에게도 스크롤 애니메이션이 그대로 남는다.
 * 그래서 호출 시점에 설정을 읽어 동작을 정한다.
 */

/** 동작 감소를 켰는지. matchMedia가 없는 환경(구형 jsdom 등)은 끈 것으로 본다. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * 대상을 화면 안으로 옮긴다.
 *
 * 동작 감소를 켜면 애니메이션 없이 즉시 이동한다. 이동 자체를 생략하지는 않는다.
 * 초점이 화면 밖으로 나가면 동작 감소 여부와 무관하게 사용자가 위치를 잃는다.
 */
export function scrollIntoViewRespectingMotion(
  target: Element | null | undefined,
  options: Omit<ScrollIntoViewOptions, "behavior"> = {},
): void {
  target?.scrollIntoView({
    ...options,
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
}
