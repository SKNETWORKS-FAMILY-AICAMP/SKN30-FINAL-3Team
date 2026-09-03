/**
 * 알림 버튼과 아침 일정 브리핑 창.
 *
 * 두 진입이 같은 조회를 공유한다. 매일 아침 한 번 저절로 열리고, 그 뒤로는 상단바의 알림
 * 버튼으로 다시 연다. 「만기도래일 보기」가 현업에서 쓰이지 않은 이유가 사용자가 찾아 열어야만
 * 보이기 때문이므로 (F1 10.4), 찾아오게 만드는 쪽을 기본으로 둔다.
 *
 * 창을 열 때마다 다시 읽는다. 기준일이 하루 넘어가면 D-day가 통째로 하루씩 틀리는데, 사무소
 * PC는 화면을 켜 둔 채로 날짜를 넘기는 일이 흔하다.
 */

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Modal, ModalBody, ModalFooter, ModalHeader } from "@patternfly/react-core";
import { BellIcon } from "@patternfly/react-icons";
import { AgendaList } from "./AgendaList.tsx";
import { useAgenda } from "./hooks/useAgenda.ts";
import { useDailyBriefing } from "./hooks/useDailyBriefing.ts";
import { BRIEFING_HOUR } from "./model/briefing.ts";
import { BRIEFING_LIMIT } from "./model/dto.ts";
import "./TimeKeeper.css";

export interface TimeKeeperNotificationProps {
  /** 조회를 시작해도 되는 시점. 장부 조회와 같은 조건을 쓴다. */
  enabled?: boolean;
}

/** 배지에 적는 건수. 세 자리부터는 숫자 자체보다 "많다"가 정보다. */
function badgeLabel(total: number): string {
  return total > 99 ? "99+" : String(total);
}

export function TimeKeeperNotification({ enabled = true }: TimeKeeperNotificationProps) {
  const [isOpen, setOpen] = useState(false);
  /**
   * 브리핑이 재조회를 기다리는 중임을 나타낸다. 값은 요청 시점의 `loadCount`이며, 그보다 큰
   * 결과가 도착해야 연다. `status`만 보면 재조회 직후에도 직전 결과가 `ready`라 낡은 기준일로
   * 열린다.
   */
  const [briefingAfterLoad, setBriefingAfterLoad] = useState<number | null>(null);

  const agenda = useAgenda({ limit: BRIEFING_LIMIT }, { enabled });
  const { status, total, loadCount, reload, withinDays } = agenda;

  useDailyBriefing({
    enabled,
    onDue: useCallback(() => {
      setBriefingAfterLoad(loadCount);
      reload();
    }, [loadCount, reload]),
  });

  useEffect(() => {
    if (briefingAfterLoad == null) return;
    if (status !== "ready" || loadCount <= briefingAfterLoad) return;
    setBriefingAfterLoad(null);
    // 알릴 것이 없는 날까지 창을 띄우면 다음 날부터 아무도 읽지 않는다. 하루 한 번이라는
    // 기록은 이미 남았으므로 오늘 다시 뜨지는 않는다.
    if (total > 0) setOpen(true);
  }, [briefingAfterLoad, status, loadCount, total]);

  const openFromBell = useCallback(() => {
    reload();
    setOpen(true);
  }, [reload]);

  const hasCount = status === "ready" && total > 0;

  return (
    <>
      <Button
        variant="plain"
        aria-label={hasCount ? `알림. 예정된 일정 ${total}건` : "알림. 예정된 일정을 엽니다"}
        aria-haspopup="dialog"
        onClick={openFromBell}
        icon={
          <span className="time-keeper__bell">
            <BellIcon />
            {hasCount && (
              <Badge className="time-keeper__badge" isRead={false}>
                {badgeLabel(total)}
              </Badge>
            )}
          </span>
        }
      />

      <Modal
        variant="medium"
        isOpen={isOpen}
        onClose={() => setOpen(false)}
        aria-label="예정된 일정과 할 일"
      >
        <ModalHeader
          title="다가오는 일정"
          description={
            withinDays == null
              ? `기한이 다가온 일정과 할 일입니다. 매일 오전 ${BRIEFING_HOUR}시 이후 첫 접속에 한 번 열립니다.`
              : `${withinDays}일 이내에 기한이 오는 일정과 할 일입니다. 매일 오전 ${BRIEFING_HOUR}시 이후 첫 접속에 한 번 열립니다.`
          }
        />
        <ModalBody>
          <div
            className="time-keeper"
            data-screen-id="F1-MOD-160"
            data-requirement-ids="F1-AL-01, F1-AL-03, F1-AL-04"
          >
            <AgendaList agenda={agenda} />
            {agenda.asOf != null && <p className="time-keeper__asof">기준일 {agenda.asOf}</p>}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={() => setOpen(false)}>
            확인
          </Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
