import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_ai_source_does_not_import_backend_frameworks_or_database_clients() -> None:
    forbidden = {
        "asyncpg",
        "backend",
        "fastapi",
        "psycopg",
        "sqlalchemy",
        "sqlmodel",
    }
    violations = {
        str(path.relative_to(REPOSITORY_ROOT)): sorted(imported_roots(path) & forbidden)
        for path in (REPOSITORY_ROOT / "ai" / "src").rglob("*.py")
        if imported_roots(path) & forbidden
    }

    assert violations == {}


def test_backend_source_does_not_import_ai_sdk_or_workflow_details() -> None:
    forbidden = {"langgraph", "openai"}
    violations = {
        str(path.relative_to(REPOSITORY_ROOT)): sorted(imported_roots(path) & forbidden)
        for path in (REPOSITORY_ROOT / "backend" / "src").rglob("*.py")
        if imported_roots(path) & forbidden
    }

    assert violations == {}


def test_f3_public_contract_does_not_import_workflow_or_provider_sdk() -> None:
    """Backend 는 이 계약만 보고 구현한다. LangGraph 나 SDK 타입이 새면 경계가 무너진다."""
    forbidden = {"langgraph", "openai", "vllm"}
    violations = {
        str(path.relative_to(REPOSITORY_ROOT)): sorted(imported_roots(path) & forbidden)
        for path in (REPOSITORY_ROOT / "ai" / "src" / "brokerage_ai" / "f3").rglob("*.py")
        if imported_roots(path) & forbidden
    }

    assert violations == {}
