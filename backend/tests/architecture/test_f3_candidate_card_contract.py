"""후보 카드 구현 상태와 project-wiki 정본의 동기화를 검증한다."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_candidate_card_implementation_and_project_wiki_stay_aligned() -> None:
    api_contract = (
        REPOSITORY_ROOT
        / ".agents"
        / "skills"
        / "project-wiki"
        / "references"
        / "contracts"
        / "api.md"
    ).read_text(encoding="utf-8")
    ai_contract = (
        REPOSITORY_ROOT
        / ".agents"
        / "skills"
        / "project-wiki"
        / "references"
        / "contracts"
        / "f3-ai.md"
    ).read_text(encoding="utf-8")
    online_runtime = (
        REPOSITORY_ROOT / "docs" / "architecture" / "f3" / "online-runtime.md"
    ).read_text(encoding="utf-8")
    log = (
        REPOSITORY_ROOT / ".agents" / "skills" / "project-wiki" / "references" / "log.md"
    ).read_text(encoding="utf-8")

    assert (
        "| `CANDIDATE_CARDS_READY` | 업무 처리 | 후보 카드 생성·재사용 완료 | 구현됨 |"
        in api_contract
    )
    assert "`CANDIDATE_CARDS_READY`, `JUDGING`)다" in api_contract
    assert "후보 카드 재사용 경계" in ai_contract
    assert "`SYNTHETIC_PROTOTYPE` 입력만 허용" in ai_contract
    assert "중개 판정 요청 조립, 결과·근거 저장" in online_runtime
    assert "후보 포지션 카드 확보" in online_runtime
    assert "F3 최초 카드화·판정 상한을 상위 5건으로 조정" in log
