import re
from pathlib import Path

from yoyo import read_migrations

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "db" / "migrate"
NAME_PATTERN = re.compile(r"^[0-9]{3}_(CREATE|ALTER|DATA|DROP)_[A-Z0-9_]+\.sql$")


def migration_files() -> list[Path]:
    return sorted(MIGRATION_DIRECTORY.glob("*.sql"))


def test_migration_names_and_sequence() -> None:
    files = migration_files()

    assert [int(path.name[:3]) for path in files] == list(range(1, 9))
    assert all(NAME_PATTERN.fullmatch(path.name) for path in files)


def test_migrations_have_linear_dependencies_and_tool_owned_transactions() -> None:
    files = migration_files()

    for index, path in enumerate(files):
        text = path.read_text()
        expected = "-- depends:" if index == 0 else f"-- depends: {files[index - 1].stem}"
        assert expected in text
        assert "\nBEGIN;" not in text
        assert "\nCOMMIT;" not in text


def test_migrations_use_business_names() -> None:
    forbidden = re.compile(r"(?i)(?:\bf[123]\b|f[123]_terminology_placeholder)")
    text = "\n".join(path.read_text() for path in migration_files())

    assert forbidden.search(text) is None
    assert "CREATE TABLE agent_run" in text
    assert "CREATE TABLE agent_capability_call" in text
    assert "CREATE TABLE ai_decision_feedback" in text


def test_schema_baseline_contains_26_tables() -> None:
    text = "\n".join(path.read_text() for path in migration_files())

    assert len(re.findall(r"(?m)^CREATE TABLE ", text)) == 26


def test_yoyo_can_parse_all_sql_migrations() -> None:
    migrations = read_migrations(str(MIGRATION_DIRECTORY))

    assert len(migrations) == 8
