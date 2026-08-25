from __future__ import annotations

import uvicorn

from core.config import Config, get_config


def serve(config: Config | None = None) -> None:
    resolved_config = config or get_config()
    uvicorn.run(
        "main:app",
        host=resolved_config.app.host,
        port=resolved_config.app.port,
    )


if __name__ == "__main__":
    serve()
