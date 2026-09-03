import re
from pathlib import Path

from yoyo import read_migrations

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "db" / "migrate"
NAME_PATTERN = re.compile(r"^[0-9]{3}_(CREATE|ALTER|DATA|DROP)_[A-Z0-9_]+\.sql$")


def migration_files() -> list[Path]:
    return sorted(MIGRATION_DIRECTORY.glob("*.sql"))


def test_migration_names_and_sequence() -> None:
    files = migration_files()

    assert [int(path.name[:3]) for path in files] == list(range(1, 18))
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


def test_schema_baseline_contains_27_tables() -> None:
    text = "\n".join(path.read_text() for path in migration_files())

    assert len(re.findall(r"(?m)^CREATE TABLE ", text)) == 27


def test_all_tables_and_columns_have_comments() -> None:
    text = "\n".join(path.read_text() for path in migration_files())
    expected_tables: set[str] = set()
    expected_columns: set[tuple[str, str]] = set()

    create_table_pattern = re.compile(r"CREATE TABLE\s+(\w+)\s*\((.*?)\n\);", re.DOTALL)
    for match in create_table_pattern.finditer(text):
        table, body = match.groups()
        expected_tables.add(table)
        for line in body.splitlines():
            column_match = re.match(r"\s{4}([a-z][a-z0-9_]*)\s+", line)
            if column_match:
                expected_columns.add((table, column_match.group(1)))

    alter_table_pattern = re.compile(r"ALTER TABLE\s+(\w+)\s+(.*?);", re.DOTALL)
    for match in alter_table_pattern.finditer(text):
        table, body = match.groups()
        for column in re.findall(r"ADD COLUMN\s+(\w+)", body):
            expected_columns.add((table, column))

    commented_tables = set(re.findall(r"(?m)^COMMENT ON TABLE\s+(\w+)\s+IS", text))
    commented_columns = set(re.findall(r"(?m)^COMMENT ON COLUMN\s+(\w+)\.(\w+)\s+IS", text))

    assert commented_tables == expected_tables
    assert commented_columns == expected_columns


def test_yoyo_can_parse_all_sql_migrations() -> None:
    migrations = read_migrations(str(MIGRATION_DIRECTORY))

    assert len(migrations) == 17
