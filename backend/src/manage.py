from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from sqlmodel import Session

from core.config import get_config
from domain.agent_execution.backfill import backfill_position_cards, position_card_coverage
from domain.authentication.commands import (
    create_development_user,
    purge_expired_sessions,
)
from domain.authentication.models import UserRole
from domain.engine import create_database_engine
from domain.property_ledger.commands import (
    clear_sample_ledger,
    has_sample_ledger,
    seed_sample_ledger,
)
from synthetic_seed import F3_MODEL_PROFILES, SyntheticSeedError, seed_f3_synthetic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backend management commands")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_user = subcommands.add_parser("create-development-user")
    create_user.add_argument("--brokerage-name", required=True)
    create_user.add_argument("--login-id", required=True)
    create_user.add_argument("--display-name", required=True)
    create_user.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.OWNER.value,
    )

    subcommands.add_parser("purge-expired-sessions")

    seed = subcommands.add_parser("seed-sample-ledger")
    seed.add_argument("--brokerage-id", type=int, required=True)
    seed.add_argument("--user-id", type=int, required=True)
    seed.add_argument(
        "--reset",
        action="store_true",
        help="해당 사무소의 기존 장부 데이터를 지우고 다시 만든다",
    )

    f3_seed = subcommands.add_parser(
        "seed-f3-synthetic",
        help="로컬 loopback DB의 F3 합성 seed를 초기화하고 검증한다",
    )
    backfill = subcommands.add_parser(
        "backfill-position-cards",
        help="활성 매물·손님의 포지션 카드를 미리 만들도록 F3 실행을 접수한다",
    )
    backfill.add_argument("--brokerage-id", type=int, required=True)
    backfill.add_argument("--user-id", type=int, required=True, help="실행 요청자로 기록할 사용자")
    backfill.add_argument("--limit", type=int, help="한 번에 접수할 앵커 수. 나눠서 돌릴 때 쓴다")
    backfill.add_argument("--dry-run", action="store_true", help="접수하지 않고 대상 수만 센다")

    f3_seed.add_argument(
        "--confirm-reset",
        action="store_true",
        help="F3_SYNTHETIC 합성 사무소의 기존 장부와 실행 결과 삭제를 확인한다",
    )
    f3_seed.add_argument(
        "--model-profile",
        choices=F3_MODEL_PROFILES,
        required=True,
        help="허용된 Provider·모델·endpoint 설정 프로필",
    )
    subcommands.add_parser("smoke-general", help="합성 입력으로 범용 GPU의 포지션 카드·판정 검증")
    activate = subcommands.add_parser(
        "activate-general-qwen", help="장부·실행 이력 보존, 범용 모델 설정만 전환"
    )
    activate.add_argument("--brokerage-id", type=int, required=True)
    activate.add_argument("--apply", action="store_true")
    activate.add_argument("--shared-dev", action="store_true")
    activate.add_argument("--workloads-stopped-confirmed", action="store_true")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    config = get_config()

    if arguments.command in {"smoke-general", "activate-general-qwen"}:
        from brokerage_ai.smoke import smoke_general

        from core.config import load_ai_config
        from general_model import activate_general, general_route

        try:
            if arguments.command == "smoke-general":
                asyncio.run(
                    smoke_general(load_ai_config(config.app.environment.value), general_route())
                )
                print("general synthetic workflows: OK")
            else:
                activate_general(
                    config,
                    arguments.brokerage_id,
                    apply=arguments.apply,
                    shared_dev=arguments.shared_dev,
                    workloads_stopped=arguments.workloads_stopped_confirmed,
                )
        except Exception:
            raise SystemExit(
                "General model operation failed; check endpoint readiness, credentials "
                "and queued runs. Sensitive details withheld."
            ) from None
        return
    if arguments.command == "seed-f3-synthetic":
        try:
            result = seed_f3_synthetic(
                config,
                confirm_reset=arguments.confirm_reset,
                model_profile=arguments.model_profile,
            )
        except SyntheticSeedError as error:
            raise SystemExit(str(error)) from None
        print(json.dumps(asdict(result), ensure_ascii=False))
        return

    engine = create_database_engine(config)

    with Session(engine) as session:
        if arguments.command == "create-development-user":
            user = create_development_user(
                session,
                config,
                brokerage_name=arguments.brokerage_name,
                login_id=arguments.login_id,
                display_name=arguments.display_name,
                role=UserRole(arguments.role),
            )
            print(
                json.dumps(
                    {
                        "id": user.id,
                        "brokerage_id": user.brokerage_id,
                        "login_id": user.login_id,
                        "role": user.role,
                    },
                    ensure_ascii=False,
                )
            )
        elif arguments.command == "purge-expired-sessions":
            print(json.dumps({"purged": purge_expired_sessions(session)}))
        elif arguments.command == "backfill-position-cards":
            before = position_card_coverage(session, arguments.brokerage_id)
            result = backfill_position_cards(
                session,
                brokerage_id=arguments.brokerage_id,
                requested_by=arguments.user_id,
                limit=arguments.limit,
                dry_run=arguments.dry_run,
            )
            print(
                json.dumps(
                    {
                        **asdict(result),
                        "coverage_before": before,
                        "next": "Worker 를 실행하면 접수된 앵커의 카드를 만든다",
                    },
                    ensure_ascii=False,
                )
            )
        elif arguments.command == "seed-sample-ledger":
            if has_sample_ledger(session, arguments.brokerage_id):
                if not arguments.reset:
                    raise SystemExit(
                        "이미 장부 데이터가 있습니다. 지우고 다시 만들려면 --reset을 사용하세요."
                    )
                clear_sample_ledger(session, arguments.brokerage_id)
            counts = seed_sample_ledger(
                session,
                config,
                brokerage_id=arguments.brokerage_id,
                user_id=arguments.user_id,
            )
            print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
