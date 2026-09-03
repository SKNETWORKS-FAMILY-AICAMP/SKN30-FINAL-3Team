/**
 * 일정 버튼과 아침 브리핑 창.
 *
 * 두 진입이 같은 조회를 공유한다. 매일 아침 한 번 저절로 열리고, 그 뒤로는 상단바의 달력
 * 버튼으로 다시 연다. 「만기도래일 보기」가 현업에서 쓰이지 않은 이유가 사용자가 찾아 열어야만
 * 보이기 때문이므로 (F1 10.4), 찾아오게 만드는 쪽을 기본으로 둔다.
 *
 * 옆의 종 아이콘은 F1 알림 센터(F1-AL-04)의 자리이고 이 버튼과 소유가 다르다. 아이콘을 나눠
 * 두면 "일정을 보러 가는 곳"과 "알림을 보러 가는 곳"이 화면에서 구분된다.
 *
 * 창을 열 때마다 다시 읽는다. 기준일이 하루 넘어가면 D-day가 통째로 하루씩 틀리는데, 사무소
 * PC는 화면을 켜 둔 채로 날짜를 넘기는 일이 흔하다.
 */

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Modal, ModalBody, ModalFooter, ModalHeader } from "@patternfly/react-core";
import { OutlinedCalendarAltIcon } from "@patternfly/react-icons";
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

interface BriefingAttempt {
  businessDateKey: string;
  afterSettlement: number;
}

/** 배지에 적는 건수. 세 자리부터는 숫자 자체보다 "많다"가 정보다. */
function badgeLabel(total: number): string {
  return total > 99 ? "99+" : String(total);
}

export function TimeKeeperNotification({ enabled = true }: TimeKeeperNotificationProps) {
  const [isOpen, setOpen] = useState(false);
  /**
   * 브리핑이 재조회를 기다리는 중임을 나타낸다. 요청 시점보다 큰 `settlementCount`가 되어야
   * 성공 또는 실패를 확정한다. `status`만 보면 재조회 직후에도 직전 결과가 `ready`라 낡은
   * 기준일로 브리핑을 열 수 있다.
   */
  const [briefingAttempt, setBriefingAttempt] = useState<BriefingAttempt | null>(null);

  const agenda = useAgenda({ limit: BRIEFING_LIMIT }, { enabled });
  const { status, total, settlementCount, reload, withinDays } = agenda;

  const { complete: completeBriefing, fail: failBriefing } = useDailyBriefing({
    enabled,
    onDue: useCallback((businessDateKey: string) => {
      setBriefingAttempt({ businessDateKey, afterSettlement: settlementCount });
      reload();
    }, [settlementCount, reload]),
  });

  useEffect(() => {
    if (briefingAttempt == null || settlementCount <= briefingAttempt.afterSettlement) return;

    setBriefingAttempt(null);
    if (status === "ready") {
      // 조회가 성공하고 표시 대상 유무까지 확인한 뒤에만 오늘 브리핑을 소진한다. 빈 날도
      // 성공한 확인이므로 기록하되 창은 열지 않는다.
      if (total > 0) setOpen(true);
      completeBriefing(briefingAttempt.businessDateKey);
      return;
    }
    if (status === "error") failBriefing(briefingAttempt.businessDateKey);
  }, [briefingAttempt, completeBriefing, failBriefing, settlementCount, status, total]);

  /** 달력 버튼으로 여는 경로. 열 때마다 다시 읽어 기준일이 하루 밀린 목록을 보여주지 않는다. */
  const openAgenda = useCallback(() => {
    reload();
    setOpen(true);
  }, [reload]);

  const hasCount = status === "ready" && total > 0;

  return (
    <>
      <Button
        variant="plain"
        aria-label={hasCount ? `다가오는 일정 ${total}건` : "다가오는 일정을 엽니다"}
        aria-haspopup="dialog"
        onClick={openAgenda}
        icon={
          <span className="time-keeper__launcher">
            <OutlinedCalendarAltIcon />
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
            data-screen-id="F4-MOD-010"
            data-requirement-ids="F4-TK-08, F4-TK-12~21, F1-AL-01, F1-AL-03, F1-AL-04"
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
