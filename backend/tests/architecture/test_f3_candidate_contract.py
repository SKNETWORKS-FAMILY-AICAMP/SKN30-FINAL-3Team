"""후보 추출 구현 상태와 project-wiki 정본의 동기화를 검증한다."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_candidate_selection_implementation_and_project_wiki_stay_aligned() -> None:
    api_contract = (
        REPOSITORY_ROOT
        / ".agents"
        / "skills"
        / "project-wiki"
        / "references"
        / "contracts"
        / "api.md"
    ).read_text()
    online_runtime = (
        REPOSITORY_ROOT / "docs" / "architecture" / "f3" / "online-runtime.md"
    ).read_text()
    log = (
        REPOSITORY_ROOT / ".agents" / "skills" / "project-wiki" / "references" / "log.md"
    ).read_text()

    implemented_row = "| `CANDIDATES_READY` | 업무 처리 | 결정적 SQL 후보 스냅샷 완료 | 구현됨 |"
    assert implemented_row in api_contract
    assert "`RUNNING`, `ANCHOR_READY`, `CANDIDATES_READY`" in api_contract
    assert "`candidate-selection:v3`" in online_runtime
    assert "F3 결정적 SQL 후보 추출을 구현" in log
