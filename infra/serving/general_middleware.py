"""Expose only authenticated inference and a small disk-status response."""

import hmac
import json
import os
import shutil


class ServingRoutes:
    def __init__(self, app):
        self.app = app
        self.authorization = ("Bearer " + os.environ["VLLM_API_KEY"]).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return await send({"type": "websocket.close", "code": 1008})
        authorizations = [
            v for k, v in scope["headers"] if k.lower() == b"authorization"
        ]
        route = (scope["method"], scope["path"])
        if len(authorizations) != 1 or not hmac.compare_digest(
            authorizations[0], self.authorization
        ):
            status, body = 401, {"error": "unauthorized"}
        elif route in {("GET", "/v1/models"), ("POST", "/v1/chat/completions")}:
            return await self.app(scope, receive, send)
        elif route == ("GET", "/ops/status"):
            usage = shutil.disk_usage(os.environ.get("HF_HOME", "/tmp"))
            status, body = (
                200,
                {"disk_total_bytes": usage.total, "disk_free_bytes": usage.free},
            )
        else:
            status, body = 404, {"error": "not found"}
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(body).encode()})
