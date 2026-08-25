from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = REPO_ROOT / "docs" / "deliverables" / "registry.yaml"
REQUIRED_ARTIFACT_FIELDS = {
    "artifact_id",
    "title",
    "week",
    "management_mode",
    "source_mode",
    "source_ref",
    "source_paths",
    "drive_folder_id",
    "drive_file_id",
    "drive_url",
    "observed_at",
    "sheet_row_key",
    "notes",
}
EXPECTED_TITLES = {
    "요구사항 정의서",
    "WBS",
    "프로젝트 기획서",
    "수집 데이터 보고서",
    "데이터베이스/저장소 설계 문서",
    "데이터 전처리 결과서",
    "머신러닝/딥러닝 학습결과서",
    "학습한 ML/DL 모델",
}
ALLOWED_MANAGEMENT_MODES = {"active", "manual_on_request"}
ALLOWED_SOURCE_MODES = {"external_pending_import", "git_branch", "git_managed"}
BANNED_KEYS = {"status", "submission_status", "feedback", "instructor_feedback"}


def fail(message: str) -> None:
    raise ValueError(message)


def find_banned_keys(value: Any, path: str = "registry") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in BANNED_KEYS:
                found.append(child_path)
            found.extend(find_banned_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_banned_keys(child, f"{path}[{index}]"))
    return found


def git_object_exists(ref: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def validate() -> None:
    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        fail("registry root must be a mapping")
    if set(registry) != {"schema_version", "updated", "policy", "integrations", "artifacts"}:
        fail("registry top-level fields do not match the v1 schema")
    if registry.get("schema_version") != 1:
        fail("schema_version must be 1")

    policy = registry.get("policy")
    if not isinstance(policy, dict):
        fail("policy must be a mapping")
    if policy.get("canonical_store") != "git":
        fail("policy.canonical_store must be git")
    if policy.get("one_document_per_task") is not True:
        fail("policy.one_document_per_task must be true")
    if policy.get("submission_status_owner") != "human":
        fail("policy.submission_status_owner must be human")
    if policy.get("excluded_weeks") != [4]:
        fail("policy.excluded_weeks must contain only week 4")

    integrations = registry.get("integrations")
    if not isinstance(integrations, dict):
        fail("integrations must be a mapping")
    drive = integrations.get("google_drive")
    sheet = integrations.get("management_sheet")
    if not isinstance(drive, dict) or not isinstance(sheet, dict):
        fail("google_drive and management_sheet integrations are required")
    if drive.get("codex_read_access") != "verified":
        fail("Codex Drive read access must be recorded as verified")
    if drive.get("codex_write_access") != "unverified":
        fail("Codex Drive write access must remain unverified")
    if drive.get("claude_code_access") != "unverified":
        fail("Claude Code Drive access must remain unverified")
    if sheet.get("team_tab") != "3팀" or sheet.get("row_and_column_coordinates_persisted") is not False:
        fail("management sheet must use the 3팀 tab without persisted coordinates")

    banned = find_banned_keys(registry)
    if banned:
        fail(f"submission state or feedback must not be stored: {', '.join(banned)}")

    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 8:
        fail("artifacts must contain exactly the eight approved v1 entries")

    ids: set[str] = set()
    titles: set[str] = set()
    row_keys: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            fail("each artifact must be a mapping")
        missing = REQUIRED_ARTIFACT_FIELDS - artifact.keys()
        if missing:
            fail(f"artifact is missing fields: {sorted(missing)}")
        extra = artifact.keys() - REQUIRED_ARTIFACT_FIELDS
        if extra:
            fail(f"artifact has unsupported fields: {sorted(extra)}")
        artifact_id = artifact["artifact_id"]
        title = artifact["title"]
        row_key = artifact["sheet_row_key"]
        if not isinstance(artifact_id, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", artifact_id) is None:
            fail(f"artifact_id must be kebab-case: {artifact_id}")
        if artifact_id in ids or title in titles or row_key in row_keys:
            fail(f"duplicate artifact id, title, or row key: {artifact_id}")
        ids.add(artifact_id)
        titles.add(title)
        row_keys.add(row_key)
        if artifact["week"] not in {1, 2, 3}:
            fail(f"artifact week must be 1, 2, or 3: {artifact_id}")
        if row_key != title:
            fail(f"sheet_row_key must match the approved title: {artifact_id}")
        if artifact["management_mode"] not in ALLOWED_MANAGEMENT_MODES:
            fail(f"invalid management_mode: {artifact_id}")
        if artifact["source_mode"] not in ALLOWED_SOURCE_MODES:
            fail(f"invalid source_mode: {artifact_id}")
        if not isinstance(artifact["source_paths"], list):
            fail(f"source_paths must be a list: {artifact_id}")
        if not isinstance(artifact["notes"], list):
            fail(f"notes must be a list: {artifact_id}")
        for field in ("drive_folder_id", "drive_file_id", "drive_url", "observed_at"):
            if not artifact[field]:
                fail(f"{field} must be populated: {artifact_id}")
        if artifact["drive_file_id"] not in artifact["drive_url"]:
            fail(f"drive_url must contain drive_file_id: {artifact_id}")

    if titles != EXPECTED_TITLES:
        fail("artifact titles do not match the approved v1 scope")

    by_title = {artifact["title"]: artifact for artifact in artifacts}
    if by_title["WBS"]["management_mode"] != "manual_on_request":
        fail("WBS must be manual_on_request")
    if any(
        artifact["management_mode"] != "active"
        for title, artifact in by_title.items()
        if title != "WBS"
    ):
        fail("all non-WBS v1 artifacts must be active")

    ml_titles = {"머신러닝/딥러닝 학습결과서", "학습한 ML/DL 모델"}
    for title, artifact in by_title.items():
        if title in ml_titles:
            if artifact["source_mode"] != "git_branch" or artifact["source_ref"] != "feat/ml-poc":
                fail(f"ML artifact must use feat/ml-poc: {artifact['artifact_id']}")
            for source_path in artifact["source_paths"]:
                if not git_object_exists(artifact["source_ref"], source_path):
                    fail(f"missing ML source path at feat/ml-poc: {source_path}")
        elif artifact["source_mode"] != "external_pending_import":
            fail(f"legacy artifact must await one-document import: {artifact['artifact_id']}")
        elif artifact["source_ref"] is not None or artifact["source_paths"]:
            fail(f"pending external artifact must not claim Git sources: {artifact['artifact_id']}")


if __name__ == "__main__":
    try:
        validate()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"deliverables registry validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("deliverables registry validation passed")
