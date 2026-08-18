import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

requires_database = pytest.mark.skipif(
    not os.getenv("TEST_DB_URL"),
    reason="TEST_DB_URL is required for PostgreSQL integration tests",
)

INSERT_PARTY = text(
    "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at, privacy_consent_by)"
    " VALUES (:brokerage_id, 'PERSON', :name, :consent_at, :consent_by)"
)


def seed_brokerage_and_user(session: Session) -> tuple[int, int]:
    brokerage_id = session.execute(
        text("INSERT INTO brokerage (name) VALUES ('동의 검증 사무소') RETURNING id")
    ).scalar_one()
    user_id = session.execute(
        text(
            "INSERT INTO app_user (brokerage_id, login_id, password_hash, display_name, role)"
            " VALUES (:brokerage_id, 'consent-test', 'unused', '검증', 'OWNER') RETURNING id"
        ),
        {"brokerage_id": brokerage_id},
    ).scalar_one()
    return brokerage_id, user_id


@requires_database
def test_party_without_consent_is_stored() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        brokerage_id, _ = seed_brokerage_and_user(session)

        session.execute(
            INSERT_PARTY,
            {
                "brokerage_id": brokerage_id,
                "name": "미동의",
                "consent_at": None,
                "consent_by": None,
            },
        )

        session.rollback()


@requires_database
def test_party_with_complete_consent_is_stored() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        brokerage_id, user_id = seed_brokerage_and_user(session)

        session.execute(
            INSERT_PARTY,
            {
                "brokerage_id": brokerage_id,
                "name": "동의",
                "consent_at": "2026-08-18T09:00:00+09:00",
                "consent_by": user_id,
            },
        )

        session.rollback()


@requires_database
def test_consent_without_recorder_is_rejected() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        brokerage_id, _ = seed_brokerage_and_user(session)

        with pytest.raises(IntegrityError, match="ck_party_privacy_consent_pair"):
            session.execute(
                INSERT_PARTY,
                {
                    "brokerage_id": brokerage_id,
                    "name": "시각만",
                    "consent_at": "2026-08-18T09:00:00+09:00",
                    "consent_by": None,
                },
            )

        session.rollback()


@requires_database
def test_recorder_from_another_brokerage_is_rejected() -> None:
    engine = create_engine(os.environ["TEST_DB_URL"])

    with Session(engine) as session:
        _, user_id = seed_brokerage_and_user(session)
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('다른 사무소') RETURNING id")
        ).scalar_one()

        with pytest.raises(IntegrityError, match="fk_party_privacy_consent_by"):
            session.execute(
                INSERT_PARTY,
                {
                    "brokerage_id": other_brokerage_id,
                    "name": "교차 참조",
                    "consent_at": "2026-08-18T09:00:00+09:00",
                    "consent_by": user_id,
                },
            )

        session.rollback()
