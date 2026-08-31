from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, create_engine, select

from domain.agent_execution import repository, service
from domain.agent_execution.models import CROSS_JUDGMENT_RUN_TYPE, AgentRun

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

WORKER_A = "worker-a"
WORKER_B = "worker-b"

INSERT_RUN = text(
    "INSERT INTO agent_run (brokerage_id, run_group_id, parent_run_id, run_type, agent_type,"
    " status, trigger_type, requested_by, created_at, started_at, attempt_count, lease_owner,"
    " lease_expires_at)"
    " VALUES (:brokerage_id, :run_group_id, :parent_run_id, :run_type, 'BROKERAGE_WORKFLOW',"
    " :status, :trigger_type, :requested_by, :created_at, :started_at, :attempt_count,"
    " :lease_owner, :lease_expires_at) RETURNING id"
)


def insert_run(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    *,
    status: str = "QUEUED",
    run_type: str = CROSS_JUDGMENT_RUN_TYPE,
    parent_run_id: int | None = None,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    attempt_count: int = 0,
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    trigger_type: str = "USER_REQUEST",
) -> int:
    return session.execute(
        INSERT_RUN,
        {
            "brokerage_id": brokerage_id,
            "run_group_id": str(uuid4()),
            "parent_run_id": parent_run_id,
            "run_type": run_type,
            "status": status,
            "trigger_type": trigger_type,
            "requested_by": requested_by,
            "created_at": created_at or datetime.now(UTC),
            "started_at": started_at,
            "attempt_count": attempt_count,
            "lease_owner": lease_owner,
            "lease_expires_at": lease_expires_at,
        },
    ).scalar_one()


def create_tenant(session: Session, name: str) -> tuple[int, int]:
    brokerage_id = session.execute(
        text("INSERT INTO brokerage (name) VALUES (:n) RETURNING id"), {"n": name}
    ).scalar_one()
    user_id = session.execute(
        text(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:b, 'claim-test', 'unused', '선점검증', 'OWNER') RETURNING id"
        ),
        {"b": brokerage_id},
    ).scalar_one()
    return brokerage_id, user_id


def stored_run(session: Session, run_id: int) -> dict:
    row = (
        session.execute(text("SELECT * FROM agent_run WHERE id = :i"), {"i": run_id})
        .mappings()
        .one()
    )
    return dict(row)


@contextmanager
def claim_session() -> Iterator[tuple[Session, int, int]]:
    """실제 PostgreSQL에 붙되 종료 시 전부 롤백한다. service의 commit은 savepoint에 걸린다."""
    engine = create_engine(os.environ["TEST_DB_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        brokerage_id, user_id = create_tenant(session, "선점 검증 사무소")
        yield session, brokerage_id, user_id
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@contextmanager
def committed_runs(count: int) -> Iterator[list[int]]:
    """연결이 다른 Worker가 서로 보려면 커밋된 행이 필요하다. 끝나면 반드시 지운다."""
    engine = create_engine(os.environ["TEST_DB_URL"])
    brokerage_id: int | None = None
    try:
        with Session(engine) as setup:
            brokerage_id, user_id = create_tenant(setup, "동시선점 검증 사무소")
            base = datetime.now(UTC)
            run_ids = [
                insert_run(
                    setup,
                    brokerage_id,
                    user_id,
                    created_at=base + timedelta(seconds=index),
                )
                for index in range(count)
            ]
            setup.commit()
        yield run_ids
    finally:
        if brokerage_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    text("DELETE FROM agent_run WHERE brokerage_id = :b"), {"b": brokerage_id}
                )
                cleanup.execute(
                    text("DELETE FROM app_user WHERE brokerage_id = :b"), {"b": brokerage_id}
                )
                cleanup.execute(text("DELETE FROM brokerage WHERE id = :b"), {"b": brokerage_id})
                cleanup.commit()
        engine.dispose()


@requires_database
def test_queued_root_run_is_claimed_with_a_fresh_lease() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(session, brokerage_id, user_id)

        claimed = service.claim_next_run(session, WORKER_A)

        assert claimed is not None
        assert claimed.id == run_id
        stored = stored_run(session, run_id)
        assert stored["status"] == "RUNNING"
        assert stored["lease_owner"] == WORKER_A
        assert stored["attempt_count"] == 1
        assert stored["started_at"] is not None

        remaining = session.execute(
            text("SELECT lease_expires_at - now() AS remaining FROM agent_run WHERE id = :i"),
            {"i": run_id},
        ).scalar_one()
        assert timedelta(minutes=4, seconds=50) <= remaining <= timedelta(minutes=5)


@requires_database
def test_oldest_run_is_claimed_first() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        base = datetime.now(UTC)
        newer = insert_run(session, brokerage_id, user_id, created_at=base)
        older = insert_run(session, brokerage_id, user_id, created_at=base - timedelta(hours=1))

        first = service.claim_next_run(session, WORKER_A)
        second = service.claim_next_run(session, WORKER_B)

        assert first is not None and first.id == older
        assert second is not None and second.id == newer


@requires_database
def test_child_run_is_never_claimed() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        parent = insert_run(session, brokerage_id, user_id, status="RUNNING")
        insert_run(session, brokerage_id, user_id, parent_run_id=parent)

        assert service.claim_next_run(session, WORKER_A) is None


@requires_database
def test_other_run_type_is_never_claimed() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        insert_run(session, brokerage_id, user_id, run_type="POSITION_ANALYSIS")

        assert service.claim_next_run(session, WORKER_A) is None


@requires_database
@pytest.mark.parametrize("status", ["COMPLETED", "JUDGING", "FAILED_TERMINAL", "CANCELLED"])
def test_runs_in_other_states_are_never_claimed(status: str) -> None:
    with claim_session() as (session, brokerage_id, user_id):
        insert_run(session, brokerage_id, user_id, status=status)

        assert service.claim_next_run(session, WORKER_A) is None


@requires_database
def test_running_run_with_a_live_lease_is_not_claimed() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        insert_run(
            session,
            brokerage_id,
            user_id,
            status="RUNNING",
            attempt_count=1,
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=4),
        )

        assert service.claim_next_run(session, WORKER_B) is None


