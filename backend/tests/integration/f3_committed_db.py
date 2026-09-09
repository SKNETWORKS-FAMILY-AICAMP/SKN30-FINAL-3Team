"""Real-commit F3 test sessions and cleanup scoped to synthetic brokerages.

Do not wrap these sessions in an outer rollback: commit visibility, lease fencing,
and concurrent connections are part of the behavior under test.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

CREATED_BROKERAGES: list[int] = []

_CLEANUP_ORDER = (
    "DELETE FROM match_candidate_evidence WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM match_candidate_evaluation WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM match_evaluation WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM negotiation_position_evidence WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM negotiation_position_price WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM negotiation_position_analysis WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM agent_run WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM client_interaction WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_listing WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_unit_party_relation WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_requirement_complex WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_requirement WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM party_contact WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM party WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_unit WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM property_complex WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM ai_model_config WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM app_user WHERE brokerage_id = ANY(:ids)",
    "DELETE FROM brokerage WHERE id = ANY(:ids)",
)


@pytest.fixture(autouse=True)
def remove_committed_rows() -> Iterator[None]:
    CREATED_BROKERAGES.clear()
    yield
    if not CREATED_BROKERAGES or not os.getenv("TEST_DB_URL"):
        return
    engine = create_engine(os.environ["TEST_DB_URL"])
    with Session(engine) as session:
        for statement in _CLEANUP_ORDER:
            session.execute(text(statement), {"ids": list(CREATED_BROKERAGES)})
        session.commit()
    engine.dispose()
    CREATED_BROKERAGES.clear()


@contextmanager
def db_session() -> Iterator[Session]:
    engine = create_engine(os.environ["TEST_DB_URL"])
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
