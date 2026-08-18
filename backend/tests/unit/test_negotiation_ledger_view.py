"""코드가 산출하는 값들 — 인도 가능일·마감일·보류 게이트·로그 원문 재구성.

전부 LLM 없이 돈다. 날짜 산수를 모델에 맡기지 않는다는 규칙이 지켜지는지 보는 자리다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from domain.negotiation import ledger_view
from domain.property_ledger.models import (
    ClientInteraction,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
    PropertyUnitPartyRelation,
)

AS_OF = date(2026, 8, 17)


def unit(**overrides: object) -> PropertyUnit:
    values: dict[str, object] = {
        "brokerage_id": 1,
        "complex_id": 1,
        "building_number": "203",
        "unit_number": "1101",
        "pyeong": Decimal("33.00"),
        "custom_fields": {},
    }
    values.update(overrides)
    return PropertyUnit(**values)  # pyright: ignore[reportArgumentType]


def interaction(
    *,
    at: datetime | None,
    role: str | None,
    index: int | None,
    content: str,
) -> ClientInteraction:
    return ClientInteraction(
        brokerage_id=1,
        interaction_at=at,
        counterparty_role=role,
        counterparty_index=index,
        interaction_content=content,
    )


def relation(*, is_co_owner: bool, role_index: int = 1) -> PropertyUnitPartyRelation:
    return PropertyUnitPartyRelation(
        brokerage_id=1,
        unit_id=1,
        party_id=1,
        role="OWNER",
        role_index=role_index,
        is_co_owner=is_co_owner,
    )


class TestAvailableFrom:
    def test_leased_unit_hands_over_at_the_tenancy_expiry(self) -> None:
        handover, note = ledger_view.available_from(
            unit(tenancy_status="LEASED", tenancy_expiry_date=date(2027, 4, 30)), AS_OF
        )

        assert handover == date(2027, 4, 30)
        assert note == "임차 만기 2027-04-30"

    def test_leased_unit_without_an_expiry_is_undecidable(self) -> None:
        handover, note = ledger_view.available_from(unit(tenancy_status="LEASED"), AS_OF)

        assert handover is None
        assert note == "임차 중 · 만기 불명"

    def test_owner_stated_preference_wins_over_the_default_settlement(self) -> None:
        handover, note = ledger_view.available_from(
            unit(
                tenancy_status="SELF_OCCUPIED",
                custom_fields={"handover_pref_date": "2026-12-15"},
            ),
            AS_OF,
        )

        assert handover == date(2026, 12, 15)
        assert note == "소유자 진술 인도 희망일"

    def test_self_occupied_falls_back_to_the_settlement_window(self) -> None:
        handover, _ = ledger_view.available_from(unit(tenancy_status="SELF_OCCUPIED"), AS_OF)

        assert handover == date(2026, 11, 15)

    def test_vacant_falls_back_to_the_clearing_window(self) -> None:
        handover, _ = ledger_view.available_from(unit(tenancy_status="VACANT"), AS_OF)

        assert handover == date(2026, 9, 16)

    def test_a_blocking_precondition_beats_every_other_rule(self) -> None:
        """선행 조건이 걸려 있으면 임차 만기가 있어도 인도일을 못 낸다."""
        handover, note = ledger_view.available_from(
            unit(
                tenancy_status="LEASED",
                tenancy_expiry_date=date(2027, 4, 30),
                custom_fields={"handover_blocked_reason": "본인 매수 건 잔금 선행"},
            ),
            AS_OF,
        )

        assert handover is None
        assert note == "선행 조건 미확정 — 본인 매수 건 잔금 선행"

    def test_unknown_tenancy_is_undecidable(self) -> None:
        handover, note = ledger_view.available_from(unit(tenancy_status="UNKNOWN"), AS_OF)

        assert handover is None
        assert note == "임대차 상태 불명"


class TestLogReconstruction:
    def test_utc_timestamps_are_rendered_in_kst(self) -> None:
        """시드는 UTC 로 저장돼 있다. 변환을 빼먹으면 날짜 경계가 어긋난다."""
        line = ledger_view.format_log_line(
            interaction(
                at=datetime(2026, 6, 11, 10, 42, tzinfo=UTC),
                role="OWNER_SIDE",
                index=1,
                content="24.5억은 받아야 한다. 아래로는 생각 없다",
            )
        )

        assert line == "[26-06-11 19:42 주]①24.5억은 받아야 한다. 아래로는 생각 없다"

    def test_utc_evening_rolls_over_to_the_next_kst_day(self) -> None:
        line = ledger_view.format_log_line(
            interaction(
                at=datetime(2026, 6, 11, 20, 0, tzinfo=UTC),
                role="TENANT",
                index=2,
                content="집 보여주기 어렵다",
            )
        )

        assert line.startswith("[26-06-12 05:00 세]②")

    def test_every_counterparty_role_maps_to_its_ledger_symbol(self) -> None:
        symbols = [
            ledger_view.format_log_line(
                interaction(
                    at=datetime(2026, 1, 1, 3, 0, tzinfo=UTC), role=role, index=1, content="x"
                )
            ).split("]")[0][-1]
            for role in ("OWNER_SIDE", "TENANT", "CO_BROKER", "BUYER", "OTHER")
        ]

        assert symbols == ["주", "세", "중", "손", "기"]

    def test_an_unknown_role_falls_back_to_the_other_symbol(self) -> None:
        line = ledger_view.format_log_line(
            interaction(
                at=datetime(2026, 1, 1, 3, 0, tzinfo=UTC), role=None, index=None, content="x"
            )
        )

        assert line == "[26-01-01 12:00 기]x"

    def test_logs_are_ordered_newest_first(self) -> None:
        lines = ledger_view.sorted_log_lines(
            [
                interaction(
                    at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                    role="OWNER_SIDE",
                    index=1,
                    content="옛것",
                ),
                interaction(
                    at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
                    role="OWNER_SIDE",
                    index=1,
                    content="새것",
                ),
            ]
        )

        assert "새것" in lines[0]
        assert "옛것" in lines[1]


class TestHoldFlags:
    def test_tenant_only_recent_statements_raise_the_decision_maker_flag(self) -> None:
        logs = [
            interaction(
                at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
                role="TENANT",
                index=1,
                content="세입자 발화",
            )
        ]

        flags = ledger_view.hold_flags(unit(), [], logs, AS_OF)

        assert flags == ["응대자 결정권 미확인 — 최근 진술이 임차인(세) 발화뿐"]

    def test_a_recent_owner_statement_clears_the_decision_maker_flag(self) -> None:
        logs = [
            interaction(
                at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC), role="TENANT", index=1, content="세입자"
            ),
            interaction(
                at=datetime(2026, 7, 2, 0, 0, tzinfo=UTC),
                role="OWNER_SIDE",
                index=1,
                content="소유자",
            ),
        ]

        assert ledger_view.hold_flags(unit(), [], logs, AS_OF) == []

    def test_co_ownership_counts_distinct_owner_speakers(self) -> None:
        logs = [
            interaction(
                at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
                role="OWNER_SIDE",
                index=1,
                content="남편",
            ),
            interaction(
                at=datetime(2026, 7, 2, 0, 0, tzinfo=UTC),
                role="OWNER_SIDE",
                index=2,
                content="아내",
            ),
        ]

        flags = ledger_view.hold_flags(unit(), [relation(is_co_owner=True)], logs, AS_OF)

        assert flags == ["공동명의 — 소유자측 화자 2명의 진술이 있다. 단독 결정 불가"]

    def test_co_ownership_with_a_single_speaker_still_blocks(self) -> None:
        logs = [
            interaction(
                at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
                role="OWNER_SIDE",
                index=1,
                content="남편",
            )
        ]

        flags = ledger_view.hold_flags(unit(), [relation(is_co_owner=True)], logs, AS_OF)

        assert flags == ["공동명의 — 단독 결정 불가"]

    def test_a_blocking_precondition_is_reported_as_an_ordered_deal(self) -> None:
        flags = ledger_view.hold_flags(
            unit(custom_fields={"handover_blocked_reason": "본인 매수 건 잔금 선행"}),
            [],
            [],
            AS_OF,
        )

        assert flags == ["선행 조건 — 본인 매수 건 잔금 선행 (순서가 있는 성사)"]


class TestCardInputs:
    def test_money_is_converted_from_won_to_eok(self) -> None:
        listing = PropertyListing(
            brokerage_id=1, unit_id=1, is_sale_available=True, sale_price=2_230_000_000
        )

        assert ledger_view.listing_book_amount(listing) == 22.3

    def test_listing_input_carries_no_customer_field(self) -> None:
        """수용 기준 3 — 매물 대리 입력에 손님 쪽 값이 들어갈 자리가 없다."""
        card_input = ledger_view.listing_card_input(
            unit(tenancy_status="VACANT", memo="급매"),
            PropertyListing(
                brokerage_id=1, unit_id=1, is_sale_available=True, sale_price=2_230_000_000
            ),
            [],
        )

        assert card_input.side == "매물"
        assert card_input.label == "203동 1101호"
        assert card_input.book_amount == 22.3
        assert card_input.deal_type_book == "매매"
        assert "현 임대차 공실" in (card_input.note or "")

    def test_requirement_input_uses_the_ceiling_budget_and_first_pyeong(self) -> None:
        requirement = PropertyRequirement(
            brokerage_id=1,
            party_id=1,
            demand_type="BUY",
            desired_pyeongs=[Decimal("33.00")],
            max_budget_amount=2_200_000_000,
            desired_move_in_date=date(2027, 3, 2),
        )

        card_input = ledger_view.requirement_card_input(requirement, "김O수", [])

        assert card_input.side == "손님"
        assert card_input.book_amount == 22.0
        assert card_input.pyeong == 33.0
        assert card_input.deal_type_book == "매매"
        assert ledger_view.hard_deadline(requirement) == date(2027, 3, 2)

    def test_a_requirement_without_a_move_in_date_has_no_deadline(self) -> None:
        requirement = PropertyRequirement(brokerage_id=1, party_id=1, demand_type="BUY")

        assert ledger_view.hard_deadline(requirement) is None
