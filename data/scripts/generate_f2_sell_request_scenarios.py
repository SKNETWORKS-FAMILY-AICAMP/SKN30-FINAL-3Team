from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "f2_llm" / "working"
DATASET_VERSION = "0.4.0"
SOURCE_TYPE = "fully_synthetic_from_abstract_blueprint"
LABEL = "매도의뢰"
PLACEHOLDER_PHONE = "010-1234-5678"

CITIES = ("나린온시", "소보람시", "별밭시", "온새미시", "하늬바람시", "달빛고을시", "정겨운시", "윤슬시")
GUS = ("바오름구", "여울구", "다솜구", "새록구", "물빛구", "은어구", "초록누리구", "하늘가람구")
DONGS = ("수풀동", "별빛동", "고운동", "늘봄동", "은행나무동", "단풍마루동", "솔바람동", "냇가동")
COMPLEXES = (
    "이든여울빛마을",
    "라온누리파크",
    "한빛마루타운",
    "다솜언덕마을",
    "새봄으뜸단지",
    "푸른들채",
    "온새미로타운",
    "별헤는마을",
    "고운뜨락",
    "향긋한숲마을",
)


def address(index: int) -> str:
    city = CITIES[index % len(CITIES)]
    gu = GUS[(index * 3) % len(GUS)]
    dong_name = DONGS[(index * 5) % len(DONGS)]
    complex_name = COMPLEXES[(index * 7) % len(COMPLEXES)]
    building = 100 + (index * 11) % 20
    unit = 101 + (index * 13) % 1400
    return f"{city} {gu} {dong_name} {complex_name} {building}동 {unit}호"


SELL_OPENINGS = (
    "여보세요, 지금 살고 있는 집을 내놓으려고 연락드렸습니다. 이사 갈 곳은 대충 정해졌는데 지금 집이 안 팔리면 곤란해서요.",
    "안녕하세요, 소유하고 있는 집을 매물로 등록하고 싶어서 전화했습니다. 예전에 잠깐 알아본 적은 있는데 이번엔 진짜로 진행하려고요.",
    "저기, 이사 계획이 생겨서 살던 아파트를 매매로 내놓으려고 합니다. 아이 학교 때문에 시기가 좀 빠듯할 것 같아요.",
    "안녕하세요, 비어 있는 오피스텔이 하나 있어서 임대로 내놓으려고 문의드립니다. 관리하기가 번거로워서 이번에 정리하려고요.",
    "가지고 있던 상가를 정리하려고 매도 의뢰를 하고 싶어서 연락드렸습니다. 임대 수익이 예전만 못해서 결정했어요.",
    "전세로 내놓을 집이 있어서 접수 부탁드리려고 연락했습니다. 지방 발령이 나서 급하게 알아보는 중입니다.",
    "월세를 받던 집인데 이번에 매매로 전환하려고 합니다. 관리가 힘들어서 아예 정리하는 쪽으로 마음먹었어요.",
    "부모님 명의로 되어 있는 아파트를 처분하려고 대신 문의드립니다. 어르신들이 요양원으로 옮기셔서요.",
    "직장 발령으로 살던 집을 급하게 내놓아야 할 것 같아서 전화드렸습니다. 다음 달까지는 정리가 됐으면 합니다.",
    "상속받은 주택을 정리하려고 하는데 매도 절차가 처음이라 하나씩 여쭤보고 싶습니다.",
)

SELL_TARGETS = (
    "위치는 {addr}이고, 방 세 개짜리 중형 평형입니다. 채광이 좋은 편이고 엘리베이터도 있어요.",
    "{addr}에 있는 소형 오피스텔이고, 원룸형이라 혼자 살거나 사무실로 쓰기에도 괜찮습니다.",
    "{addr}의 대형 평형 아파트로 남향 위주 동이고, 단지 안에 어린이집도 있습니다.",
    "{addr} 1층 점포이고 대로변에 접해 있어서 유동 인구가 꽤 있는 자리입니다.",
    "{addr}에 있는 소형 빌라이고, 세대수가 많지 않아 조용한 편입니다.",
    "{addr}의 중소형 평형이며, 지하철역까지 걸어서 갈 수 있는 거리입니다.",
    "{addr}의 신축 오피스텔이고, 냉장고와 세탁기까지 옵션으로 들어가 있는 풀옵션 상태입니다.",
    "{addr}에 있는 단독주택이고, 작은 마당이 딸려 있는 구조입니다.",
    "{addr}의 대형 평형 중에서도 조망이 트인 동이라 앞이 막혀 있지 않습니다.",
    "{addr} 2층 사무실이고, 엘리베이터가 있는 건물이라 짐 옮기기도 수월합니다.",
)

