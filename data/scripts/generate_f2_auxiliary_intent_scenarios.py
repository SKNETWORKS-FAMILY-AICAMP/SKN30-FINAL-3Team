from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "f2_llm" / "working"
DATASET_VERSION = "0.2.0"
SOURCE_TYPE = "fully_synthetic_from_abstract_blueprint"


CO_OPENINGS = (
    "안녕하세요, [가상중개업소-{n}]에서 공동중개 가능 여부를 확인하려고 연락드렸습니다.",
    "저희는 [가상지역-{n}]의 [가상중개업소-{n}]인데, 잠깐만요, 손님 조건과 맞는 물건이 보여 전화드렸어요.",
    "[가상중개업소-{n}] 실무자입니다. 다른 사무실끼리 역할을 나눠 진행할 수 있는 건인지 확인 부탁드립니다.",
    "중개사님, 광고에 올라온 물건 하나 때문에요. 저희 쪽 손님과 연결해도 되는지 먼저 여쭤보려고요.",
    "[가상중개업소-{n}] 담당자인데 양쪽 의뢰인 조건을 맞춰볼 수 있을 것 같아서 연락드렸습니다.",
    "저희가 보유한 매물 자료를 귀사 고객에게 보여드려도 될지 사무실 간 협의를 요청드립니다.",
    "공동중개로 진행할 수 있는 건인지 확인하려고 [가상중개업소-{n}]에서 전화했습니다.",
    "귀사 매물 보고 연락드린 중개업소입니다. 아직 손님에게 확정적으로 말한 건 아니고 상태부터 확인하려고요.",
    "저희 손님 조건을 보다가 귀사 물건이 생각나서요. 두 사무실이 같이 안내할 수 있을까요.",
    "매물 쪽은 저희가 맡고 있고 반대편 고객을 찾는 중입니다. 귀사에 맞는 손님이 있는지 문의드려요.",
)

CO_TARGETS = (
    "대상은 [가상단지-{n}] [가상동-{n}] [가상호-{n}]의 중형 매매 물건이고 저희 쪽에는 비슷한 예산의 매수 희망자가 있습니다.",
    "저희가 맡은 고객은 [가상지역-{n}]의 전세 물건을 찾고 있으며 귀사의 [가상매물-{n}]이 조건에 가까워 보입니다.",
    "[가상상가-{n}]의 임대차 승계 매물에 관심을 보인 투자 고객이 있어 현재 진행 여부를 확인하고 싶습니다.",
    "저희가 접수한 [가상오피스텔-{n}] 월세 물건을 귀사 고객에게 함께 안내할 수 있는지 확인 부탁드립니다.",
    "귀사에 등록된 [가상빌라-{n}] 전세 물건을 찾는 고객이 저희 쪽에 있어 세부 조건을 맞춰보려 합니다.",
    "[가상단지-{n}] 대형 평형을 보유한 임대인과 비슷한 조건을 찾는 귀사 고객을 연결하는 건입니다.",
    "저희 고객은 입주 시기를 협의할 수 있는 매매 물건을 찾고 있고 [가상매물-{n}]을 검토하고 있습니다.",
    "귀사 고객이 원하는 지역과 저희가 보유한 [가상단지-{n}] 매물 조건이 유사해 자료를 교환하고 싶습니다.",
    "[가상건물-{n}]의 1층 점포 임차 수요가 있어 저희가 확보한 임대인 의뢰와 함께 검토하려 합니다.",
    "저희 쪽 매수 고객이 [가상지역-{n}] 소형 주거 상품을 찾고 있어 귀사 보유 물건과 비교하려고 합니다.",
)

CO_TERMS = (
    "표시 가격은 시세 범위에서 협의 가능하다고 들었고 입주 가능 시점은 두 달 뒤입니다.",
    "보증금과 월세 조건은 아직 조정 가능하지만 정확한 금액은 양측 확인이 필요합니다.",
    "현재 임차인이 있어 방문은 평일 저녁으로 사전 조율해야 하고 계약 만기도 확인해야 합니다.",
    "물건은 공실이지만 권리관계와 대출 조건은 서류를 받은 뒤 다시 확인해야 합니다.",
    "고객의 예산과 희망 시기는 전달받았으나 최종 의사와 자금 일정은 재확인이 필요합니다.",
    "소유자 측 희망 조건과 고객 측 제안 사이에 차이가 있어 중개사끼리 먼저 범위를 맞추면 좋겠습니다.",
    "현장 안내는 가능하지만 열쇠 수령과 방문 시간은 각 담당자가 사전에 확인해야 합니다.",
    "광고 내용 중 면적과 관리비는 최신 자료인지 확인이 필요하며 확정 전에는 고객에게 단정하지 않겠습니다.",
    "계약 일정은 빠르게 진행할 수 있지만 특약과 잔금 조건은 양측 당사자의 승인을 받아야 합니다.",
    "현재 접수된 조건은 참고용이며 가격과 입주일은 실제 협의 과정에서 달라질 수 있습니다.",
)

