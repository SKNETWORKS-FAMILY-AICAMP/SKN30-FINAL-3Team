"""Check candidate-card states and privacy identifiers without prose snapshots."""

from brokerage_ai.f3 import InputPrivacyMode
from f3_document_contract import REFERENCES, implemented_api_states

from domain.agent_execution.models import CANDIDATE_CARDS_READY_STATUS, IN_PROGRESS_STATUSES


def test_candidate_card_implementation_and_project_wiki_stay_aligned() -> None:
    assert CANDIDATE_CARDS_READY_STATUS in implemented_api_states()
    assert CANDIDATE_CARDS_READY_STATUS in IN_PROGRESS_STATUSES
    contract = (REFERENCES / "contracts/f3-ai-position-card.md").read_text(encoding="utf-8")
    assert f"`{InputPrivacyMode.SYNTHETIC_PROTOTYPE.value}`" in contract
    # Enforcement of the prototype-only input is covered by actual generation tests.