SELL_TERMS = (
    "희망 가격은 인근 시세 범위에서 생각하고 있고, 실제 매수자가 나타나면 어느 정도 조정할 수 있습니다. 급하게 팔 생각은 아니라서 무리하게 깎을 생각은 없어요.",
    "현재 소유자가 직접 거주 중이며, 이사 준비 기간이 두 달 정도 필요합니다. 그전에 계약이 되면 일정은 맞춰볼 수 있어요.",
    "지금은 공실 상태라 협의만 되면 바로 입주가 가능합니다. 청소도 미리 해둘 생각입니다.",
    "현재 임차인이 살고 있어서 계약 만기 시점을 먼저 확인해야 합니다. 만기가 몇 달 안 남아서 크게 문제는 없을 것 같아요.",
    "담보대출이 일부 남아 있지만 잔금 때 정리할 예정입니다. 대출 서류는 필요하시면 바로 준비해서 드리겠습니다.",
    "대출 없이 단독명의로 정리되어 있는 물건입니다. 권리관계는 깨끗한 편이에요.",
    "권리관계는 서류를 한번 더 정리해서 다시 안내드릴 수 있습니다. 오래 보유한 물건이라 확인할 서류가 좀 있어요.",
    "수리는 작년에 이미 끝난 상태라 바로 보여드릴 수 있습니다. 도배와 장판도 새로 했습니다.",
    "가격과 조건은 아직 가족과 협의 중이라 우선은 범위로만 말씀드릴 수 있습니다. 다음 주까지는 정리해서 다시 연락드릴게요.",
    "관리비와 시설 상태는 자료를 정리해서 함께 전달하겠습니다. 최근 몇 달치 고지서도 챙겨두겠습니다.",
)

SELL_REQUESTS = (
    "매물 접수가 되면 필요한 서류부터 먼저 안내해 주시면 좋겠습니다. 처음이라 뭐부터 준비해야 할지 잘 모르겠어요.",
    "방문 일정은 사전에 연락 주시면 맞춰서 조율하겠습니다. 평일 저녁이나 주말이 그나마 편합니다.",
    "광고에 올리기 전에 조건을 한 번 더 확인하고 싶습니다. 제가 말씀드린 내용이 정확히 반영됐는지 보고 싶어요.",
    "매수 희망자가 나타나면 조건을 먼저 저한테 전달해 주세요. 바로 결정하기보다는 한 번 검토하고 싶습니다.",
    "가격 협의가 가능한 범위도 함께 안내해 주시면 좋겠습니다. 어느 정도까지 조정 가능한지 미리 알아두고 싶어요.",
    "현재 임차인과의 일정도 같이 고려해서 진행해 주세요. 괜히 서두르다 문제 생기는 건 원치 않습니다.",
    "계약 관련 절차가 처음이라 하나씩 설명해 주시면 감사하겠습니다. 특약 같은 것도 잘 몰라서요.",
    "다른 매물과 비교해서 적정 가격도 함께 알려주시면 좋겠습니다. 제가 생각한 금액이 맞는지 궁금합니다.",
    "서류 준비는 며칠 정도 걸리는지 미리 알고 싶습니다. 등기부등본이나 건축물대장 같은 것들이요.",
    "진행 상황이 있으면 중간중간 연락해서 알려주시면 좋겠습니다. 궁금해서 자꾸 여쭤보게 될 것 같아요.",
)

SELL_CLOSINGS = (
    f"제 연락처는 {PLACEHOLDER_PHONE}입니다. 편하실 때 연락 주시면 됩니다.",
    f"번호 남겨드릴게요, {PLACEHOLDER_PHONE}입니다. 문자로 먼저 주셔도 괜찮아요.",
    f"네, {PLACEHOLDER_PHONE}으로 연락 주시면 바로 확인하겠습니다.",
    f"제 번호가 {PLACEHOLDER_PHONE}인데, 낮에는 일하고 있어서 문자가 더 편할 수도 있습니다.",
    f"우선 여기까지 말씀드리고, 자세한 건 {PLACEHOLDER_PHONE}으로 이어서 이야기하시죠.",
    f"급한 연락은 {PLACEHOLDER_PHONE}으로 주시면 됩니다. 확인되는 대로 답 드리겠습니다.",
)

