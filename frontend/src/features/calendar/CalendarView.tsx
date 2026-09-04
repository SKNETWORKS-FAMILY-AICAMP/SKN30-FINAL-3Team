/**
 * 캘린더 버튼과 월간 그리드 창.
 *
 * Time Keeper의 "다가오는 일정"과 나란히 상단바에 붙는, 별개 진입점이다. 두 화면은 같은 조회
 * 규칙(F4-TK-07 앞뒤 창)과 같은 표시 문구를 공유하지만, Time Keeper 쪽 배지·아침 브리핑
 * 동작(F4-TK-08~21)은 건드리지 않는다.
 *
 * 읽기 전용 장부 일정은 `useAgenda`로 그대로 가져오되 캘린더 갈래(`event_id != null`)는 뺀다 —
 * 이 화면이 자기 일정을 이미 `useCalendarEvents`로 직접, 더 자세히 가져오기 때문에 겹쳐 그리면
 * 같은 일정이 두 번 보인다.
 */

import { useMemo, useState } from "react";
import { Button, Modal, ModalBody, ModalHeader } from "@patternfly/react-core";
import { CalendarAltIcon, AngleLeftIcon, AngleRightIcon } from "@patternfly/react-icons";
import { useAgenda } from "../timeKeeper/index.ts";
import type { AgendaItemDto } from "../timeKeeper/index.ts";
import { CalendarEventModal } from "./CalendarEventModal.tsx";
import { useCalendarEvents } from "./hooks/useCalendarEvents.ts";
import { buildDayCells, eventChipLabel, ledgerChipLabel } from "./model/viewModel.ts";
import type { CalendarEventDto } from "./model/dto.ts";
import {
  addMonths,
  monthGridDays,
  monthLabel,
  monthQueryRange,
  startOfMonth,
  toIsoDate,
  weekdayLabels,
} from "./model/monthGrid.ts";
import "./Calendar.css";

const MAX_WITHIN_DAYS = 730;
const MAX_OVERDUE_DAYS = 365;

/** 보이는 달을 덮을 만큼만 조회 창을 넓힌다. 서버 상한을 넘지 않게 자른다. */
function ledgerWindowFor(range: { from: string; to: string }): {
  withinDays: number;
  overdueDays: number;
} {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const from = new Date(`${range.from}T00:00:00`);
  const to = new Date(`${range.to}T00:00:00`);
  const overdueDays = Math.min(
    MAX_OVERDUE_DAYS,
    Math.max(0, Math.ceil((today.getTime() - from.getTime()) / 86_400_000)),
  );
  const withinDays = Math.min(
    MAX_WITHIN_DAYS,
    Math.max(1, Math.ceil((to.getTime() - today.getTime()) / 86_400_000)),
  );
  return { withinDays, overdueDays };
}

function excludeCalendarSourced(items: readonly AgendaItemDto[]): AgendaItemDto[] {
  return items.filter((item) => item.event_id == null);
}

