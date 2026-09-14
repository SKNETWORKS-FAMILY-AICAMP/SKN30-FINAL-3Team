"""Check navigable canonical contracts and machine-owned vocabulary, not prose."""

import re
from pathlib import Path

from brokerage_ai.f3.judgment_contracts import (
    BROKERAGE_JUDGMENT_CONTRACT_VERSION,
    BrokerageJudgmentRequest,
    CandidateJudgment,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REFERENCES = REPOSITORY_ROOT / ".agents" / "skills" / "project-wiki" / "references"


def linked_paths(document: Path) -> set[Path]:
    return {
        (document.parent / target.split("#", 1)[0]).resolve()
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text())
        if "://" not in target
    }


def test_judgment_contract_remains_reachable_from_the_wiki_index() -> None:
    router = REFERENCES / "contracts" / "f3-ai.md"
    contract = REFERENCES / "contracts" / "f3-ai-brokerage.md"
    assert router in linked_paths(REFERENCES / "index.md")
    assert contract in linked_paths(router)
    assert all(path.is_file() for path in linked_paths(contract))


def test_documented_judgment_fields_match_public_dto() -> None:
    contract = (REFERENCES / "contracts" / "f3-ai-brokerage.md").read_text()
    documented_fields = set(re.findall(r"^\| `([^`]+)` \|", contract, re.MULTILINE))
    for model in (BrokerageJudgmentRequest, CandidateJudgment):
        assert set(model.model_fields) <= documented_fields
    assert f"`{BROKERAGE_JUDGMENT_CONTRACT_VERSION}`" in contract
