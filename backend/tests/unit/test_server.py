from unittest.mock import patch

from conftest import config_values
from core.config import bind_config
from server import serve


def test_server_uses_configured_nondefault_listener() -> None:
    config = bind_config(config_values(APP_HOST="0.0.0.0", APP_PORT="8123"))

    with patch("server.uvicorn.run") as run:
        serve(config)

    run.assert_called_once_with("main:app", host="0.0.0.0", port=8123)
