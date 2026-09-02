from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "f2_llm" / "working"
DATASET_VERSION = "0.4.0"
SOURCE_TYPE = "fully_synthetic_from_abstract_blueprint"
LABEL = "매수문의"
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
    return f"{city} {gu} {dong_name} {complex_name} {building}동 인근"


BUY_OPENINGS = (
    "안녕하세요, 이사할 곳을 알아보고 있어서 매물이 있는지 문의드리려고 전화했습니다. 시간이 좀 걸리더라도 조건 맞는 곳을 찾고 싶어요.",
    "여보세요, 살 집을 구하는 중인데 조건에 맞는 물건이 있는지 여쭤보려고요. 인터넷으로 몇 군데 봤는데 실제로 있는지 확인하고 싶습니다.",
    "전세로 들어갈 곳을 찾고 있어서 연락드렸습니다. 지금 나와 있는 매물이 있는지 궁금합니다.",
    "매매로 집을 알아보는 중인데 이 근처 매물 정보를 좀 얻을 수 있을까 해서 전화했습니다.",
    "월세 물건을 구하고 있습니다. 조건 맞는 곳 있으면 안내받고 싶어서 연락드렸어요.",
    "사무실로 쓸 상가를 임차하려고 하는데 지금 나온 물건이 있는지 궁금해서 전화했습니다.",
    "가족과 함께 살 집을 매수하려고 알아보는 중입니다. 상담을 좀 받고 싶어요.",
    "투자 목적으로 매입할 물건을 찾고 있어서 문의드립니다. 몇 군데 후보를 비교해 보려고요.",
    "지금 살고 있는 곳 계약이 끝나가서 다음 집을 미리 알아보려고 연락드렸습니다.",
    "직장 근처로 이사를 계획 중이라 매물부터 확인하고 싶어서 전화했습니다.",
)

BUY_TARGETS = (
    "희망 지역은 {addr} 쪽이고, 중형 평형 아파트를 우선으로 보고 있습니다. 방은 최소 두 개는 있었으면 합니다.",
    "{addr}의 오피스텔이나 소형 아파트 중에서 조건에 맞는 곳을 찾고 있습니다. 혼자 지낼 예정이라 크기는 크지 않아도 됩니다.",
    "{addr} 인근 대형 평형 위주로 매매 물건을 알아보는 중입니다. 가족이 많아서 방이 넉넉해야 해요.",
    "출퇴근을 고려해서 {addr}의 역세권 빌라나 소형 주택을 보고 있습니다.",
    "{addr} 인근에서 사무실로 쓸 만한 상가를 찾고 있습니다. 전면이 넓은 자리면 좋겠습니다.",
    "아이 학교 문제로 {addr}의 중형 아파트 전세를 우선 알아보고 있습니다.",
    "{addr}의 소형 평형 중 공실 위주로 월세 물건을 찾고 있습니다. 바로 입주할 수 있는 곳이면 좋겠어요.",
    "{addr}과 같은 신축 오피스텔 매매 물건이 있는지 궁금합니다.",
    "{addr} 대형 평형 중 주차가 넉넉한 아파트를 우선 보고 있습니다. 차가 두 대라 주차가 중요해요.",
    "투자용으로 {addr}의 소형 주거 상품을 검토하고 있습니다.",
)

BUY_TERMS = (
    "예산은 인근 시세 범위 안에서 생각하고 있고, 입주는 두 달 뒤쯤 가능하면 좋겠습니다. 조금 더 늦어져도 크게 상관은 없어요.",
    "대출을 함께 이용할 예정이라 정확한 상한은 은행 확인 후 말씀드릴 수 있습니다. 이번 주 안에 은행에 다녀올 생각입니다.",
    "지금 사는 곳 계약이 다음 달 만료라 그 안에 이사할 수 있는 물건이면 좋겠습니다.",
    "보증금과 월세 조건은 협의 가능한 범위에서 맞춰볼 생각입니다. 조건이 너무 빡빡하지 않으면 좋겠어요.",
    "당장 급한 건 아니고 조건이 맞으면 몇 달 뒤 입주도 괜찮습니다. 천천히 좋은 매물을 찾고 싶습니다.",
    "현재 자금은 어느 정도 준비돼 있고 나머지는 대출로 진행할 계획입니다.",
    "가족 수가 늘어날 예정이라 방 개수가 넉넉한 곳을 우선으로 보고 있습니다.",
    "직접 거주할 목적이라 공실이거나 입주 시기가 명확한 물건이면 좋겠습니다.",
    "권리관계나 대출 여부는 매물이 정해지면 서류로 다시 확인하려고 합니다.",
    "정확한 예산 상한은 아직 가족과 협의 중이라 우선은 범위로만 말씀드릴 수 있습니다.",
)

BUY_REQUESTS = (
    "조건에 맞는 매물이 나오면 사진이나 기본 정보부터 먼저 보내주실 수 있을까요. 여러 개 비교해 보고 싶어요.",
    "방문 가능한 물건이 있으면 일정 맞춰서 한번 보러 가고 싶습니다. 주말이면 더 좋습니다.",
    "권리관계나 관리비 같은 기본 사항도 같이 안내해 주시면 좋겠습니다.",
    "비슷한 조건의 다른 물건도 있으면 함께 비교해서 보고 싶습니다.",
    "가격이나 조건이 바뀌면 그때그때 알려주실 수 있을까요.",
    "당장 계약을 결정한 상태는 아니라 우선 후보 위주로 안내받고 싶습니다.",
    "제가 놓친 조건이 있으면 상담하시면서 같이 짚어주시면 감사하겠습니다.",
    "여러 곳을 비교하고 있어서 확정되면 다시 연락드리겠습니다.",
    "필요한 서류나 준비 사항이 있으면 미리 알려주시면 좋겠습니다.",
    "우선 나온 물건부터 안내받고, 조건은 상담하면서 조율하고 싶습니다.",
)

BUY_CLOSINGS = (
    f"연락은 {PLACEHOLDER_PHONE}으로 주시면 확인하겠습니다.",
    f"그러면 매물 정리되는 대로 {PLACEHOLDER_PHONE}으로 알려주세요.",
    f"네, {PLACEHOLDER_PHONE}으로 연락 주시면 바로 확인하겠습니다.",
    f"다른 일정이 있어서 {PLACEHOLDER_PHONE}으로 남겨주시면 확인 후 답 드리겠습니다.",
    f"우선 여기까지 말씀드리고 자세한 건 {PLACEHOLDER_PHONE}으로 이어가겠습니다.",
    f"제 번호는 {PLACEHOLDER_PHONE}입니다. 낮에는 통화가 어려우니 문자도 괜찮습니다.",
)

BUY_PATTERNS = (
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
    buy_request = records(
        label=LABEL,
        id_prefix="f2-buy-request-safe",
        group_prefix="buy-request-safe-blueprint",
        count=COUNT,
        openings=BUY_OPENINGS,
        subjects=BUY_TARGETS,
        contexts=BUY_TERMS,
        requests=BUY_REQUESTS,
        closings=BUY_CLOSINGS,
        patterns=BUY_PATTERNS,
    )
    validate(buy_request, LABEL, COUNT)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        OUTPUT_DIR / "f2_buy_request_scenarios.privacy_safe.v0.4.jsonl",
        buy_request,
    )


if __name__ == "__main__":
    main()
