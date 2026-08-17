import pytest

from core.errors import AuthenticationError
from domain.authentication.models import (
    AuthenticationContext,
    CurrentUser,
    UserRole,
)
from domain.authentication.service import hash_token, validate_csrf


def context_for(csrf_token: str) -> AuthenticationContext:
    return AuthenticationContext(
        user=CurrentUser(
            id=1,
            brokerage_id=1,
            login_id="developer",
            display_name="Developer",
            role=UserRole.OWNER,
        ),
        session_id=1,
        csrf_token_hash=hash_token(csrf_token),
    )


def test_hash_token_is_deterministic_without_storing_plaintext() -> None:
    digest = hash_token("secret-session-token")

    assert digest == hash_token("secret-session-token")
    assert digest != "secret-session-token"
    assert len(digest) == 64


def test_valid_csrf_token_is_accepted() -> None:
    validate_csrf(context_for("csrf-token"), "csrf-token")


def test_invalid_csrf_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError) as error:
        validate_csrf(context_for("csrf-token"), "wrong-token")

    assert error.value.code == "INVALID_CSRF_TOKEN"
