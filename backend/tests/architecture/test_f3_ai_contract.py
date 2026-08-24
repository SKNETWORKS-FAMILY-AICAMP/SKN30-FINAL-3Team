"""Backend 와 AI 의 F3 포지션 카드 어휘가 실제로 같은 값인지 확인한다.

두 모듈이 각자 enum 을 들고 있으므로 한쪽만 바꾸면 cache key 와 저장값이 조용히 갈라진다.
문서가 아니라 여기서 막는다. 정본은 project-wiki 의 contracts/f3-ai.md 다.

이 파일은 AI 계약 모듈을 import 하는 것 자체가 DB 연결이나 Provider client 를 만들지
않는다는 것도 확인한다. Backend 는 이 계약을 SDK 없이 쓸 수 있어야 한다.
"""

import subprocess
import sys
from pathlib import Path

from brokerage_ai.f3 import (
    POSITION_CARD_CONTRACT_VERSION,
    ContactabilityStatus,
    EvidenceKind,
    InputPrivacyMode,
    NegotiationIntent,
    NegotiationSide,
    Urgency,
)

from domain.agent_execution.cache_key import CACHE_KEY_SCHEMA_VERSION
from domain.agent_execution.models import AnchorType

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_negotiation_side_matches_the_backend_anchor_type() -> None:
    assert NegotiationSide.LISTING.value == AnchorType.LISTING.value
    assert NegotiationSide.REQUIREMENT.value == AnchorType.REQUIREMENT.value
    assert {side.value for side in NegotiationSide} == {kind.value for kind in AnchorType}


def test_card_vocabularies_fit_the_stored_columns() -> None:
    """migration 005 의 VARCHAR(20) 과 기본값에 그대로 들어가야 한다."""
    vocabularies = (NegotiationSide, NegotiationIntent, Urgency, ContactabilityStatus, EvidenceKind)
    assert all(len(member.value) <= 20 for group in vocabularies for member in group)
    assert NegotiationIntent.UNKNOWN.value == "UNKNOWN"
    assert Urgency.UNKNOWN.value == "UNKNOWN"
    assert ContactabilityStatus.CAUTION.value == "CAUTION"
    assert ContactabilityStatus.UNKNOWN.value == "UNKNOWN"
    assert EvidenceKind.INFERENCE.value == "INFERENCE"


def test_contract_version_and_cache_key_version_are_separate_axes() -> None:
    assert POSITION_CARD_CONTRACT_VERSION == "position-card:v1"
    assert CACHE_KEY_SCHEMA_VERSION == "position-card:v2"
    assert POSITION_CARD_CONTRACT_VERSION != CACHE_KEY_SCHEMA_VERSION


def test_input_privacy_modes_make_the_prototype_exception_explicit() -> None:
    assert {mode.value for mode in InputPrivacyMode} == {"SYNTHETIC_PROTOTYPE", "MASKED"}


def test_f3_ai_project_decisions_are_registered() -> None:
    """공개 계약의 정본·해결 질문·개인정보 결정을 함께 등록하게 한다."""
    references = REPOSITORY_ROOT / ".agents" / "skills" / "project-wiki" / "references"
    contract_path = references / "contracts" / "f3-ai.md"
    assert contract_path.is_file()

    contract = contract_path.read_text()
    index = (references / "index.md").read_text()
    log = (references / "log.md").read_text()
    open_questions = (references / "open-questions.md").read_text()
    privacy_policy = (references / "privacy" / "policy.md").read_text()
    prototype_decision = (
        references / "decisions" / "ADR-0014-f3-prototype-synthetic-input.md"
    ).read_text()

    assert "status: 결정" in contract
    assert "| `LISTING` |" in contract
    assert "| `REQUIREMENT` |" in contract
    assert "[contracts/f3-ai.md](contracts/f3-ai.md)" in index
    assert "`contracts/f3-ai.md`" in log
    assert "OQ-012" not in open_questions
    assert "SYNTHETIC_PROTOTYPE" in privacy_policy
    assert "상태: 승인됨" in prototype_decision


def test_importing_the_contract_has_no_configuration_or_client_side_effect() -> None:
    """계약 import 가 설정을 읽거나 client 를 만들면 Worker 기동이 환경에 묶인다.

    환경변수를 모두 비운 별도 프로세스에서 확인한다. `.env` 로딩과 SDK client 생성은
    미리 막아 두고, 그래도 import 가 통과해야 계약을 설정 없이 쓸 수 있다.
    """
    probe = (
        "import sys, dotenv, openai;"
        " boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError('import side effect'));"
        " dotenv.load_dotenv = boom;"
        " openai.OpenAI = boom;"
        " openai.AsyncOpenAI = boom;"
        " import brokerage_ai.f3 as f3;"
        " assert f3.POSITION_CARD_CONTRACT_VERSION == 'position-card:v1';"
        " leaked = set(sys.modules) & {'sqlalchemy', 'sqlmodel', 'psycopg', 'fastapi'};"
        " assert not leaked, leaked"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        env={},
    )

    assert completed.returncode == 0, completed.stderr