CO_REQUESTS = (
    "매물의 현재 유효 여부와 공동 안내 가능한 시간을 알려주시고 확인된 자료만 공유해 주세요.",
    "고객 정보는 가명으로 먼저 전달하고 방문이 확정되면 필요한 범위에서 담당자끼리 연락하겠습니다.",
    "중개보수 배분과 광고 주체, 계약서 작성 역할은 고객 안내 전에 사무소 간에 합의하고 싶습니다.",
    "귀사 담당자와 저희 담당자의 역할을 정한 뒤 양측에 같은 조건으로 설명해 주시면 좋겠습니다.",
    "소유자 또는 고객의 동의 없이 연락처를 전달하지 말고 우선 가능 여부만 회신해 주세요.",
    "현장 방문 전 권리관계 자료와 기본 조건을 상호 대조하고 불일치가 있으면 보류하겠습니다.",
    "공동 광고는 아직 진행하지 말고 매물 상태와 의뢰 권한을 먼저 확인해 주세요.",
    "계약 가능성이 확인되면 양측 담당자가 함께 통화해 가격과 일정을 정리했으면 합니다.",
    "동일 물건의 중복 접수 여부를 확인하고 기존 협업 건이 있다면 그 사실도 알려주세요.",
    "상대방에게 확정 조건처럼 전달하기 전에 각 사무소가 의뢰인에게 한 번씩 재확인해 주세요.",
)

CO_CLOSINGS = (
    "가능 여부만 확인해서 [가상업무연락수단-{n}]으로 회신 부탁드립니다.",
    "담당자끼리 이야기할 수 있게 [가상업무연락수단-{n}]으로 연락 남겨주세요.",
    "자료는 [가상업무연락수단-{n}]으로 주시면 의뢰인 확인 뒤 다시 말씀드리겠습니다.",
    "오늘 안에 결정하실 필요는 없고 확인되는 대로 [가상업무연락수단-{n}]에 알려주세요.",
    "그러면 양쪽 조건부터 대조해 보고 [가상업무연락수단-{n}]으로 이어서 협의하겠습니다.",
)


INQUIRY_OPENINGS = (
    "안녕하세요, 부동산 거래 절차가 궁금해서 일반적인 내용만 문의드리려고 전화했습니다.",
    "아직 매물이나 고객을 등록하려는 것은 아니고 제도와 준비 사항을 알아보는 중입니다.",
    "구체적인 계약 계획은 정하지 않았는데 부동산 관련 기본 정보를 확인하고 싶습니다.",
    "인터넷에서 본 내용이 맞는지 확인하려고 연락드렸고 지금은 상담만 받고 싶습니다.",
    "당장 거래할 대상은 없지만 나중을 대비해 필요한 절차를 미리 알아보려고 합니다.",
    "특정 매물을 소개받으려는 전화는 아니고 일반적인 중개 절차에 대해 질문이 있습니다.",
    "가족과 상의하기 전에 기본 개념을 정리하고 싶어서 정보 문의로 연락드렸습니다.",
    "아직 예산이나 일정이 정해지지 않아 우선 시장에서 통상 어떻게 처리하는지 궁금합니다.",
    "계약을 의뢰하기 전 단계라 개인정보나 구체 주소 없이 원칙만 설명받고 싶습니다.",
    "부동산을 알아보기 시작한 단계라 특정 물건 등록 없이 몇 가지를 물어보려 합니다.",
)