@requires_database
def test_expired_lease_is_reclaimed_and_keeps_the_original_started_at() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        started_at = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
        run_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status="RUNNING",
            attempt_count=1,
            started_at=started_at,
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        claimed = service.claim_next_run(session, WORKER_B)

        assert claimed is not None and claimed.id == run_id
        stored = stored_run(session, run_id)
        assert stored["status"] == "RUNNING"
        assert stored["lease_owner"] == WORKER_B
        assert stored["attempt_count"] == 2
        assert stored["started_at"] == started_at


@requires_database
@pytest.mark.parametrize(
    "progress_status",
    ["ANCHOR_READY", "CANDIDATES_READY", "CANDIDATE_CARDS_READY", "JUDGING"],
)
def test_expired_intermediate_run_is_reclaimed_without_losing_its_progress(
    progress_status: str,
) -> None:
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status=progress_status,
            attempt_count=1,
            started_at=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        claimed = service.claim_next_run(session, WORKER_B)

        assert claimed is not None and claimed.id == run_id
        stored = stored_run(session, run_id)
        assert stored["status"] == progress_status
        assert stored["lease_owner"] == WORKER_B
        assert stored["attempt_count"] == 2


@requires_database
@pytest.mark.parametrize(
    "progress_status",
    ["RUNNING", "ANCHOR_READY", "CANDIDATES_READY", "CANDIDATE_CARDS_READY", "JUDGING"],
)
def test_expired_run_over_the_attempt_limit_is_terminated_and_not_claimed(
    progress_status: str,
) -> None:
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status=progress_status,
            attempt_count=service.MAX_CLAIM_ATTEMPTS,
            started_at=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        assert service.claim_next_run(session, WORKER_B) is None

        stored = stored_run(session, run_id)
        assert stored["status"] == "FAILED_TERMINAL"
        assert stored["failure_code"] == "LEASE_EXPIRED_MAX_ATTEMPTS"
        assert stored["failure_message"] == service.LEASE_EXPIRED_FAILURE_MESSAGE
        assert stored["completed_at"] is not None
        assert stored["lease_owner"] is None
        assert stored["lease_expires_at"] is None
        assert stored["attempt_count"] == service.MAX_CLAIM_ATTEMPTS


