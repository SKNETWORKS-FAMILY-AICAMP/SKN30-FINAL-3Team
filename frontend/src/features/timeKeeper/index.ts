/**
 * Time Keeper의 공개 진입점.
 *
 * 바깥에서는 이 배럴이 내보내는 것만 쓴다. transport 구현과 decode는 기능 안에 둔다.
 * 상단바는 `TimeKeeperNotification` 하나만 걸면 알림 버튼과 브리핑 창이 함께 붙는다.
 */

export { TimeKeeperNotification } from "./TimeKeeperNotification.tsx";
export type { TimeKeeperNotificationProps } from "./TimeKeeperNotification.tsx";

export { AgendaList } from "./AgendaList.tsx";

export { useAgenda } from "./hooks/useAgenda.ts";
export type { AgendaState } from "./hooks/useAgenda.ts";
export type { AgendaQuery } from "./api/transport.ts";

export { useDismissedNeglected } from "./hooks/useDismissedNeglected.ts";
export type { DismissedNeglectedControl } from "./hooks/useDismissedNeglected.ts";

export { BRIEFING_HOUR } from "./model/briefing.ts";
export { BRIEFING_LIMIT, KNOWN_AGENDA_CATEGORIES } from "./model/dto.ts";
export type { AgendaCategory, AgendaItemDto, AgendaPageDto } from "./model/dto.ts";

// 캘린더 화면이 "다가오는 일정"과 같은 조회·표시 규칙을 쓸 수 있도록 뷰모델 도우미도 내보낸다.
// 두 화면이 같은 데이터를 다른 문구로 부르지 않게 한다.
export {
  agendaCategoryLabel,
  agendaItemKey,
  agendaTargetLabel,
  dDayLabel,
  isUrgent,
} from "./model/viewModel.ts";
