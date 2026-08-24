"""중개 판정 코드와 project-wiki의 구현 범위를 함께 고정한다."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_judgment_contract_and_project_wiki_stay_aligned() -> None:
    references = REPOSITORY_ROOT / ".agents" / "skills" / "project-wiki" / "references"
    contract = (references / "contracts" / "f3-ai.md").read_text()
    api_contract = (references / "contracts" / "api.md").read_text()
    index = (references / "index.md").read_text()
    log = (references / "log.md").read_text()
    online_runtime = (
        REPOSITORY_ROOT / "docs" / "architecture" / "f3" / "online-runtime.md"
    ).read_text()

    assert "# F3 포지션 카드·중개 판정 Backend–AI 계약" in contract
    assert "`brokerage-judgment:v1`" in contract
    assert "결과를 반환하기 전에 직접 호출" in contract
    assert "`SYNTHETIC_PROTOTYPE` 요청은 생성기 조립 지점" in contract
    assert "Backend 중개 판정 입력 조립" in contract
    assert "| `JUDGING` | 업무 처리 | 전체 후보 중개 판정 실행 중 | 제안 · 미구현 |" in api_contract
    assert "포지션 카드·중개 판정" in index
    assert "F3 중개 판정 Backend–AI 계약" in log
    assert "중개 판정 Backend–AI 공개 계약과 구조화 출력 생성" in online_runtime
    assert "Backend 입력 조립·저장과 `JUDGING`·`COMPLETED` 전이는 미구현" in online_runtime
