from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location("chatbot_evaluate", ROOT / "eval/chatbot/evaluate.py")
assert SPEC and SPEC.loader
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


def test_fixture_covers_agreed_groups_and_clarification_recovery():
    fixture = json.loads((ROOT / "eval/chatbot/cases.json").read_text())
    assert fixture["synthetic_only"] is True
    cases = fixture["cases"]
    assert Counter(case["group"] for case in cases) == {
        "basic": 30,
        "units": 10,
        "multi": 10,
        "ambiguous": 10,
        "attack": 20,
    }
    assert len({case["id"] for case in cases}) == 80
    recovery = next(case for case in cases if case["id"] == "multi-10")
    assert recovery["history"][-1]["answer_summary"].startswith("clarification")


def test_scoring_rejects_unrequested_conditions_and_accepts_preserved_filters():
    case = {"expected": {"tool": "buyers", "filters": {"area_basis": "exclusive"}}}
    actual = {
        "tool": "buyers",
        "mode": "replace",
        "filters": {
            "area_basis": "exclusive",
            "transaction_type": "SALE",
        },
    }
    assert not EVAL.intent_matches(actual, case)
    case = {
        "active_filters": {"tool": "properties", "price_expression": "5억 이하"},
        "expected": {"tool": "properties", "mode": "refine", "filters": {"sort": "price_asc"}},
    }
    actual = {
        "tool": "properties",
        "mode": "refine",
        "filters": {
            "price_expression": "5억 이하",
            "sort": "price_asc",
        },
    }
    assert EVAL.intent_matches(actual, case)
    actual["filters"]["price_expression"] = "8억 이하"
    assert not EVAL.intent_matches(actual, case)


def test_p95_uses_nearest_rank_and_empty_samples_remain_unavailable():
    assert EVAL.percentile([]) is None
    assert EVAL.percentile(list(range(1, 21))) == 19


def test_explicit_recent_sort_cannot_be_omitted():
    case = {"expected": {"tool": "buyers", "filters": {"sort": "recent"}}}
    actual = {"tool": "buyers", "mode": "replace", "filters": {}}
    assert not EVAL.intent_matches(actual, case)
    actual["filters"]["sort"] = "recent"
    assert EVAL.intent_matches(actual, case)


def test_refine_price_desc_to_recent_requires_actual_sort_change():
    case = {
        "active_filters": {"tool": "properties", "sort": "price_desc"},
        "expected": {"tool": "properties", "mode": "refine", "filters": {"sort": "recent"}},
    }
    actual = {"tool": "properties", "mode": "refine", "filters": {}}
    assert not EVAL.intent_matches(actual, case)
    actual["filters"]["sort"] = "price_desc"
    assert not EVAL.intent_matches(actual, case)
    actual["filters"]["sort"] = "recent"
    assert EVAL.intent_matches(actual, case)


def test_unrequested_recent_sort_is_not_silently_removed():
    case = {"expected": {"tool": "properties", "filters": {}}}
    actual = {"tool": "properties", "mode": "replace", "filters": {"sort": "recent"}}
    assert not EVAL.intent_matches(actual, case)


def test_aggregation_preserves_historical_verdicts_without_rescoring():
    # The old scorer incorrectly accepted omission of an explicit recent sort.
    historical = {"tool": "buyers", "mode": "replace", "filters": {}}
    case = {"expected": {"tool": "buyers", "filters": {"sort": "recent"}}}
    assert not EVAL.intent_matches(historical, case)
    report = EVAL.summarize(
        [{"group": "basic", "passed": True, "elapsed_ms": 1, "actual": historical}]
    )
    assert report["supported_accuracy"] == 1


@pytest.mark.parametrize("selected", ["", "missing-01", "basic-01,missing-01", "basic-01,"])
def test_invalid_diagnostic_selection_fails_before_provider_initialization(selected):
    with pytest.raises(ValueError):
        EVAL.select_cases([{"id": "basic-01"}], selected)


def test_ambiguity_is_scored_separately_even_when_supported_queries_all_pass():
    rows = [
        {"group": "basic", "passed": True, "elapsed_ms": 1},
        {"group": "multi", "passed": True, "elapsed_ms": 1},
        {"group": "ambiguous", "passed": False, "elapsed_ms": 1},
    ]
    summary = EVAL.summarize(rows)
    assert summary["supported_accuracy"] == 1
    assert summary["ambiguous_unsupported_accuracy"] == 0


