from typing import cast

import pytest
from sqlmodel import Session

from core.errors import ConfigurationError
from domain.authentication.commands import create_development_user
from domain.authentication.models import UserRole
from domain.property_ledger.commands import require_local


def test_development_account_creation_remains_local_only(make_config) -> None:
    config = make_config({"APP_ENV": "dev", "DB_TARGET": "development"})

    with pytest.raises(ConfigurationError, match="only be created in local"):
        create_development_user(
            cast(Session, object()),
            config,
            "개발 중개사무소",
            "developer",
            "Developer",
            UserRole.OWNER,
        )


def test_sample_ledger_seeding_remains_local_only(make_config) -> None:
    config = make_config({"APP_ENV": "dev", "DB_TARGET": "development"})

    with pytest.raises(ConfigurationError, match="only be seeded in local"):
        require_local(config)