SELL_PATTERNS = (
    ("opening", "subject", "context", "request", "closing"),
    ("subject", "opening", "context", "request", "closing"),
    ("opening", "request", "subject", "context", "closing"),
    ("opening", "subject", "context", "closing"),
    ("context", "opening", "subject", "request", "closing"),
    ("opening", "subject", "request", "closing"),
    ("subject", "context", "opening", "request", "closing"),
    ("opening", "context", "subject", "closing"),
    ("request", "opening", "subject", "context", "closing"),
    ("opening", "subject", "context", "request", "closing"),
)


def records(
    *,
    label: str,
    id_prefix: str,
    group_prefix: str,
    count: int,
    openings: tuple[str, ...],
    subjects: tuple[str, ...],
    contexts: tuple[str, ...],
    requests: tuple[str, ...],
    closings: tuple[str, ...],
    patterns: tuple[tuple[str, ...], ...],
) -> list[dict[str, object]]:
    generated: list[dict[str, object]] = []
    for index in range(1, count + 1):
        offset = index - 1
        block = offset // 10
        fragments = {
            "opening": openings[offset % len(openings)],
            "subject": subjects[(offset * 3 + block) % len(subjects)].format(addr=address(index)),
            "context": contexts[(offset * 3 + block) % len(contexts)],
            "request": requests[(offset * 7 + block * 2) % len(requests)],
            "closing": closings[offset % len(closings)],
        }
        transcript = " ".join(
            fragments[name] for name in patterns[offset % len(patterns)]
        )
        generated.append(
            {
                "scenario_id": f"{id_prefix}-{index:04d}",
                "dataset_version": DATASET_VERSION,
                "label": label,
                "transcript": transcript,
                "source_type": SOURCE_TYPE,
                "source_group_id": f"{group_prefix}-{index:04d}",
                "split": "unassigned",
                "contains_real_personal_data": False,
            }
        )
    return generated


def validate(rows: list[dict[str, object]], label: str, count: int) -> None:
    expected_keys = {
        "scenario_id",
        "dataset_version",
        "label",
        "transcript",
        "source_type",
        "source_group_id",
        "split",
        "contains_real_personal_data",
    }
    if len(rows) != count:
        raise ValueError(f"{label}: expected {count} rows, got {len(rows)}")
    if any(set(row) != expected_keys for row in rows):
        raise ValueError(f"{label}: schema mismatch")
    if any(row["label"] != label for row in rows):
        raise ValueError(f"{label}: incorrect label")
    if len({row["scenario_id"] for row in rows}) != len(rows):
        raise ValueError(f"{label}: duplicate scenario_id")
    if len({row["source_group_id"] for row in rows}) != len(rows):
        raise ValueError(f"{label}: duplicate source_group_id")
    if len({row["transcript"] for row in rows}) != len(rows):
        raise ValueError(f"{label}: duplicate transcript")
    if any(row["contains_real_personal_data"] is not False for row in rows):
        raise ValueError(f"{label}: invalid privacy flag")
    if any(not 60 <= len(str(row["transcript"])) <= 700 for row in rows):
        raise ValueError(f"{label}: transcript length outside expected range")
    explicit_label_count = sum(label in str(row["transcript"]) for row in rows)
    leak_threshold = max(10, count // 5)
    if explicit_label_count > leak_threshold:
        raise ValueError(f"{label}: explicit label leakage in {explicit_label_count} rows")

    forbidden_patterns = (
        re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    )
    phone_pattern = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
    for row in rows:
        transcript = str(row["transcript"])
        if any(pattern.search(transcript) for pattern in forbidden_patterns):
            raise ValueError(f"{label}: possible personal data in {row['scenario_id']}")
        for match in phone_pattern.finditer(transcript):
            if match.group(0) != PLACEHOLDER_PHONE:
                raise ValueError(
                    f"{label}: unexpected phone-like string in {row['scenario_id']}"
                )


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


COUNT = 300


def main() -> None:
    sell_request = records(
        label=LABEL,
        id_prefix="f2-sell-request-blueprint-safe",
        group_prefix="sell-request-blueprint-safe",
        count=COUNT,
        openings=SELL_OPENINGS,
        subjects=SELL_TARGETS,
        contexts=SELL_TERMS,
        requests=SELL_REQUESTS,
        closings=SELL_CLOSINGS,
        patterns=SELL_PATTERNS,
    )
    validate(sell_request, LABEL, COUNT)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        OUTPUT_DIR / "f2_sell_request_scenarios.privacy_safe.v0.4.jsonl",
        sell_request,
    )


if __name__ == "__main__":
    main()
