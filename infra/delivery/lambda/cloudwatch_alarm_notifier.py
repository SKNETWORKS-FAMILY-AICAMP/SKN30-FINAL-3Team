from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import boto3

DISCORD_CONTENT_LIMIT = 2_000
_secretsmanager: Any | None = None


def secret_url() -> str:
    global _secretsmanager
    if _secretsmanager is None:
        _secretsmanager = boto3.client("secretsmanager")
    return str(
        _secretsmanager.get_secret_value(
            SecretId=os.environ["ALARM_DISCORD_SECRET_ARN"]
        )["SecretString"]
    )


def _single_line(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def alarm_message(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None

    alarm_name = message.get("AlarmName")
    state = message.get("NewStateValue")
    reason = message.get("NewStateReason")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (alarm_name, state, reason)
    ):
        return None

    safe_name = _single_line(alarm_name, 255)
    safe_state = _single_line(state, 64)
    safe_reason = " ".join(reason.split())
    prefix = (
        "**CloudWatch Alarm**\n"
        f"alarm name: {safe_name}\n"
        f"state: {safe_state}\n"
        "reason: "
    )
    available = DISCORD_CONTENT_LIMIT - len(prefix)
    if len(safe_reason) > available:
        safe_reason = safe_reason[: max(available - 1, 0)] + "…"
    return prefix + safe_reason


def _message_from_record(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    sns = record.get("Sns")
    if not isinstance(sns, dict):
        return None
    raw_message = sns.get("Message")
    if not isinstance(raw_message, str):
        return None
    try:
        message = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        return None
    return message if isinstance(message, dict) else None


def _send(content: str) -> None:
    request = urllib.request.Request(
        secret_url(),
        data=json.dumps(
            {
                "content": content,
                "allowed_mentions": {"parse": []},
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; SKN30-CloudWatchAlarm/1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"Discord returned HTTP {response.status}")


def handler(event: dict[str, Any], _context: Any) -> None:
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not isinstance(records, list):
        return

    for record in records:
        message = _message_from_record(record)
        content = alarm_message(message)
        if content is not None:
            _send(content)
