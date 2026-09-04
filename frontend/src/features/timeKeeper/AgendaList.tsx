/**
 * 일정·할 일 목록의 본문.
 *
 * 조회 전용이다. AI를 부르지 않고 장부를 바꾸지 않는다. 여기서 하는 일은 이미 장부에 있는
 * 날짜와 주기 규칙에서 나온 기한을 종류별로 묶어 세우고 연락할 사람을 함께 보여주는 것뿐이다.
 *
 * **해당되는 내용이 있는 종류만 그린다.** 종류를 미리 다 늘어놓고 "0건"으로 채우면 대부분이
 * 빈 줄이 되어 정작 할 일이 있는 줄이 묻힌다. 서버도 0건인 종류는 아예 싣지 않는다.
 *
 * 상태 표시를 이 컴포넌트가 함께 갖는 이유는, 브리핑 창과 알림 버튼이 같은 실패·빈 목록
 * 문구를 써야 하기 때문이다. 창마다 다시 쓰면 두 곳의 문구가 조용히 갈라진다.
 */

import { Button } from "@patternfly/react-core";
import type { DismissedNeglectedControl } from "./hooks/useDismissedNeglected.ts";
import type { AgendaState } from "./hooks/useAgenda.ts";
import type { AgendaItemDto } from "./model/dto.ts";
import {
  agendaActionLabel,
  agendaCategoryLabel,
  agendaItemKey,
  agendaTargetLabel,
  dDayLabel,
  groupAgenda,
  hasPrivacyConsent,
  hiddenCount,
  isNeglected,
  isUrgent,
  neglectedDismissKey,
  primaryPhone,
  roleLabel,
} from "./model/viewModel.ts";
import type { AgendaGroup } from "./model/viewModel.ts";

function ContactLine({ item }: { item: AgendaItemDto }) {
  if (item.contacts.length === 0) {
    return <span className="time-keeper__contact time-keeper__contact--none">연락처 없음</span>;
  }
  return (
    <>
      {item.contacts.map((contact) => {
        const phone = primaryPhone(contact);
        return (
          <span
            className="time-keeper__contact"
            key={`${contact.role ?? "client"}-${contact.party.id}`}
          >
            <span className="time-keeper__role">{roleLabel(contact.role)}</span>
            <span className="time-keeper__name">{contact.party.name}</span>
            {phone == null ? (
              <span className="time-keeper__phone time-keeper__phone--none">번호 없음</span>
            ) : (
              <span className="time-keeper__phone">{phone}</span>
            )}
            {/* 동의가 없는 인물은 연락 대상으로 내밀지 않는다는 사실을 그 자리에서 알린다. */}
            {hasPrivacyConsent(contact) ? null : (
              <span className="time-keeper__flag">동의 없음</span>
            )}
          </span>
        );
      })}
    </>
  );
}

/**
 * 종류 하나의 묶음.
 *
 * ``renderItems``만 그리고 ``hidden``은 ``group``(창 전체 참값 기준)으로 그대로 잰다. 밀린
 * 재연락·재확인이 아래 별도 묶음으로 빠져도 "상한에 걸려 아예 못 받은 건수"라는 뜻은 바뀌지
 * 않는다.
 */
function AgendaGroupSection({
  group,
  renderItems,
}: {
  group: AgendaGroup;
  renderItems: AgendaItemDto[];
}) {
  const action = agendaActionLabel(group.category);
  const hidden = hiddenCount(group);

  return (
    <section className="time-keeper__group" aria-label={agendaCategoryLabel(group.category)}>
      <h3 className="time-keeper__group-heading">
        <span className="time-keeper__group-name">{agendaCategoryLabel(group.category)}</span>
        <span className="time-keeper__group-count">{group.total}건</span>
        {action != null && <span className="time-keeper__action">{action}</span>}
      </h3>
      <ul className="time-keeper__list">
        {renderItems.map((item) => (
          <li className="time-keeper__row" key={agendaItemKey(item)}>
            <span
              className={
                isUrgent(item.days_until_due)
                  ? "time-keeper__dday time-keeper__dday--urgent"
                  : "time-keeper__dday"
              }
            >
              {dDayLabel(item.days_until_due)}
            </span>
            <span className="time-keeper__body">
              <span className="time-keeper__target">{agendaTargetLabel(item)}</span>
              <span className="time-keeper__meta">
                <span className="time-keeper__date">{item.due_date}</span>
              </span>
              <span className="time-keeper__contacts">
                <ContactLine item={item} />
              </span>
            </span>
          </li>
        ))}
      </ul>
      {hidden > 0 && <p className="time-keeper__more">외 {hidden}건은 장부에서 확인해 주세요.</p>}
    </section>
  );
}

