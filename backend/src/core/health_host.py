from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

HEALTH_PATHS = frozenset({"/health/live", "/health/ready"})


class HealthAwareTrustedHostMiddleware:
    """Allow ALB target Host values only for the two health endpoints."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.trusted_hosts = TrustedHostMiddleware(app, allowed_hosts=list(allowed_hosts))

    @staticmethod
    def _has_private_ip_host(scope: Scope) -> bool:
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin-1").split(":", 1)[0]
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_private or address.is_loopback or address.is_link_local

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("path") in HEALTH_PATHS
            and self._has_private_ip_host(scope)
        ):
            await self.app(scope, receive, send)
            return
        await self.trusted_hosts(scope, receive, send)
