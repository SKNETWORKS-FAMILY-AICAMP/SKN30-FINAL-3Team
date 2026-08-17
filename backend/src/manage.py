from __future__ import annotations

import argparse
import json

from sqlmodel import Session

from core.config import get_config
from domain.authentication.commands import (
    create_development_user,
    purge_expired_sessions,
)
from domain.authentication.models import UserRole
from domain.engine import create_database_engine


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
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    config = get_config()
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


if __name__ == "__main__":
    main()