export function CalendarView() {
  const [isOpen, setOpen] = useState(false);
  const [monthStart, setMonthStart] = useState(() => startOfMonth(new Date()));
  const [modalTarget, setModalTarget] = useState<
    { kind: "create"; date: string } | { kind: "edit"; event: CalendarEventDto } | null
  >(null);

  const days = useMemo(() => monthGridDays(monthStart), [monthStart]);
  const range = useMemo(() => monthQueryRange(monthStart), [monthStart]);
  const ledgerWindow = useMemo(() => ledgerWindowFor(range), [range]);
  const today = useMemo(() => toIsoDate(new Date()), []);

  const calendarEvents = useCalendarEvents(range, { enabled: isOpen });
  const agenda = useAgenda(
    { ...ledgerWindow, perCategoryLimit: 100, limit: 500, offset: 0 },
    { enabled: isOpen },
  );

  const cells = useMemo(
    () => buildDayCells(days, calendarEvents.events, excludeCalendarSourced(agenda.items)),
    [days, calendarEvents.events, agenda.items],
  );

  const openCalendar = () => setOpen(true);
  const closeModal = () => setModalTarget(null);

  return (
    <>
      <Button
        variant="plain"
        aria-label="캘린더를 엽니다"
        aria-haspopup="dialog"
        onClick={openCalendar}
        icon={<CalendarAltIcon />}
      />

      <Modal variant="large" isOpen={isOpen} onClose={() => setOpen(false)} aria-label="캘린더">
        <ModalHeader
          title="캘린더"
          description="Time Keeper가 읽는 장부 일정과 직접 추가한 일정을 함께 봅니다."
        />
        <ModalBody>
          <div className="calendar" data-screen-id="F4-MOD-011" data-requirement-ids="F4-CAL-01~05">
            <div className="calendar__toolbar">
              <Button
                variant="plain"
                aria-label="이전 달"
                icon={<AngleLeftIcon />}
                onClick={() => setMonthStart((current) => addMonths(current, -1))}
              />
              <span className="calendar__month-label">{monthLabel(monthStart)}</span>
              <Button
                variant="plain"
                aria-label="다음 달"
                icon={<AngleRightIcon />}
                onClick={() => setMonthStart((current) => addMonths(current, 1))}
              />
              <Button variant="secondary" size="sm" onClick={() => setMonthStart(startOfMonth(new Date()))}>
                오늘
              </Button>
            </div>

            {(calendarEvents.status === "error" || agenda.status === "error") && (
              <p className="calendar__state calendar__state--error" role="status">
                일정을 불러오지 못했습니다.{" "}
                <button
                  type="button"
                  className="calendar__retry"
                  onClick={() => {
                    calendarEvents.reload();
                    agenda.reload();
                  }}
                >
                  다시 시도
                </button>
              </p>
            )}

            <div className="calendar__weekdays">
              {weekdayLabels().map((label) => (
                <span key={label} className="calendar__weekday">
                  {label}
                </span>
              ))}
            </div>

            <div className="calendar__grid">
              {cells.map((cell) => {
                const inCurrentMonth =
                  new Date(`${cell.date}T00:00:00`).getMonth() === monthStart.getMonth();
                return (
                  <div
                    key={cell.date}
                    className={
                      "calendar__cell" +
                      (inCurrentMonth ? "" : " calendar__cell--outside") +
                      (cell.date === today ? " calendar__cell--today" : "")
                    }
                  >
                    <div className="calendar__cell-header">
                      <span className="calendar__cell-date">
                        {Number(cell.date.slice(-2))}
                      </span>
                      <button
                        type="button"
                        className="calendar__add"
                        aria-label={`${cell.date} 일정 추가`}
                        onClick={() => setModalTarget({ kind: "create", date: cell.date })}
                      >
                        +
                      </button>
                    </div>
                    <ul className="calendar__items">
                      {cell.ledgerItems.map((item) => (
                        <li
                          key={`ledger-${item.category}-${item.unit_id}-${item.listing_id}-${item.requirement_id}`}
                          className="calendar__item calendar__item--ledger"
                          title={ledgerChipLabel(item)}
                        >
                          {ledgerChipLabel(item)}
                        </li>
                      ))}
                      {cell.events.map((event) => (
                        <li key={event.id} className="calendar__item calendar__item--event">
                          <button
                            type="button"
                            className="calendar__item-button"
                            title={eventChipLabel(event)}
                            onClick={() => setModalTarget({ kind: "edit", event })}
                          >
                            {eventChipLabel(event)}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          </div>
        </ModalBody>
      </Modal>

      <CalendarEventModal
        isOpen={modalTarget != null}
        fallbackDate={modalTarget?.kind === "create" ? modalTarget.date : today}
        event={modalTarget?.kind === "edit" ? modalTarget.event : null}
        onClose={closeModal}
        onCreate={calendarEvents.createEvent}
        onUpdate={calendarEvents.updateEvent}
        onDelete={calendarEvents.deleteEvent}
      />
    </>
  );
}
