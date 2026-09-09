"""Check candidate state and schema identifiers against the public contract."""

from f3_document_contract import REPOSITORY_ROOT, implemented_api_states

from domain.agent_execution.candidates import CANDIDATE_SELECTION_SCHEMA_VERSION
from domain.agent_execution.models import CANDIDATES_READY_STATUS, IN_PROGRESS_STATUSES


def test_candidate_selection_implementation_and_project_wiki_stay_aligned() -> None:
    assert CANDIDATES_READY_STATUS in implemented_api_states()
    assert CANDIDATES_READY_STATUS in IN_PROGRESS_STATUSES
    online_runtime = (REPOSITORY_ROOT / "docs/architecture/f3/online-runtime.md").read_text(
        encoding="utf-8"
    )
    assert f"`{CANDIDATE_SELECTION_SCHEMA_VERSION}`" in online_runtime
