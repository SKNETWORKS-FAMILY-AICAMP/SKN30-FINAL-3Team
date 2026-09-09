"""Shared local/dev management adapter for deterministic example match results."""

from dataclasses import asdict

from sqlalchemy import Engine, text

from synthetic_seed import (
    F3_SEED_DIRECTORY,
    F3_SYNTHETIC_BROKERAGE_NAME,
    SyntheticSeedError,
    model_profile_path,
    read_psql_script,
)

RESULT_VERIFICATION_CHECKS = 12


def complete_match_seed(engine: Engine, model_profile: str) -> dict[str, object]:
    from synthetic_match_results import seed_match_results

    model_profile_path(model_profile)
    with engine.connect() as connection:
        identity = connection.execute(
            text("""SELECT b.id,u.id FROM brokerage b
            JOIN app_user u ON u.brokerage_id=b.id
            WHERE b.name=:name AND u.login_id='f3_synthetic_dev' AND u.is_active"""),
            {"name": F3_SYNTHETIC_BROKERAGE_NAME},
        ).one_or_none()
        if identity is None:
            raise SyntheticSeedError("active synthetic seed identity is required")
        profiles = (
            connection.execute(
                text("""SELECT config_key FROM ai_model_config WHERE brokerage_id=:tenant
            AND is_active AND capability IN ('POSITION_CARD','BROKERAGE_JUDGMENT')"""),
                {"tenant": identity[0]},
            )
            .scalars()
            .all()
        )
        if profiles != [model_profile, model_profile]:
            raise SyntheticSeedError("selected synthetic model profile does not match")
    summary = seed_match_results(engine, int(identity[0]), int(identity[1]))
    with engine.connect() as connection:
        checks = connection.exec_driver_sql(
            read_psql_script(F3_SEED_DIRECTORY / "004_MATCH_RESULTS_VERIFY.sql")
        ).all()
        if len(checks) != RESULT_VERIFICATION_CHECKS or any(row[3] != "PASS" for row in checks):
            raise SyntheticSeedError("synthetic matching result verification failed")
    return {
        "event": "synthetic-match-seed-complete",
        "model_inference": False,
        "brokerage_id": int(identity[0]),
        "user_id": int(identity[1]),
        "login_id": "f3_synthetic_dev",
        "model_profile": model_profile,
        "total_targets": 84,
        "eligible_targets": 81,
        "completed_results": 81,
        "verification_checks": len(checks),
        "generation": asdict(summary),
    }