@requires_database
def test_parked_ledger_save_run_waits_and_resumes_at_the_attempt_limit() -> None:
    """재시도 상한에서 앵커 카드에 성공해도 기다렸다가 판정을 이어갈 수 있다."""
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(
            session,
            brokerage_id,
            user_id,
            status="ANCHOR_READY",
            trigger_type="LEDGER_SAVE",
            attempt_count=service.MAX_CLAIM_ATTEMPTS,
            started_at=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
            lease_owner=WORKER_A,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        assert service.claim_next_run(session, WORKER_B) is None

        stored = stored_run(session, run_id)
        assert stored["status"] == "ANCHOR_READY"
        assert stored["failure_code"] is None
        assert stored["completed_at"] is None
        assert stored["attempt_count"] == service.MAX_CLAIM_ATTEMPTS

        changed = repository.resume_ledger_save_run(
            session, run_id, brokerage_id, "USER_REQUEST"
        )
        session.commit()
        claimed = service.claim_next_run(session, WORKER_B)

        assert changed == 1
        assert claimed is not None and claimed.id == run_id
        assert claimed.status == "ANCHOR_READY"
        # 사용자 요청에 따른 계획된 handoff는 실패 재시도로 세지 않는다.
        assert claimed.attempt_count == service.MAX_CLAIM_ATTEMPTS


@requires_database
def test_attempt_limit_cleanup_leaves_child_and_other_run_types_untouched() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        expired = datetime.now(UTC) - timedelta(seconds=1)
        parent = insert_run(session, brokerage_id, user_id, status="COMPLETED")
        child = insert_run(
            session,
            brokerage_id,
            user_id,
            status="RUNNING",
            parent_run_id=parent,
            attempt_count=service.MAX_CLAIM_ATTEMPTS,
            lease_expires_at=expired,
        )
        other_type = insert_run(
            session,
            brokerage_id,
            user_id,
            status="RUNNING",
            run_type="POSITION_ANALYSIS",
            attempt_count=service.MAX_CLAIM_ATTEMPTS,
            lease_expires_at=expired,
        )

        assert service.claim_next_run(session, WORKER_A) is None

        assert stored_run(session, child)["status"] == "RUNNING"
        assert stored_run(session, other_type)["status"] == "RUNNING"


@requires_database
def test_claim_returns_none_when_nothing_is_available() -> None:
    with claim_session() as (session, _brokerage_id, _user_id):
        assert service.claim_next_run(session, WORKER_A) is None


@requires_database
def test_database_error_rolls_back_the_whole_claim_transaction() -> None:
    """lease_owner가 컬럼 길이를 넘겨 실패한다. 같은 트랜잭션의 상한 초과 정리도 함께 취소된다."""
    with claim_session() as (session, brokerage_id, user_id):
        exhausted = insert_run(
            session,
            brokerage_id,
            user_id,
            status="RUNNING",
            attempt_count=service.MAX_CLAIM_ATTEMPTS,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        queued = insert_run(session, brokerage_id, user_id)
        # 실패 경로가 rollback을 부르므로 준비 데이터는 미리 확정해 둔다.
        session.commit()

        with pytest.raises(SQLAlchemyError):
            service.claim_next_run(session, "w" * 65)

        assert stored_run(session, exhausted)["status"] == "RUNNING"
        untouched = stored_run(session, queued)
        assert untouched["status"] == "QUEUED"
        assert untouched["attempt_count"] == 0
        assert untouched["lease_owner"] is None


@requires_database
def test_a_locked_run_is_skipped_by_another_connection() -> None:
    """FOR UPDATE SKIP LOCKED 확인. 커밋하지 않은 채 잠근 행은 다른 연결이 건너뛴다."""
    with committed_runs(1) as run_ids:
        engine_a = create_engine(os.environ["TEST_DB_URL"])
        engine_b = create_engine(os.environ["TEST_DB_URL"])
        try:
            with Session(engine_a) as session_a, Session(engine_b) as session_b:
                locked = repository.lock_claimable_run(session_a, service.MAX_CLAIM_ATTEMPTS)
                assert locked is not None and locked.id == run_ids[0]

                # session_a 가 아직 커밋하지 않았다. 유일한 대상이 잠겨 있으므로 건너뛴다.
                assert repository.lock_claimable_run(session_b, service.MAX_CLAIM_ATTEMPTS) is None

                session_a.rollback()
                session_b.rollback()
        finally:
            engine_a.dispose()
            engine_b.dispose()


@requires_database
def test_two_connections_claim_different_runs() -> None:
    with committed_runs(2) as run_ids:
        engine_a = create_engine(os.environ["TEST_DB_URL"])
        engine_b = create_engine(os.environ["TEST_DB_URL"])
        try:
            with Session(engine_a) as session_a, Session(engine_b) as session_b:
                first = repository.lock_claimable_run(session_a, service.MAX_CLAIM_ATTEMPTS)
                second = repository.lock_claimable_run(session_b, service.MAX_CLAIM_ATTEMPTS)

                assert first is not None and second is not None
                assert first.id != second.id
                assert {first.id, second.id} == set(run_ids)

                session_a.rollback()
                session_b.rollback()
        finally:
            engine_a.dispose()
            engine_b.dispose()


@requires_database
def test_parallel_workers_never_claim_the_same_run() -> None:
    """서로 다른 연결의 Worker 4개가 동시에 선점해도 같은 실행을 가져가지 않는다."""
    worker_count = 4
    with committed_runs(worker_count) as run_ids:
        barrier = threading.Barrier(worker_count)
        claimed: list[tuple[str, int]] = []
        failures: list[BaseException] = []
        lock = threading.Lock()

        def claim(index: int) -> None:
            engine = create_engine(os.environ["TEST_DB_URL"])
            worker_id = f"worker-{index}"
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    run = service.claim_next_run(session, worker_id)
                    if run is not None and run.id is not None:
                        with lock:
                            claimed.append((worker_id, run.id))
            except BaseException as error:  # noqa: BLE001 - 스레드 실패를 본 스레드로 옮긴다
                with lock:
                    failures.append(error)
            finally:
                engine.dispose()

        threads = [threading.Thread(target=claim, args=(index,)) for index in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert failures == []
        assert len(claimed) == worker_count
        assert len({run_id for _, run_id in claimed}) == worker_count
        assert {run_id for _, run_id in claimed} == set(run_ids)

        engine = create_engine(os.environ["TEST_DB_URL"])
        try:
            with Session(engine) as verify:
                for worker_id, run_id in claimed:
                    stored = stored_run(verify, run_id)
                    assert stored["status"] == "RUNNING"
                    assert stored["lease_owner"] == worker_id
                    assert stored["attempt_count"] == 1
        finally:
            engine.dispose()


@requires_database
def test_longest_documented_status_round_trips_through_the_model() -> None:
    """CANDIDATE_CARDS_READY 는 21자다. status 컬럼과 SQLModel 이 20자면 저장에서 잘린다."""
    with claim_session() as (session, brokerage_id, user_id):
        run = AgentRun(
            brokerage_id=brokerage_id,
            run_group_id=uuid4(),
            run_type=CROSS_JUDGMENT_RUN_TYPE,
            agent_type="BROKERAGE_WORKFLOW",
            status="CANDIDATE_CARDS_READY",
            trigger_type="USER_REQUEST",
            requested_by=user_id,
        )
        repository.add_agent_run(session, run)
        session.commit()
        run_id = run.id
        assert run_id is not None

        session.expire_all()
        reloaded = (
            session.execute(select(AgentRun).where(col(AgentRun.id) == run_id)).scalars().one()
        )

        assert reloaded.status == "CANDIDATE_CARDS_READY"
        assert stored_run(session, run_id)["status"] == "CANDIDATE_CARDS_READY"


@requires_database
def test_retry_release_makes_the_same_stage_immediately_claimable() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(session, brokerage_id, user_id)
        claimed = service.claim_next_run(session, WORKER_A)
        assert claimed is not None

        changed = repository.release_lease(
            session, run_id, brokerage_id, WORKER_A, claimed.attempt_count
        )
        session.commit()
        reclaimed = service.claim_next_run(session, WORKER_B)

        assert changed == 1
        assert reclaimed is not None and reclaimed.id == run_id
        stored = stored_run(session, run_id)
        assert stored["status"] == "RUNNING"
        assert stored["lease_owner"] == WORKER_B
        assert stored["attempt_count"] == 2


@requires_database
def test_worker_failure_uses_fencing_and_clears_the_lease() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(session, brokerage_id, user_id)
        claimed = service.claim_next_run(session, WORKER_A)
        assert claimed is not None

        changed = repository.fail_run(
            session,
            run_id,
            brokerage_id,
            WORKER_A,
            claimed.attempt_count,
            status="SUPERSEDED",
            failure_code="INPUT_SUPERSEDED",
            failure_message="실행 중 입력 데이터가 변경되어 결과를 반영하지 않았습니다",
        )
        session.commit()

        assert changed == 1
        stored = stored_run(session, run_id)
        assert stored["status"] == "SUPERSEDED"
        assert stored["failure_code"] == "INPUT_SUPERSEDED"
        assert stored["completed_at"] is not None
        assert stored["lease_owner"] is None
        assert stored["lease_expires_at"] is None
        assert service.claim_next_run(session, WORKER_B) is None


@requires_database
def test_wrong_worker_cannot_release_or_fail_a_run() -> None:
    with claim_session() as (session, brokerage_id, user_id):
        run_id = insert_run(session, brokerage_id, user_id)
        claimed = service.claim_next_run(session, WORKER_A)
        assert claimed is not None

        released = repository.release_lease(
            session, run_id, brokerage_id, WORKER_B, claimed.attempt_count
        )
        failed = repository.fail_run(
            session,
            run_id,
            brokerage_id,
            WORKER_B,
            claimed.attempt_count,
            status="FAILED_TERMINAL",
            failure_code="EXECUTION_FAILED",
            failure_message="실행에 실패했습니다. 잠시 후 다시 시도해 주세요",
        )
        session.commit()

        assert released == 0
        assert failed == 0
        stored = stored_run(session, run_id)
        assert stored["status"] == "RUNNING"
        assert stored["lease_owner"] == WORKER_A
