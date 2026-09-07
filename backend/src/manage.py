from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from sqlmodel import Session

from core.config import get_config
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
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    config = get_config()

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