INQUIRY_QUESTIONS = (
    "매매 계약을 진행할 때 계약금과 중도금, 잔금 일정은 보통 어떤 순서로 정하는지 궁금합니다.",
    "전세 계약 전에 등기사항과 선순위 권리를 어느 시점에 확인하는지 일반적인 절차를 알려주세요.",
    "월세 보증금과 차임을 비교할 때 어떤 항목을 함께 살펴보는지 설명을 듣고 싶습니다.",
    "중개보수는 어떤 기준으로 계산하고 실제 금액은 언제 확정하는지 궁금합니다.",
    "아파트를 보러 갈 때 미리 준비하거나 확인해야 할 기본 항목에는 무엇이 있나요.",
    "임대차 계약 갱신과 새 계약의 차이를 중개 현장에서는 어떻게 구분하는지 알고 싶습니다.",
    "공동명의 부동산을 거래할 때 일반적으로 어떤 사람들의 확인이 필요한지 궁금합니다.",
    "대리인이 계약에 참여하면 위임 관계를 어떤 서류로 확인하는지 원칙을 설명해 주세요.",
    "공실 물건과 임차인이 있는 물건을 살펴볼 때 확인 사항이 어떻게 다른지 궁금합니다.",
    "매물 광고에서 면적과 관리비, 입주 가능일은 어떤 자료를 기준으로 확인해야 하나요.",
)

INQUIRY_CONTEXTS = (
    "가령 [가상지역-{n}]의 중형 아파트를 나중에 검토할 수는 있지만 지금 정해진 단지나 동호수는 없습니다.",
    "예시로 [가상단지-{n}] 같은 곳을 보고 있지만 가격이나 거래 유형을 결정한 상태는 아닙니다.",
    "주변에서 들은 사례가 서로 달라 확인하는 것이며 제 소유 물건이나 구체 고객 정보는 제공하지 않겠습니다.",
    "정확한 판단은 서류와 당사자 상황에 따라 달라진다는 점을 알고 있고 일반적인 범위만 듣고 싶습니다.",
    "아직 방문 예약이나 매물 추천은 필요하지 않고 설명을 들은 뒤 가족과 다시 상의할 예정입니다.",
    "현재는 비교를 위한 사전 조사 단계라 희망 가격이나 입주일을 장부에 접수할 필요가 없습니다.",
    "[가상사례-{n}]처럼 가정한 상황을 묻는 것이며 실제 주소나 연락처와 연결되는 사례는 아닙니다.",
    "법률·세무 판단이 필요하면 별도 전문가에게 확인하겠고 중개 과정의 일반적인 흐름만 질문드립니다.",
    "설명을 들었다고 바로 계약하거나 의뢰하는 것은 아니며 조건이 정해지면 다시 연락하겠습니다.",
    "특정 상대방과 협의 중인 상황이 아니어서 가격 제안이나 현장 안내는 요청하지 않겠습니다.",
)

INQUIRY_FOLLOWUPS = (
    "준비해야 할 자료가 있다면 명칭만 알려주시고 실제 제출 여부는 거래가 구체화된 뒤 판단하겠습니다.",
    "온라인에서 확인할 수 있는 공개 정보와 중개사에게 별도로 확인할 내용을 구분해서 설명해 주세요.",
    "상황에 따라 답이 달라지는 부분은 확정적으로 말하지 말고 추가 확인이 필요하다고 알려주세요.",
    "현재 단계에서는 제 개인정보나 조건을 따로 접수하지 않으셔도 됩니다.",
    "구체적인 조건이 생기면 다시 연락드릴 테니 오늘은 등록 없이 안내만 부탁드려요.",
    "비용이나 기간을 단정하기 어렵다면 통상적인 범위와 변수가 무엇인지 정도만 안내해 주세요.",
    "특정 매물을 권유하기보다 제가 나중에 확인할 체크리스트 중심으로 설명해 주시면 좋겠습니다.",
    "문의 내용이 중개 범위를 벗어나면 담당 기관이나 전문가 확인이 필요하다고 구분해 주세요.",
    "답변을 들은 뒤 별도의 후속 연락을 요청하지 않을 예정이니 상담 기록만 남겨주세요.",
    "등록 의사가 확정되기 전에는 매도나 매수 의뢰로 처리하지 말아 주세요.",
)

INQUIRY_CLOSINGS = (
    "추가 자료는 제가 [가상안내채널-{n}]에서 찾아볼게요. 오늘은 설명만 들으면 됩니다.",
    "아, 네, 이해했습니다. 가족과 이야기해 보고 필요하면 나중에 다시 연락드릴게요.",
    "조건이 정해진 건 아니라서 지금은 여기까지만 여쭤보겠습니다.",
    "공개된 안내가 있으면 [가상안내채널-{n}] 위치만 알려주세요. 따로 연락 주실 필요는 없습니다.",
    "네, 아직 뭘 사고팔겠다는 건 아니고 궁금한 점이 해결됐습니다. 감사합니다.",
)


