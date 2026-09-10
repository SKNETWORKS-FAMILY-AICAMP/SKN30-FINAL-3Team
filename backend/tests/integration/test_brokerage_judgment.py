"""중개 판정 저장과 완료 전이의 수직 슬라이스.

실제 PostgreSQL 에 붙고 AI 호출 경계만 fake generator 로 바꾼다. 확인하는 것은 다섯이다.
판정 후보를 전부 저장하는가, 기각과 사유가 남는가, 후보 집합이 어긋난 결과를 거절하는가,
실패했을 때 부분 결과가 남지 않는가, 그리고 후보 0건이 AI 없이 완료되는가.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from brokerage_ai.f3 import (
    BrokerageJudgmentContractError,
    BrokerageJudgmentRequest,
    CandidateJudgment,
    InputPrivacyMode,
    NegotiationSide,
)
from brokerage_judgment_fixtures import (
    ATTEMPT,
    OWNER_QUOTE,
    WORKER,
    FakeJudgmentGenerator,
    Fixture,
    default_judgments,
)
from f3_committed_db import db_session
from f3_committed_db import remove_committed_rows as remove_committed_rows
from sqlalchemy import text

from domain.agent_execution import service
from domain.agent_execution.anchor_card import GenerationBindingError
from domain.agent_execution.judgment import (
    JudgmentBinding,
    JudgmentResultMismatchError,
    judge_and_store,
    prepare_judgment,
    store_judgment,
)
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CANDIDATE_CARDS_READY_STATUS,
    COMPLETED_STATUS,
    JUDGING_STATUS,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
)

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)


@requires_database
def test_every_judged_candidate_is_stored_with_its_grade_and_rank() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()

        stored = asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(generator),
            )
        )

        assert generator.calls == 1, "교차 판정 1회당 중개 판정 LLM 호출은 1회다 (F3-NF-04)"
        assert stored.candidate_count == 2
        assert fixture.stored_run(run_id)["status"] == COMPLETED_STATUS
        assert fixture.stored_run(run_id)["completed_at"] is not None

        rows = fixture.candidates()
        assert len(rows) == 2
        assert [row["match_rank"] for row in rows] == [1, 2]
        assert rows[0]["match_grade"] == "STRONG"
        assert rows[0]["evaluation_basis"]
        assert rows[0]["primary_obstacle"] == "가격 차"
        assert rows[0]["recommended_action"]["channel"] == "MESSAGE"
        assert fixture.header()["candidate_count"] == 2


@requires_database
def test_the_anchor_card_goes_out_once_with_all_candidates() -> None:
    """앵커 1장 + 후보 N장을 한 번에 보낸다 (F3-BR-01, F3-BR-02)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(generator),
            )
        )

        request = generator.requests[0]
        assert request.anchor.negotiation_side is NegotiationSide.LISTING
        assert request.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE
        assert len(request.candidates) == 2
        assert all(
            card.negotiation_side is NegotiationSide.REQUIREMENT for card in request.candidates
        )


@requires_database
def test_a_rejected_candidate_keeps_its_reason() -> None:
    """기각도 사유와 함께 남는다. 조용히 사라지는 후보를 만들지 않는다 (F3-BR-10)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        rejected = [row for row in fixture.candidates() if row["match_grade"] == "REJECTED"]
        assert len(rejected) == 1
        assert rejected[0]["exclusion_reason"] == "이사일이 어긋난다"


@requires_database
def test_the_quote_offsets_come_from_the_stored_card_evidence() -> None:
    """판정 단계에는 상담 원문이 없다. offset 은 카드가 저장해 둔 값을 그대로 옮긴다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        rows = [row for row in fixture.evidence() if row["evidence_type"] == "QUOTE"]
        assert rows, "앵커 카드의 인용을 근거로 쓴 판정이 있어야 한다"
        for row in rows:
            card_row = session.execute(
                text(
                    "SELECT quote_start_offset, quote_end_offset FROM"
                    " negotiation_position_evidence WHERE brokerage_id = :b"
                    " AND interaction_id = :i AND quote_text = :q LIMIT 1"
                ),
                {"b": fixture.brokerage_id, "i": row["interaction_id"], "q": row["quote_text"]},
            ).one()
            assert (row["quote_start_offset"], row["quote_end_offset"]) == tuple(card_row)


@requires_database
def test_no_candidate_completes_without_calling_the_model() -> None:
    """후보 0건은 AI 호출 없이 빈 최종 결과를 원자 저장하고 완료한다."""
    with db_session() as session:
        fixture = Fixture(session)
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()

        # 판정할 후보가 없으면 모델 설정도 조회할 이유가 없다.
        binding = JudgmentBinding(
            generator=generator,
            model_config_id=999_999_999,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        )
        stored = asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=binding,
            )
        )

        assert generator.calls == 0
        assert stored.candidate_count == 0
        assert fixture.candidates() == []
        assert fixture.header()["candidate_count"] == 0
        assert fixture.stored_run(run_id)["status"] == COMPLETED_STATUS