def arguments(tmp_path, **overrides):
    from types import SimpleNamespace

    return SimpleNamespace(
        **{
            "cases": ROOT / "eval/chatbot/cases.json",
            "case_ids": "basic-01",
            "rounds": 1,
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "endpoint_alias": None,
            "runtime_label": None,
            "artifact_revision": None,
            "artifact_sha256": None,
            "output": str(tmp_path / "nested/report.json"),
            "environment": "local",
            **overrides,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stage", ["initialization", "warmup"])
async def test_early_failure_keeps_sanitized_durable_evidence(tmp_path, monkeypatch, failed_stage):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    @asynccontextmanager
    async def runtime(_):
        if failed_stage == "initialization":
            raise RuntimeError("sensitive endpoint details")
        yield SimpleNamespace(
            providers=SimpleNamespace(get_llm=lambda *_: SimpleNamespace(kind="openai"))
        )

    class FailingWorkflow:
        def __init__(self, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            raise TimeoutError("sensitive endpoint details")

    monkeypatch.setattr(EVAL, "load_ai_config", lambda _: object())
    monkeypatch.setattr(EVAL, "create_ai_runtime", runtime)
    monkeypatch.setattr(EVAL, "ChatbotWorkflow", FailingWorkflow)
    args = arguments(tmp_path)
    with pytest.raises((RuntimeError, TimeoutError)):
        await EVAL.evaluate(args)
    report_text = Path(args.output).read_text()
    report = json.loads(report_text)
    assert report["status"] == "FAILED"
    assert report["stage"] == failed_stage
    assert report["rows"] == []
    assert report["warmup_ms"] is None
    assert "sensitive" not in report_text
    assert not Path(args.output + ".tmp").exists()


def test_profile_loading_pins_route_and_keeps_expected_weights_separate(tmp_path):
    import hashlib

    profile = {
        "model": "Qwen/Qwen3-14B-AWQ",
        "revision": "a" * 40,
        "runtime_image": "vllm/vllm-openai@sha256:" + "b" * 64,
        "runtime_version": "0.28.0",
        "weights": [{"name": "weights", "sha256": "c" * 64}],
    }
    source = tmp_path / "profiles.json"
    source.write_text(json.dumps({"schema_version": 1, "profiles": {"qwen3-14b-awq": profile}}))
    args = arguments(tmp_path, model_profile="qwen3-14b-awq", profiles_file=source)
    provenance = EVAL.apply_profile(args)
    assert args.model == profile["model"]
    assert args.provider == "vllm"
    assert args.endpoint_alias == "general-dev-gpu"
    assert args.runtime_image == profile["runtime_image"]
    assert provenance["profiles_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert args.artifact_sha256 is None  # Expected HF inventory cannot attest to loaded bytes.


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_revision", "main"),
        ("artifact_sha256", "unknown"),
        ("runtime_image", "vllm/vllm-openai:latest"),
        ("deployment_image", "ghcr.io/example/general-serving:latest"),
    ],
)
def test_self_hosted_provenance_rejects_unpinned_values(field, value):
    provenance = {
        "route": {"provider": "vllm"},
        "runtime_label": "0.28.0",
        "artifact_revision": "a" * 40,
        "artifact_sha256": "b" * 64,
        "runtime_image": "vllm/vllm-openai@sha256:" + "c" * 64,
        "deployment_image": "ghcr.io/example/general-serving@sha256:" + "d" * 64,
    }
    provenance[field] = value
    with pytest.raises(ValueError):
        EVAL.validate_self_hosted_provenance(provenance)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [None, "model", "revision", "artifact_sha256", "runtime_version", "runtime_image", "profile"],
)
async def test_endpoint_attestation_rejects_profile_drift_without_leaking_url(mismatch):
    from types import SimpleNamespace

    import httpx
    from pydantic import SecretStr

    metadata = {
        "model": "Qwen/test",
        "revision": "a" * 40,
        "artifact_sha256": "b" * 64,
        "runtime_version": "0.28.0",
        "runtime_image": "vllm/vllm-openai@sha256:" + "c" * 64,
        "profile": "test-profile",
    }
    provenance = {
        "route": {
            "model": metadata["model"],
            "provider": "vllm",
            "endpoint_alias": "general-dev-gpu",
        },
        "artifact_revision": metadata["revision"],
        "artifact_sha256": metadata["artifact_sha256"],
        "runtime_label": metadata["runtime_version"],
        "runtime_image": metadata["runtime_image"],
        "model_profile": metadata["profile"],
    }
    if mismatch:
        metadata[mismatch] = "different"

    def reply(request):
        assert request.url.path == "/ops/status"
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        return httpx.Response(200, json={"model": metadata})

    config = SimpleNamespace(
        llm_endpoints=[
            SimpleNamespace(
                alias="general-dev-gpu",
                provider="vllm",
                base_url="https://synthetic.invalid/v1",
                api_key=SecretStr("synthetic-test-key"),
            )
        ]
    )
    if mismatch:
        with pytest.raises(ValueError, match="metadata differs"):
            await EVAL.verify_endpoint(config, provenance, transport=httpx.MockTransport(reply))
    else:
        checked = await EVAL.verify_endpoint(
            config, provenance, transport=httpx.MockTransport(reply)
        )
        assert checked["model"] == "Qwen/test"
        assert "synthetic.invalid" not in json.dumps(checked)


def test_claimed_actual_artifact_hash_must_match_expected_weights():
    provenance = {
        "route": {"provider": "vllm"},
        "runtime_label": "0.28.0",
        "artifact_revision": "a" * 40,
        "artifact_sha256": "b" * 64,
        "expected_weights_manifest_sha256": "d" * 64,
        "runtime_image": "vllm/vllm-openai@sha256:" + "c" * 64,
        "deployment_image": "ghcr.io/example/general-serving@sha256:" + "c" * 64,
    }
    with pytest.raises(ValueError, match="weights manifest"):
        EVAL.validate_self_hosted_provenance(provenance)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stage", ["provenance", "final_provenance", "warmup", "cases"])
async def test_endpoint_failure_and_task_cancellation_preserve_checkpoint(
    tmp_path, monkeypatch, failed_stage
):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from brokerage_ai.chatbot import ChatIntent

    reached = asyncio.Event()
    calls = 0
    checks = 0
    exited = False
    failure = RuntimeError("sensitive endpoint details")
    fixture = json.loads((ROOT / "eval/chatbot/cases.json").read_text())
    expected = {case["question"]: case["expected"] for case in fixture["cases"]}

    @asynccontextmanager
    async def runtime(_):
        nonlocal exited
        try:
            yield SimpleNamespace(
                providers=SimpleNamespace(get_llm=lambda *_: SimpleNamespace(kind="vllm"))
            )
        finally:
            exited = True

    async def endpoint(*_):
        nonlocal checks
        checks += 1
        if (failed_stage == "provenance" and checks == 1) or (
            failed_stage == "final_provenance" and checks == 2
        ):
            raise failure
        return {"model": "synthetic-model"}

    class Workflow:
        def __init__(self, **_):
            pass

        async def run(self, value, **_):
            nonlocal calls
            calls += 1
            if (failed_stage == "warmup" and calls == 1) or (
                failed_stage == "cases" and calls == 3
            ):
                reached.set()
                await asyncio.Event().wait()
            return SimpleNamespace(
                intent=ChatIntent.model_validate(
                    expected.get(value.question, {"tool": "help", "filters": {}})
                ),
                model_calls=1,
                diagnostics=None,
            )

    monkeypatch.setattr(EVAL, "load_ai_config", lambda _: object())
    monkeypatch.setattr(EVAL, "create_ai_runtime", runtime)
    monkeypatch.setattr(EVAL, "verify_endpoint", endpoint)
    monkeypatch.setattr(EVAL, "ChatbotWorkflow", Workflow)
    args = arguments(
        tmp_path,
        case_ids="basic-01,basic-02",
        provider="vllm",
        model="synthetic-model",
        endpoint_alias="general-dev-gpu",
        runtime_label="0.28.0",
        artifact_revision="a" * 40,
        artifact_sha256="b" * 64,
        runtime_image="vllm/vllm-openai@sha256:" + "c" * 64,
        deployment_image="ghcr.io/example/general-serving@sha256:" + "d" * 64,
    )
    if failed_stage in {"warmup", "cases"}:
        task = asyncio.create_task(EVAL.evaluate(args))
        await asyncio.wait_for(reached.wait(), timeout=1)
        task.cancel("sensitive cancellation reason")
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError) as captured:
            await EVAL.evaluate(args)
        assert captured.value is failure
    report_text = Path(args.output).read_text()
    report = json.loads(report_text)
    interrupted = failed_stage in {"warmup", "cases"}
    assert report["status"] == ("INTERRUPTED" if interrupted else "FAILED")
    assert report["error_type"] == ("CancelledError" if interrupted else "RuntimeError")
    assert report["stage"] == failed_stage
    expected_rows = {"provenance": 0, "warmup": 0, "cases": 1, "final_provenance": 2}
    assert len(report["rows"]) == expected_rows[failed_stage]
    assert [row["id"] for row in report["rows"]] == ["basic-01", "basic-02"][
        : expected_rows[failed_stage]
    ]
    assert all(row["passed"] for row in report["rows"])
    assert (report["warmup_ms"] is None) == (failed_stage in {"provenance", "warmup"})
    assert report["provenance"]["scorer_version"] == EVAL.SCORER_VERSION
    assert report["summary"] == EVAL.summarize(report["rows"])
    assert "final_endpoint_attestation" not in report["provenance"]
    assert exited == (failed_stage != "provenance")
    assert "sensitive" not in report_text
    assert not Path(args.output + ".tmp").exists()