/**
 * 되돌아보는 기간을 넘겨 밀린 재연락·재확인 한 줄.
 *
 * 여러 종류가 한 묶음에 섞이므로 행마다 종류 이름을 함께 세운다. "다시 보지 않기"는 이
 * 브라우저에서만 감추고, 다시 연락해 기한이 새로 생기면 감춘 기록과 무관하게 다시 보인다.
 */
function NeglectedRow({
  item,
  onDismiss,
}: {
  item: AgendaItemDto;
  onDismiss: (item: AgendaItemDto) => void;
}) {
  return (
    <li className="time-keeper__row">
      <span className="time-keeper__dday time-keeper__dday--urgent">
        {dDayLabel(item.days_until_due)}
      </span>
      <span className="time-keeper__body">
        <span className="time-keeper__target">
          {agendaCategoryLabel(item.category)} · {agendaTargetLabel(item)}
        </span>
        <span className="time-keeper__meta">
          <span className="time-keeper__date">{item.due_date}</span>
        </span>
        <span className="time-keeper__contacts">
          <ContactLine item={item} />
        </span>
      </span>
      <Button
        className="time-keeper__dismiss"
        variant="secondary"
        size="sm"
        onClick={() => onDismiss(item)}
      >
        다시 보지 않기
      </Button>
    </li>
  );
}

function NeglectedSection({
  items,
  onDismiss,
}: {
  items: AgendaItemDto[];
  onDismiss: (item: AgendaItemDto) => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="time-keeper__group time-keeper__group--neglected" aria-label="밀린 재연락·재확인">
      <h3 className="time-keeper__group-heading">
        <span className="time-keeper__group-name">밀린 재연락·재확인</span>
        <span className="time-keeper__group-count">{items.length}건</span>
      </h3>
      <p className="time-keeper__group-note">
        오래 방치된 대상입니다. 확인한 건은 「다시 보지 않기」로 감출 수 있고, 다시 연락하면 새
        기한으로 돌아옵니다.
      </p>
      <ul className="time-keeper__list">
        {items.map((item) => (
          <NeglectedRow item={item} key={agendaItemKey(item)} onDismiss={onDismiss} />
        ))}
      </ul>
    </section>
  );
}

export function AgendaList({
  agenda,
  dismissed,
}: {
  agenda: AgendaState;
  dismissed: DismissedNeglectedControl;
}) {
  const { items, categories, status, overdueDays } = agenda;

  if (status === "loading") {
    return (
      <p className="time-keeper__state" role="status">
        일정을 불러오는 중입니다.
      </p>
    );
  }

  if (status === "error") {
    return (
      <p className="time-keeper__state time-keeper__state--error" role="status">
        일정을 불러오지 못했습니다.{" "}
        <button type="button" className="time-keeper__retry" onClick={agenda.reload}>
          다시 시도
        </button>
      </p>
    );
  }

  // 서버가 실제로 적용한 되돌아보는 기간을 우선한다. 첫 응답이 오기 전 짧은 순간에는 items가
  // 비어 있어 어느 값을 써도 화면에 드러나지 않으므로 문서화된 기본값(7일)으로 충분하다.
  const effectiveOverdueDays = overdueDays ?? 7;
  const groups = groupAgenda(items, categories);
  // 감춘 건은 완전히 빠진다. 밀린 재연락·재확인이 "다가오는 일정" 쪽으로 되돌아가지 않는다.
  const neglected = items.filter(
    (item) =>
      isNeglected(item, effectiveOverdueDays) && !dismissed.isDismissed(neglectedDismissKey(item)),
  );
  const visibleGroups = groups
    .map((group) => ({
      group,
      // hidden 계산은 group(창 전체 참값) 기준으로 그대로 두고, 그릴 행만 종류에서 뗀다.
      renderItems: group.items.filter((item) => !isNeglected(item, effectiveOverdueDays)),
    }))
    .filter(({ renderItems }) => renderItems.length > 0);

  if (visibleGroups.length === 0 && neglected.length === 0) {
    return <p className="time-keeper__state">예정된 일정이 없습니다.</p>;
  }

  return (
    <div className="time-keeper__groups">
      {visibleGroups.map(({ group, renderItems }) => (
        <AgendaGroupSection group={group} key={group.category} renderItems={renderItems} />
      ))}
      <NeglectedSection
        items={neglected}
        onDismiss={(item) => dismissed.dismiss(neglectedDismissKey(item))}
      />
    </div>
  );
}
