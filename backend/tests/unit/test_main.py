from fastapi.testclient import TestClient

from main import create_app


class FakeF2Runtime:
    def __init__(self) -> None:
        self.pipeline = object()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_f2_runtime_is_always_started_and_closed(make_config) -> None:
    runtime = FakeF2Runtime()
    app = create_app(
        config=make_config(),
        readiness_probe=lambda request: True,
        f2_runtime_factory=lambda: runtime,  # type: ignore[arg-type, return-value]
    )

    with TestClient(app):
        assert app.state.f2_pipeline is runtime.pipeline
        assert runtime.closed is False

    assert runtime.closed is True
