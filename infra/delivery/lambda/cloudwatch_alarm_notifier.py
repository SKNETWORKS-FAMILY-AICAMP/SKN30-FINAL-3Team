from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import boto3

DISCORD_CONTENT_LIMIT = 2_000
QUERY_WAIT_SECONDS = 2.0
QUERY_POLL_SECONDS = 0.2
QUERY_WINDOW_MINUTES = 10
REASON_LIMIT = 500

DETAIL_FIELDS = (
    "@timestamp",
    "source",
    "request_id",
    "run_id",
    "status",
    "status_code",
    "failure_stage",
    "attempt",
    "failure_category",
    "error_code",
    "error_type",
    "error_location",
    "terminal_count",
)
DETAIL_LABELS = {
    "@timestamp": "timestamp",
    "source": "source",
    "request_id": "request_id",
    "run_id": "run_id",
    "status": "status",
    "status_code": "status_code",
    "failure_stage": "failure_stage",
    "attempt": "attempt",
    "failure_category": "failure_category",
    "error_code": "error_code",
    "error_type": "error_type",
    "error_location": "error_location",
    "terminal_count": "terminal_count",
}
EXPECTED_EVENTS = {
    "backend": "unhandled_request_error",
    "ai": "ai_terminal_failure",
}

_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d+$")
_SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._:/+\-]+$")
_SAFE_TIMESTAMP_PATTERN = re.compile(r"^[0-9TZ:.,+\- ]+$")
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_INTEGER_PATTERN = re.compile(r"^\d+$")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_secretsmanager: Any | None = None
_logs: Any | None = None


def secret_url() -> str:
    global _secretsmanager
    if _secretsmanager is None:
        _secretsmanager = boto3.client("secretsmanager")
    return str(
        _secretsmanager.get_secret_value(
            SecretId=os.environ["ALARM_DISCORD_SECRET_ARN"]
        )["SecretString"]
    )


def _logs_client() -> Any:
    global _logs
    if _logs is None:
        _logs = boto3.client("logs")
    return _logs


