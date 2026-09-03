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

export { BRIEFING_HOUR } from "./model/briefing.ts";
export { BRIEFING_LIMIT, KNOWN_AGENDA_CATEGORIES } from "./model/dto.ts";
export type { AgendaCategory, AgendaItemDto, AgendaPageDto } from "./model/dto.ts";
