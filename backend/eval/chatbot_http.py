"""Real Luna + localhost HTTP/SSE + isolated PostgreSQL latency and restore evaluation.

Requires TEST_DB_URL on loopback, an account with CREATE DATABASE, and AI_OPENAI_API_KEY.
Never targets a shared database. The temporary database is removed after evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import socket
import sys
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import uvicorn
from sqlalchemy import create_engine, text
from yoyo import get_backend, read_migrations

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.config import bind_config  # noqa: E402
from main import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
QUERIES = [
    ("매매 매물 보여줘", "properties", 25),
    ("매매 15억 이하 매물 찾아줘", "properties", 15),
    ("매매 5억 미만 매물 보여줘", "properties", 4),
    ("매매 20억 이상 매물 찾아줘", "properties", 6),
    ("매매 매물을 가격 낮은 순으로 보여줘", "properties", 25),
    ("전세 매물 보여줘", "properties", 0),
    ("전세를 찾는 손님 보여줘", "buyers", 5),
    ("매매를 찾는 손님 보여줘", "buyers", 0),
    ("진행 중인 구입장 보여줘", "buyers", 5),
    ("오늘 캘린더 일정 보여줘", "agenda", 25),
    ("이번 달 캘린더 일정 보여줘", "agenda", 25),
    ("내일 캘린더 일정 보여줘", "agenda", 0),
]


def replace_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def seed(url: str) -> int:
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            brokerage = db.execute(
                text("INSERT INTO brokerage(name) VALUES ('F4 HTTP 합성 평가') RETURNING id")
            ).scalar_one()
            db.execute(
                text(
                    "INSERT INTO app_user(brokerage_id,login_id,password_hash,"
                    "display_name,role) VALUES (:b,'chatbot-http-eval','unused','합성 평가',"
                    "'OWNER')"
                ),
                {"b": brokerage},
            )
            complex_id = db.execute(
                text(
                    "INSERT INTO property_complex(brokerage_id,name) "
                    "VALUES (:b,'A단지') RETURNING id"
                ),
                {"b": brokerage},
            ).scalar_one()
            for index in range(1, 26):
                unit = db.execute(
                    text(
                        "INSERT INTO property_unit(brokerage_id,complex_id,unit_number,"
                        "exclusive_area_sqm,supply_area_sqm) VALUES (:b,:c,:n,84,109) "
                        "RETURNING id"
                    ),
                    {"b": brokerage, "c": complex_id, "n": str(index)},
                ).scalar_one()
                db.execute(
                    text(
                        "INSERT INTO property_listing(brokerage_id,unit_id,is_sale_available,"
                        "sale_price) VALUES (:b,:u,TRUE,:p)"
                    ),
                    {"b": brokerage, "u": unit, "p": index * 100_000_000},
                )
                db.execute(
                    text(
                        "INSERT INTO calendar_event(brokerage_id,title,event_date) VALUES "
                        "(:b,:title,(now() AT TIME ZONE 'Asia/Seoul')::date)"
                    ),
                    {"b": brokerage, "title": f"합성 일정 {index}"},
                )
            for index in range(5):
                party = db.execute(
                    text(
                        "INSERT INTO party(brokerage_id,party_type,name) VALUES (:b,'PERSON',"
                        ":n) RETURNING id"
                    ),
                    {"b": brokerage, "n": f"합성 의뢰 {index}"},
                ).scalar_one()
                db.execute(
                    text(
                        "INSERT INTO property_requirement(brokerage_id,party_id,demand_type,"
                        "min_budget_amount,max_budget_amount) VALUES (:b,:p,'전세',"
                        "100000000,500000000)"
                    ),
                    {"b": brokerage, "p": party},
                )
            db.execute(
                text(
                    "INSERT INTO ai_model_config(brokerage_id,capability,config_key,"
                    "config_version,provider,model_name) VALUES (:b,'CHATBOT',"
                    "'http-eval-luna',1,'openai','gpt-5.6-luna')"
                ),
                {"b": brokerage},
            )
            return brokerage
    finally:
        engine.dispose()


def p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


async def measure(url: str, brokerage: int, rounds: int) -> dict:
    config = bind_config(
        {
            "APP_ENV": "local",
            "DB_TARGET": "development",
            "DB_URL": url,
            "CHATBOT_ENABLED": "true",
            "AUTH_DEVELOPMENT_ENABLED": "true",
            "AUTH_DEVELOPMENT_BROKERAGE_ID": str(brokerage),
            "AUTH_DEVELOPMENT_LOGIN_ID": "chatbot-http-eval",
            "HTTP_ALLOWED_HOSTS": '["127.0.0.1"]',
            "LOG_LEVEL": "WARNING",
        }
    )
    app = create_app(config)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.05)
        if not server.started:
            raise RuntimeError("local server startup failed")
        async with httpx.AsyncClient(base_url=origin, timeout=70) as client:
            auth = await client.post("/api/v1/auth/development-session")
            auth.raise_for_status()
            client.headers["X-CSRF-Token"] = auth.json()["csrf_token"]
            root = "/api/v1/chatbot"
            conversation = (await client.post(f"{root}/conversations")).json()
            rows = []
            # First sample is a real warm-up, excluded from p95.
            for index, (question, kind, total) in enumerate([QUERIES[0]] + QUERIES * rounds):
                current = (await client.get(f"{root}/conversation")).json()["conversation"]
                await client.patch(
                    f"{root}/conversations/{conversation['id']}/filters",
                    json={"expected_version": current["state_version"]},
                )
                current = (await client.get(f"{root}/conversation")).json()["conversation"]
                started = perf_counter()
                accepted = await client.post(
                    f"{root}/conversations/{conversation['id']}/requests",
                    json={
                        "question": question,
                        "client_request_id": str(uuid4()),
                        "expected_version": current["state_version"],
                    },
                )
                accepted.raise_for_status()
                request_id = accepted.json()["id"]
                first = None
                terminal = None
                async with client.stream("GET", f"{root}/requests/{request_id}/events") as stream:
                    stream.raise_for_status()
                    async for line in stream.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        event = json.loads(line[6:])
                        first = first if first is not None else (perf_counter() - started) * 1000
                        terminal = event["payload"]
                elapsed = (perf_counter() - started) * 1000
                restored = (await client.get(f"{root}/requests/{request_id}")).json()
                payload = (restored.get("answer") or {}).get("result_payload") or {}
                row = {
                    "case": index,
                    "warmup": index == 0,
                    "first_progress_ms": first,
                    "elapsed_ms": elapsed,
                    "status": restored["status"],
                    "result_kind": payload.get("kind"),
                    "total": payload.get("total"),
                    "passed": restored["status"] == "COMPLETED"
                    and payload.get("kind") == kind
                    and payload.get("total") == total,
                    "restored": terminal == restored,
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
            delete = await client.delete(f"{root}/conversations/{conversation['id']}")
            delete.raise_for_status()
            deleted = (await client.get(f"{root}/conversation")).json()["conversation"] is None
            measured = rows[1:]
            first_p95 = p95([r["first_progress_ms"] for r in measured])
            total_p95 = p95([r["elapsed_ms"] for r in measured])
            return {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "rounds": rounds,
                "samples": len(measured),
                "first_progress_p95_ms": first_p95,
                "completion_p95_ms": total_p95,
                "deleted": deleted,
                "passed": deleted
                and all(r["passed"] and r["restored"] for r in measured)
                and first_p95 <= 1000
                and total_p95 <= 30000,
                "rows": rows,
            }
    finally:
        server.should_exit = True
        await task
        sock.close()
        app.state.db_engine.dispose()


def main() -> None:
    logging.getLogger().setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", type=int, default=3, choices=range(1, 4))
    args = parser.parse_args()
    base = os.environ["TEST_DB_URL"]
    if urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Only a loopback test PostgreSQL server is permitted")
    if not os.environ.get("AI_OPENAI_API_KEY"):
        raise SystemExit("AI_OPENAI_API_KEY is required")
    database = f"chatbot_http_{uuid4().hex[:12]}"
    admin = create_engine(replace_database(base, "postgres"), isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
        url = replace_database(base, database)
        migration = get_backend(url)
        with migration.lock():
            migration.apply_migrations(
                migration.to_apply(read_migrations(str(ROOT / "docs/db/migrate")))
            )
        os.environ["AI_F2_PROVIDER_STATUS"] = "offline"
        report = asyncio.run(measure(url, seed(url), args.rounds))
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
        if not report["passed"]:
            raise SystemExit(1)
    finally:
        if created:
            with admin.connect() as db:
                db.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE "
                        "datname=:name AND pid<>pg_backend_pid()"
                    ),
                    {"name": database},
                )
                db.execute(text(f'DROP DATABASE "{database}"'))
        admin.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(
            f"HTTP evaluation failed: {type(error).__name__}; sensitive details withheld"
        ) from None