@requires_database
def test_a_missing_candidate_in_the_result_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()

        def drop_one(request: BrokerageJudgmentRequest) -> tuple[CandidateJudgment, ...]:
            return default_judgments(request)[:1]

        with pytest.raises(BrokerageJudgmentContractError, match="missing"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator(drop_one)),
                )
            )

        assert fixture.candidates() == []
        assert fixture.evidence() == []
        assert fixture.stored_run(run_id)["status"] != COMPLETED_STATUS


@requires_database
def test_a_non_empty_candidate_set_cannot_complete_without_a_result() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        binding = fixture.judgment_binding(FakeJudgmentGenerator())
        prepared = prepare_judgment(session, run_id, WORKER, ATTEMPT, binding)

        with pytest.raises(JudgmentResultMismatchError, match="requires a result"):
            store_judgment(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding,
                prepared,
                None,
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == JUDGING_STATUS


@requires_database
def test_duplicate_ranks_store_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        fixture.requirement(budget=3_100_000_000, party_name="손님B")
        run_id = fixture.run_to_candidate_cards()

        def same_rank(request: BrokerageJudgmentRequest) -> tuple[CandidateJudgment, ...]:
            return tuple(
                candidate.model_copy(update={"rank": 1}) for candidate in default_judgments(request)
            )

        with pytest.raises(BrokerageJudgmentContractError, match="1..N"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator(same_rank)),
                )
            )

        assert fixture.candidates() == []


@requires_database
def test_masked_input_is_refused_until_backend_masking_is_implemented() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()
        binding = JudgmentBinding(
            generator=generator,
            model_config_id=fixture.judgment_config_id,
            input_privacy_mode=InputPrivacyMode.MASKED,
        )

        with pytest.raises(GenerationBindingError, match="masked F1 judgment"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=binding,
                )
            )

        assert generator.calls == 0
        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_a_lost_lease_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        with pytest.raises(LeaseNotHeldError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id="another-worker",
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator()),
                )
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_a_changed_anchor_version_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        session.execute(
            text("UPDATE property_listing SET row_version = row_version + 1 WHERE id = :i"),
            {"i": fixture.listing_id},
        )
        session.commit()

        with pytest.raises(InputVersionChangedError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator()),
                )
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_a_candidate_changed_after_the_model_call_stores_nothing() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        requirement_id = fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()
        binding = fixture.judgment_binding(generator)
        prepared = prepare_judgment(session, run_id, WORKER, ATTEMPT, binding)
        assert prepared.request is not None
        result = asyncio.run(generator.judge_candidates(prepared.request))

        session.execute(
            text("UPDATE property_requirement SET row_version = row_version + 1 WHERE id = :i"),
            {"i": requirement_id},
        )
        session.commit()

        with pytest.raises(InputVersionChangedError, match="position card target changed"):
            store_judgment(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding,
                prepared,
                result,
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == JUDGING_STATUS


@requires_database
def test_a_position_card_config_cannot_be_used_for_the_judgment() -> None:
    """대리와 판정은 다른 capability 설정을 쓴다 (F3-NF-10)."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        wrong = JudgmentBinding(
            generator=FakeJudgmentGenerator(),
            model_config_id=fixture.card_config_id,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        )

        with pytest.raises(GenerationBindingError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=wrong,
                )
            )

        assert fixture.stored_run(run_id)["status"] == CANDIDATE_CARDS_READY_STATUS


@requires_database
def test_another_brokerage_judgment_config_is_refused() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        other = Fixture(session, name="다른 사무소")
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        foreign = JudgmentBinding(
            generator=FakeJudgmentGenerator(),
            model_config_id=other.judgment_config_id,
            input_privacy_mode=InputPrivacyMode.SYNTHETIC_PROTOTYPE,
        )

        with pytest.raises(GenerationBindingError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=foreign,
                )
            )

        assert fixture.candidates() == []


@requires_database
def test_a_provider_failure_leaves_no_partial_result() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        failing = FakeJudgmentGenerator(fail=RuntimeError("provider is unavailable"))

        with pytest.raises(RuntimeError, match="provider is unavailable"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(failing),
                )
            )

        assert fixture.candidates() == []
        assert fixture.evidence() == []
        assert fixture.stored_run(run_id)["status"] == JUDGING_STATUS


@requires_database
def test_an_expired_judging_run_is_reclaimed_and_completed() -> None:
    """Provider 호출 중 중단된 실행은 같은 바인딩으로 판정을 다시 시작할 수 있다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        with pytest.raises(RuntimeError, match="provider is unavailable"):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(
                        FakeJudgmentGenerator(fail=RuntimeError("provider is unavailable"))
                    ),
                )
            )

        session.execute(
            text(
                "UPDATE agent_run SET lease_expires_at = now() - interval '1 second' WHERE id = :i"
            ),
            {"i": run_id},
        )
        session.commit()

        reclaimed = service.claim_next_run(session, "worker-judgment-retry")
        assert reclaimed is not None
        assert reclaimed.id == run_id
        assert reclaimed.status == JUDGING_STATUS
        assert reclaimed.attempt_count == ATTEMPT + 1

        stored = asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id="worker-judgment-retry",
                attempt_count=ATTEMPT + 1,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        assert stored.candidate_count == 1
        assert fixture.stored_run(run_id)["status"] == COMPLETED_STATUS


