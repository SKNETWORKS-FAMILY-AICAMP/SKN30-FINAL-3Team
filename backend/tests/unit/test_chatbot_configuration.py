import pytest
from pydantic import ValidationError

from conftest import config_values
from core.config import bind_config


def test_chatbot_is_opt_in_and_execution_is_bounded() -> None:
    assert bind_config(config_values()).chatbot.enabled is False
    config = bind_config(config_values(CHATBOT_ENABLED="true"))
    assert config.chatbot.enabled
    assert config.chatbot.request_timeout_seconds == 60
    assert config.chatbot.max_concurrent_requests == 1


@pytest.mark.parametrize("timeout", ["0", "61"])
def test_chatbot_deadline_cannot_be_disabled_or_extended(timeout: str) -> None:
    with pytest.raises(ValidationError):
        bind_config(config_values(CHATBOT_REQUEST_TIMEOUT_SECONDS=timeout))


def test_synthetic_chatbot_cannot_be_enabled_in_production() -> None:
    with pytest.raises(ValidationError, match="synthetic"):
        bind_config(config_values(APP_ENV="prod", DB_TARGET="production", CHATBOT_ENABLED="true"))