def _single_line(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _truncated(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    return value[: limit - 1] + "…"


def _log_enrichment_failure(code: str) -> None:
    logger.warning("alarm_log_enrichment_failed code=%s", code)


def _alarm_contexts() -> dict[str, dict[str, Any]]:
    raw_contexts = os.environ.get("ALARM_LOG_CONTEXTS_JSON", "")
    try:
        contexts = json.loads(raw_contexts)
    except (json.JSONDecodeError, TypeError):
        _log_enrichment_failure("INVALID_CONTEXT_CONFIG")
        return {}

    if not isinstance(contexts, dict):
        _log_enrichment_failure("INVALID_CONTEXT_CONFIG")
        return {}

    validated: dict[str, dict[str, Any]] = {}
    for alarm_name, context in contexts.items():
        if not isinstance(alarm_name, str) or not isinstance(context, dict):
            _log_enrichment_failure("INVALID_CONTEXT_ENTRY")
            continue

        module = context.get("module")
        event = context.get("event")
        log_group_names = context.get("log_group_names")
        if (
            not isinstance(module, str)
            or not isinstance(event, str)
            or event != EXPECTED_EVENTS.get(module)
            or not isinstance(log_group_names, list)
            or not 1 <= len(log_group_names) <= 2
            or not all(
                isinstance(group, str)
                and group.startswith("/")
                and 1 < len(group) <= 256
                for group in log_group_names
            )
        ):
            _log_enrichment_failure("INVALID_CONTEXT_ENTRY")
            continue

        validated[alarm_name] = {
            "module": module,
            "event": event,
            "log_group_names": tuple(log_group_names),
        }
    return validated


def _alarm_region(message: dict[str, Any]) -> str | None:
    alarm_arn = message.get("AlarmArn")
    alarm_name = message.get("AlarmName")
    account_id = message.get("AWSAccountId")
    if not all(
        isinstance(value, str) and value
        for value in (alarm_arn, alarm_name, account_id)
    ):
        _log_enrichment_failure("INVALID_ALARM_ARN")
        return None

    parts = alarm_arn.split(":", 5)
    if len(parts) != 6:
        _log_enrichment_failure("INVALID_ALARM_ARN")
        return None
    arn, partition, service, region, arn_account_id, resource = parts
    expected_region = os.environ.get("AWS_REGION")
    if (
        arn != "arn"
        or partition != "aws"
        or service != "cloudwatch"
        or not _REGION_PATTERN.fullmatch(region)
        or (expected_region and region != expected_region)
        or arn_account_id != account_id
        or resource != f"alarm:{alarm_name}"
    ):
        _log_enrichment_failure("INVALID_ALARM_ARN")
        return None
    return region


def _state_change_time(message: dict[str, Any]) -> datetime | None:
    raw_value = message.get("StateChangeTime")
    if not isinstance(raw_value, str) or not raw_value:
        _log_enrichment_failure("INVALID_STATE_CHANGE_TIME")
        return None
    normalized = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        _log_enrichment_failure("INVALID_STATE_CHANGE_TIME")
        return None
    if parsed.tzinfo is None:
        _log_enrichment_failure("INVALID_STATE_CHANGE_TIME")
        return None
    return parsed.astimezone(timezone.utc)


def _query_string(event: str) -> str:
    fields = ", ".join(DETAIL_FIELDS)
    return (
        f"fields {fields}\n"
        f'| filter event = "{event}"\n'
        "| sort @timestamp desc\n"
        "| limit 1"
    )


def _console_value(value: Any) -> str:
    if isinstance(value, str):
        return "'" + quote(value, safe="").replace("%", "*")
    if isinstance(value, (tuple, list)):
        return "(" + "".join(f"~{_console_value(item)}" for item in value) + ")"
    return str(value)


def _logs_insights_url(
    region: str,
    log_group_names: tuple[str, ...],
    query: str,
    start_time: datetime,
    end_time: datetime,
) -> str:
    query_parameters = {
        "end": end_time.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "start": start_time.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "timeType": "ABSOLUTE",
        "tz": "UTC",
        "editorString": query,
        "source": log_group_names,
    }
    state = (
        "~("
        + "~".join(
            f"{key}~{_console_value(value)}" for key, value in query_parameters.items()
        )
        + ")"
    )
    encoded_state = quote(state, safe="")
    route = quote(f"?queryDetail={encoded_state}", safe="").replace("%", "$")
    return (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={quote(region, safe='')}#logsV2:logs-insights{route}"
    )


def _alarm_url(region: str, alarm_name: str) -> str:
    return (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={quote(region, safe='')}#alarmsV2:alarm/"
        f"{quote(alarm_name, safe='')}"
    )


def _safe_detail_value(field: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    safe_value = _single_line(value, 180)
    if not safe_value:
        return None
    if field == "@timestamp":
        return safe_value if _SAFE_TIMESTAMP_PATTERN.fullmatch(safe_value) else None
    if field == "request_id" and not _UUID_PATTERN.fullmatch(safe_value):
        return None
    if field in {"run_id", "attempt", "terminal_count", "status_code"}:
        return safe_value if _INTEGER_PATTERN.fullmatch(safe_value) else None
    if not _SAFE_TOKEN_PATTERN.fullmatch(safe_value):
        return None
    return safe_value


def _render_query_result(results: Any) -> str | None:
    if not isinstance(results, list) or not results or not isinstance(results[0], list):
        return None

    allowed_values: dict[str, str] = {}
    for item in results[0]:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if field not in DETAIL_LABELS:
            continue
        safe_value = _safe_detail_value(field, item.get("value"))
        if safe_value is not None:
            allowed_values[field] = safe_value

    lines = [
        f"{DETAIL_LABELS[field]}: {allowed_values[field]}"
        for field in DETAIL_FIELDS
        if field in allowed_values
    ]
    return "\n".join(lines) if lines else None


def _best_effort_stop(query_id: str) -> None:
    try:
        _logs_client().stop_query(queryId=query_id)
    except Exception:  # noqa: BLE001 - enrichment must not trigger SNS retry
        _log_enrichment_failure("QUERY_STOP_FAILED")


def _recent_error(
    context: dict[str, Any],
    start_time: datetime,
    end_time: datetime,
) -> str | None:
    query = _query_string(context["event"])
    deadline = time.monotonic() + QUERY_WAIT_SECONDS
    try:
        response = _logs_client().start_query(
            logGroupNames=list(context["log_group_names"]),
            startTime=int(start_time.timestamp()),
            endTime=int(end_time.timestamp()),
            queryString=query,
            limit=1,
        )
        query_id = response.get("queryId")
        if not isinstance(query_id, str) or not query_id:
            _log_enrichment_failure("QUERY_START_INVALID")
            return None
    except Exception:  # noqa: BLE001 - enrichment must not trigger SNS retry
        _log_enrichment_failure("QUERY_START_FAILED")
        return None

    while True:
        if time.monotonic() >= deadline:
            _best_effort_stop(query_id)
            _log_enrichment_failure("QUERY_WAIT_TIMEOUT")
            return None
        try:
            result = _logs_client().get_query_results(queryId=query_id)
        except Exception:  # noqa: BLE001 - enrichment must not trigger SNS retry
            _best_effort_stop(query_id)
            _log_enrichment_failure("QUERY_RESULT_FAILED")
            return None

        status = result.get("status")
        if status == "Complete":
            rendered = _render_query_result(result.get("results"))
            if rendered is None:
                _log_enrichment_failure("QUERY_NO_SAFE_RESULT")
            return rendered
        if status in {"Failed", "Cancelled", "Timeout", "Unknown"}:
            _log_enrichment_failure("QUERY_NOT_COMPLETED")
            return None
        if status not in {"Scheduled", "Running"}:
            _best_effort_stop(query_id)
            _log_enrichment_failure("QUERY_STATUS_INVALID")
            return None

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            continue
        time.sleep(min(QUERY_POLL_SECONDS, remaining))


def _fit_section(prefix: str, value: str, available: int, maximum: int) -> str:
    if available <= len(prefix):
        return ""
    value_limit = min(maximum, available - len(prefix))
    return prefix + _truncated(value, value_limit)


def alarm_message(
    message: Any,
    *,
    module: str = "infra",
    changed_at: datetime | None = None,
    alarm_url: str | None = None,
    logs_url: str | None = None,
    runbook_url: str | None = None,
    detail: str | None = None,
) -> str | None:
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
    safe_module = module if module in {"backend", "ai", "infra"} else "infra"
    safe_reason = " ".join(reason.split())
    safe_changed_at = (
        changed_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if changed_at is not None
        else "unavailable"
    )
    content = (
        "**CloudWatch Alarm**\n"
        f"alarm name: {safe_name}\n"
        f"module: {safe_module}\n"
        f"state: {safe_state}\n"
        f"changed at: {safe_changed_at}"
    )

    link_parts = []
    if alarm_url:
        link_parts.append(f"[Alarm]({alarm_url})")
    if logs_url:
        link_parts.append(f"[Logs Insights]({logs_url})")
    if runbook_url:
        link_parts.append(f"[Runbook]({runbook_url})")
    if link_parts:
        links_section = "\nlinks: " + " · ".join(link_parts)
        if len(content) + len(links_section) <= DISCORD_CONTENT_LIMIT:
            content += links_section
        else:
            _log_enrichment_failure("MESSAGE_LINK_BUDGET_EXCEEDED")

    reason_section = _fit_section(
        "\nreason: ",
        safe_reason,
        DISCORD_CONTENT_LIMIT - len(content),
        REASON_LIMIT,
    )
    content += reason_section

    if detail:
        detail_prefix = (
            "\nrecent matching error (near alarm time; not confirmed as root cause):\n"
        )
        detail_section = _fit_section(
            detail_prefix,
            detail,
            DISCORD_CONTENT_LIMIT - len(content),
            DISCORD_CONTENT_LIMIT,
        )
        content += detail_section
    return content


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


def handler(event: Any, _context: Any) -> None:
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not isinstance(records, list):
        return
    contexts = _alarm_contexts()
    runbook_url = os.environ.get("ALARM_RUNBOOK_URL")
    for record in records:
        message = _message_from_record(record)
        if message is None:
            continue

        alarm_name = message.get("AlarmName")
        context = contexts.get(alarm_name) if isinstance(alarm_name, str) else None
        module = context["module"] if context is not None else "infra"
        region = _alarm_region(message)
        changed_at = _state_change_time(message)

        alarm_link = None
        logs_link = None
        detail = None
        if region is not None and isinstance(alarm_name, str):
            alarm_link = _alarm_url(region, alarm_name)
        if region is not None and changed_at is not None and context is not None:
            start_time = changed_at - timedelta(minutes=QUERY_WINDOW_MINUTES)
            end_time = changed_at + timedelta(minutes=QUERY_WINDOW_MINUTES)
            query = _query_string(context["event"])
            logs_link = _logs_insights_url(
                region,
                context["log_group_names"],
                query,
                start_time,
                end_time,
            )
            if message.get("NewStateValue") == "ALARM":
                detail = _recent_error(context, start_time, end_time)

        content = alarm_message(
            message,
            module=module,
            changed_at=changed_at,
            alarm_url=alarm_link,
            logs_url=logs_link,
            runbook_url=runbook_url if region is not None else None,
            detail=detail,
        )
        if content is not None:
            _send(content)