CO_PATTERNS = (
    ("opening", "subject", "context", "request", "closing"),
    ("subject", "opening", "request", "closing"),
    ("opening", "request", "subject", "context"),
    ("opening", "subject", "closing"),
    ("context", "opening", "subject", "request", "closing"),
    ("opening", "subject", "request"),
    ("subject", "context", "opening", "request"),
    ("opening", "context", "subject", "closing"),
    ("request", "opening", "subject", "context", "closing"),
    ("opening", "subject", "context", "request"),
)

INQUIRY_PATTERNS = (
    ("subject", "closing"),
    ("opening", "subject"),
    ("subject", "context"),
    ("opening", "subject", "closing"),
    ("subject", "request"),
    ("context", "subject", "closing"),
    ("opening", "subject", "request"),
    ("subject", "opening"),
    ("request", "subject", "closing"),
    ("opening", "subject", "context"),
)


def records(
    *,
    label: str,
    id_prefix: str,
    group_prefix: str,
    openings: tuple[str, ...],
    subjects: tuple[str, ...],
    contexts: tuple[str, ...],
    requests: tuple[str, ...],
    closings: tuple[str, ...],
    patterns: tuple[tuple[str, ...], ...],
) -> list[dict[str, object]]:
    generated: list[dict[str, object]] = []
    for index in range(1, 51):
        offset = index - 1
        block = offset // 10
        number = f"{index:02d}"
        fragments = {
            "opening": openings[offset % len(openings)],
            "subject": subjects[(offset * 3 + block) % len(subjects)],
            "context": contexts[(offset * 3 + block) % len(contexts)],
            "request": requests[(offset * 7 + block * 2) % len(requests)],
            "closing": closings[offset % len(closings)],
        }
        transcript = " ".join(
            fragments[name].format(n=number) for name in patterns[offset % len(patterns)]
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


def validate(rows: list[dict[str, object]], label: str) -> None:
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
    if len(rows) != 50:
        raise ValueError(f"{label}: expected 50 rows, got {len(rows)}")
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
    if any(not 60 <= len(str(row["transcript"])) <= 500 for row in rows):
        raise ValueError(f"{label}: transcript length outside expected range")
    explicit_label_count = sum(label in str(row["transcript"]) for row in rows)
    if explicit_label_count > 10:
        raise ValueError(f"{label}: explicit label leakage in {explicit_label_count} rows")

    forbidden_patterns = (
        re.compile(r"01[016789]-?\d{3,4}-?\d{4}"),
        re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    )
    for row in rows:
        transcript = str(row["transcript"])
        if any(pattern.search(transcript) for pattern in forbidden_patterns):
            raise ValueError(f"{label}: possible personal data in {row['scenario_id']}")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    co_brokerage = records(
        label="공동중개",
        id_prefix="f2-co-brokerage-safe",
        group_prefix="co-brokerage-safe-blueprint",
        openings=CO_OPENINGS,
        subjects=CO_TARGETS,
        contexts=CO_TERMS,
        requests=CO_REQUESTS,
        closings=CO_CLOSINGS,
        patterns=CO_PATTERNS,
    )
    general_inquiry = records(
        label="단순문의",
        id_prefix="f2-general-inquiry-safe",
        group_prefix="general-inquiry-safe-blueprint",
        openings=INQUIRY_OPENINGS,
        subjects=INQUIRY_QUESTIONS,
        contexts=INQUIRY_CONTEXTS,
        requests=INQUIRY_FOLLOWUPS,
        closings=INQUIRY_CLOSINGS,
        patterns=INQUIRY_PATTERNS,
    )
    validate(co_brokerage, "공동중개")
    validate(general_inquiry, "단순문의")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        OUTPUT_DIR / "f2_co_brokerage_scenarios.privacy_safe.v0.2.jsonl",
        co_brokerage,
    )
    write_jsonl(
        OUTPUT_DIR / "f2_general_inquiry_scenarios.privacy_safe.v0.2.jsonl",
        general_inquiry,
    )


if __name__ == "__main__":
    main()