@requires_database
def test_a_late_result_from_the_previous_attempt_is_fenced_out() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        generator = FakeJudgmentGenerator()
        binding = fixture.judgment_binding(generator)
        prepared = prepare_judgment(session, run_id, WORKER, ATTEMPT, binding)
        assert prepared.request is not None
        result = asyncio.run(generator.judge_candidates(prepared.request))

        session.execute(
            text(
                "UPDATE agent_run SET lease_expires_at = now() - interval '1 second' WHERE id = :i"
            ),
            {"i": run_id},
        )
        session.commit()
        reclaimed = service.claim_next_run(session, "worker-judgment-new-owner")
        assert reclaimed is not None and reclaimed.attempt_count == ATTEMPT + 1

        with pytest.raises(LeaseNotHeldError):
            store_judgment(
                session,
                run_id,
                WORKER,
                ATTEMPT,
                binding,
                prepared,
                result,
            )

        assert fixture.candidates() == []
        assert fixture.stored_run(run_id)["status"] == JUDGING_STATUS


@requires_database
def test_the_run_snapshot_carries_no_prompt_or_model_response() -> None:
    """전체 프롬프트와 전체 모델 응답은 실행에 남기지 않는다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        snapshot = fixture.stored_run(run_id)["redacted_output_snapshot"]
        judgment = snapshot["judgment_result"]
        assert set(judgment) == {
            "match_evaluation_id",
            "anchor_position_analysis_id",
            "candidate_count",
            "contract_version",
            "prompt_version",
            "workflow_version",
            "provider",
            "model",
            "grades",
        }
        # 판정 바인딩은 allowlist 필드만 남는다. API key 와 endpoint 는 들어가지 않는다.
        assert set(snapshot["judgment"]) == {
            "model_config_id",
            "model_snapshot",
            "prompt_version",
            "workflow_version",
            "input_privacy_mode",
        }
        assert snapshot["judgment"]["input_privacy_mode"] == "SYNTHETIC_PROTOTYPE"
        assert set(snapshot["judgment"]["model_snapshot"]) == {
            "provider",
            "model_name",
            "model_version",
            "endpoint_alias",
            "config_key",
            "config_version",
        }
        assert OWNER_QUOTE not in str(snapshot)


@requires_database
def test_the_candidate_side_is_the_opposite_of_the_anchor() -> None:
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()

        asyncio.run(
            judge_and_store(
                session,
                run_id=run_id,
                worker_id=WORKER,
                attempt_count=ATTEMPT,
                binding=fixture.judgment_binding(FakeJudgmentGenerator()),
            )
        )

        card_ids = [row["candidate_position_analysis_id"] for row in fixture.candidates()]
        sides = session.execute(
            text(
                "SELECT DISTINCT negotiation_side FROM negotiation_position_analysis"
                " WHERE brokerage_id = :b AND id = ANY(:ids)"
            ),
            {"b": fixture.brokerage_id, "ids": card_ids},
        ).scalars()
        assert set(sides) == {AnchorType.REQUIREMENT.value}


@requires_database
def test_an_anchor_ready_run_is_not_judged() -> None:
    """단계를 건너뛰지 않는다. 기대 상태가 아니면 lease 를 잡지 못한 것으로 다룬다."""
    with db_session() as session:
        fixture = Fixture(session)
        fixture.requirement(budget=3_000_000_000, party_name="손님A")
        run_id = fixture.run_to_candidate_cards()
        session.execute(
            text("UPDATE agent_run SET status = :s WHERE id = :i"),
            {"s": ANCHOR_READY_STATUS, "i": run_id},
        )
        session.commit()

        with pytest.raises(LeaseNotHeldError):
            asyncio.run(
                judge_and_store(
                    session,
                    run_id=run_id,
                    worker_id=WORKER,
                    attempt_count=ATTEMPT,
                    binding=fixture.judgment_binding(FakeJudgmentGenerator()),
                )
            )
