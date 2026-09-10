"""F2 장부 필드 추출·근거·요약 학습·평가용 합성 full-output v0.5 초안을 생성한다.

v0.4에서 바뀐 점은 네 가지다.

1. 장부 배정을 blueprint 밖으로 꺼내 (장부, 상담 유형) 셀별 목표 건수로 직접 통제한다.
2. 분할 단위를 blueprint 하나에서 (blueprint, 대화 형태) 조합으로 쪼개 그룹 수를 늘린다.
3. 필드 값이 없는 대화 문장에만 STT 표기 흔들림을 넣는다.
4. 대화 형태 10개 중 3개는 핵심 사실만 남겨 짧은 상담에서도 필드 정답이 존재하게 한다.

필드 제안이 금지된 구간(장부 불일치·기타상담)은 재포장 도구가 짧은 사례를 따로 공급한다.
이 생성기도 같은 구간을 긴 사례로 남겨 둔다. 빈 필드 정답이 전부 짧은 문장에만 붙으면 모델이
길이로 필드 유무를 가르는 지름길을 배우기 때문이다.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 상담 로그 초안 규칙을 재포장 도구와 하나로 유지한다. 두 산출물의 summary 형식이 갈라지면
# 모델이 필드 유무를 요약 문체로 구분해 버린다.
from rewrap_classification_to_full_output import is_ledger_mismatch, key_sentences

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    ROOT / "f2_llm" / "working" / "f2_full_output_scenarios.privacy_safe.v0.5.jsonl"
)
DATASET_VERSION = "0.5.0"
SOURCE_TYPE = "fully_synthetic_from_deterministic_blueprint"
REVIEW_STATUS = "generated_unreviewed"
PLACEHOLDER_PHONE = "010-1234-5678"

# 한 blueprint를 몇 가지 대화 형태로 펼칠지. 형태가 분할 단위의 일부라 그룹 수를 좌우한다.
SHAPES_PER_BLUEPRINT = 10
# 핵심 사실과 본인 식별 문장만 남기는 압축형. shape는 그룹 키의 일부이므로
# 압축형과 확장형이 서로 다른 split으로 헤어져도 그룹 내 누수는 생기지 않는다.
COMPACT_SHAPES = frozenset({1, 2, 3})


@dataclass(frozen=True)
class CellSpec:
    """(현재 장부, 상담 유형) 조합과 그 조합을 만들 blueprint·반복 수."""

    slug: str
    label: str
    ledger_type: str
    blueprints: tuple[int, ...]
    rows_per_group: int
    index_base: int


# blueprint 0~7은 장부가 맞는 필드 보유 사례, 8~9는 장부가 어긋난 사례로 이미 나뉘어 있다.
# 기타상담은 OTHER_BLUEPRINTS를 앞뒤로 갈라 그룹마다 장부를 하나로 고정한다.
CELLS = (
    CellSpec("sell-on-property", "매도의뢰", "매물장", tuple(range(8)), 4, 0),
    CellSpec("buy-on-buyer", "매수문의", "구입장", tuple(range(8)), 4, 3000),
    CellSpec("buy-on-property", "매수문의", "매물장", (8, 9), 2, 6000),
    CellSpec("sell-on-buyer", "매도의뢰", "구입장", (8, 9), 2, 9000),
    CellSpec("other-on-property", "기타상담", "매물장", tuple(range(5)), 2, 12000),
    CellSpec("other-on-buyer", "기타상담", "구입장", tuple(range(5, 10)), 2, 15000),
)

LABEL_IDENTITY_OFFSET = {"매도의뢰": 0, "매수문의": 1000, "기타상담": 2000}

STT_FILLERS = ("어", "그", "음", "저기")

LABELS = ("매도의뢰", "매수문의", "기타상담")
LEDGERS = ("매물장", "구입장")
PROPERTY_FIELDS = frozenset(
    {
        "단지",
        "평형",
        "동",
        "호",
        "타입",
        "방향",
        "현상태",
        "현재 보증금",
        "현재 차임",
        "융자",
        "만기일",
        "접수일",
        "현매물",
        "진행상태",
        "명도 조건",
        "매매가",
        "전세보증금",
        "월세 보증금",
        "월세 차임",
        "확장 여부",
        "붙박이",
        "시설 상태",
        "임대인",
        "임대인 전화",
        "임차인",
        "임차인 전화",
        "관련 중개업소",
        "담당자",
        "비고",
    }
)
BUYER_FIELDS = frozenset(
    {
        "접수일",
        "최종접촉일",
        "거래 구분",
        "희망 단지",
        "희망 지역",
        "희망 평형",
        "금액 원문",
        "이사일 원문",
        "구입자 이름",
        "구입자 별칭",
        "전화번호",
        "관련 중개업소",
        "진행단계",
        "완료 여부",
        "담당자",
        "분류",
        "비고",
    }
)
ALLOWED_FIELDS = {"매물장": PROPERTY_FIELDS, "구입장": BUYER_FIELDS}

CITIES = ("나린온시", "소보람시", "별밭시", "온새미시", "하늬바람시")
GUS = ("바오름구", "여울구", "다솜구", "새록구", "물빛구")
DONGS = ("수풀동", "별빛동", "고운동", "늘봄동", "솔바람동")
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
SYNTHETIC_NAMES = ("가온고객", "나래고객", "다온고객", "라온고객", "마루고객")
SYNTHETIC_BROKERAGES = (
    "가상한빛공인중개사",
    "가상라온공인중개사",
    "가상다온공인중개사",
)

DIALOGUE_OPENINGS = (
    "네, 확인된 정보와 아직 정하지 않은 내용을 나눠서 정리하겠습니다.",
    "말씀하시는 순서대로 들은 뒤 마지막에 빠진 내용이 있는지만 다시 확인하겠습니다.",
    "통화가 조금 길어져도 괜찮으니 확실한 내용과 추후 확인할 내용을 구분해 주세요.",
    "제가 중간에 짧게 되묻더라도 기존 내용을 바로 바꾸지는 않고 제안으로만 정리하겠습니다.",
    "주변 소리가 조금 들리지만 통화는 가능하니 천천히 말씀해 주세요.",
)
CUSTOMER_CONTEXTS = (
    "제가 메모해 둔 내용을 보면서 말해서 순서가 조금 앞뒤로 바뀔 수 있어요.",
    "아까 다른 곳에도 문의해서 들은 내용과 제가 확정한 내용이 섞이지 않게 부탁드릴게요.",
    "생각나는 대로 말씀드릴 테니 확실하지 않다고 한 부분은 빈칸으로 남겨 주세요.",
    "제가 말을 빨리 하는 편이라 숫자나 고유명사는 들은 그대로 다시 확인해 주세요.",
    "한 번에 정리해서 말하려고 했는데 중간중간 빠진 내용이 생각날 수도 있습니다.",
    "가족과 상의 중인 내용도 있어서 오늘 확정한 것만 기준으로 봐 주세요.",
)
INTERRUPTIONS = (
    "아, 잠깐만요. 방금 알림이 와서 어디까지 말씀드렸는지 잠시 헷갈렸네요.",
    "제가 방금 표현을 조금 이상하게 했는데 새로운 조건을 추가한 건 아닙니다.",
    "통화가 잠깐 끊기는 것 같았어요. 들린 부분만 기준으로 하고 추측하지 말아 주세요.",
    "다른 사례와 섞어 말할 뻔했네요. 지금 통화에서 확인된 내용만 보시면 됩니다.",
    "잠시만요, 메모를 다시 보고 이어서 말씀드릴게요. 아직 말하지 않은 건 확정이 아닙니다.",
    "앞에서 말씀드린 내용을 취소한 건 아니고 설명 순서만 다시 잡는 중입니다.",
)
AGENT_ACKNOWLEDGEMENTS = (
    "네, 지금까지 확실하게 들린 부분만 임시 제안으로 구분하겠습니다.",
    "알겠습니다. 원문에 없는 값은 채우지 않고 확인이 필요한 부분은 따로 표시하겠습니다.",
    "서로 다르게 들린 내용은 임의로 하나를 고르지 않고 다시 확인할 항목으로 남기겠습니다.",
    "말씀하지 않은 항목은 빈 상태로 두고 상담 내용만 이어서 듣겠습니다.",
    "기존 장부 값은 바로 덮어쓰지 않고 검토할 수 있는 형태로만 정리하겠습니다.",
)
MID_CALL_REVIEWS = (
    (
        "중간 확인입니다. 비교 사례나 제가 예시로 든 값은 장부 후보에 넣지 않고, 직접 확인해 주신 내용만 남기겠습니다.",
        "네, 주변 이야기는 참고일 뿐이고 제가 오늘 확정해서 말한 내용과 구분해 주세요.",
    ),
    (
        "지금까지 들은 순서와 장부 필드 순서가 달라도 원문 근거를 함께 보여드리겠습니다. 틀리면 저장 전에 고칠 수 있습니다.",
        "좋습니다. 제가 반복하거나 말을 고쳐도 마지막에 임의로 추측해서 합치지는 말아 주세요.",
    ),
    (
        "아직 언급되지 않은 항목은 공란으로 두겠습니다. 비슷한 매물의 조건을 가져와 채우지도 않겠습니다.",
        "맞아요. 오늘 통화에서 들리지 않은 내용은 나중에 확인할 항목으로 남겨 주세요.",
    ),
    (
        "제가 이해한 내용은 상담 로그와 필드 제안을 나눠 보여드리고, 근거가 없는 값은 제안하지 않겠습니다.",
        "네, 설명을 위한 말과 실제로 장부에 넣을 조건이 섞이지 않도록 한 번 더 확인해 주세요.",
    ),
    (
        "통화가 길어져 앞부분과 표현이 달라질 수 있으니, 충돌하는 값이 나오면 어느 하나를 선택하지 않고 확인 필요로 표시하겠습니다.",
        "그렇게 해 주세요. 확실하지 않은 숫자나 날짜는 그럴듯하게 보완하면 안 됩니다.",
    ),
)
CONVERSATION_CLOSINGS = (
    "빠뜨린 내용이 있더라도 임의로 보완하지 말고 다음 통화에서 다시 확인해 주세요.",
    "오늘 정리된 내용을 먼저 보고 잘못 들린 부분이 있으면 제가 직접 수정하겠습니다.",
    "확정되지 않은 내용은 나중에 다시 말씀드릴 테니 이번에는 확인된 것만 남겨 주세요.",
    "상담 결과를 바로 저장하지 말고 제가 화면에서 한 번 검토할 수 있게 해 주세요.",
    "같은 말을 반복했더라도 임의로 합쳐서 다른 값으로 만들지는 말아 주세요.",
)

REPEAT_CUE = "방금 말씀하신 핵심 부분을 같은 표현으로 한 번만 다시 확인하겠습니다."
CLOSING_CUE = "네, 자동 저장하지 않고 제안 목록과 상담 로그 초안으로만 보여드리겠습니다."

# STT 표기 흔들림을 넣어도 되는 문장. 생성기가 맥락용으로 끼워 넣는 문장만 해당한다.
# 상담 내용을 담은 문장은 필드 값과 근거, 본인 이름 발화를 품고 있어 원문 그대로 두어야 한다.
FILLER_TEXTS = frozenset(
    DIALOGUE_OPENINGS
    + CUSTOMER_CONTEXTS
    + INTERRUPTIONS
    + AGENT_ACKNOWLEDGEMENTS
    + CONVERSATION_CLOSINGS
    + tuple(line for review in MID_CALL_REVIEWS for line in review)
    + (REPEAT_CUE, CLOSING_CUE)
)

Fragment = tuple[str, dict[str, str]]


def values(index: int) -> dict[str, str]:
    """실제 사람·주소와 연결되지 않는 반복 가능한 합성 슬롯 값을 만든다."""

    complex_name = COMPLEXES[index % len(COMPLEXES)]
    city = CITIES[index % len(CITIES)]
    gu = GUS[(index * 3) % len(GUS)]
    dong_name = DONGS[(index * 2) % len(DONGS)]
    return {
        "city": city,
        "gu": gu,
        "region": f"{city} {gu} {dong_name}",
        "complex": complex_name,
        "building": f"{101 + index % 18}동",
        "unit": f"{201 + (index * 37) % 1500}호",
        "area": f"{20 + index % 20}평",
        "type": f"{59 + (index % 4) * 15}A",
        "direction": ("남향", "남동향", "동향", "서향")[index % 4],
        "sale_price": f"{6 + index % 9}억 {index % 5 * 1000}만 원",
        "jeonse_price": f"{3 + index % 7}억 {index % 4 * 1000}만 원",
        "deposit": f"{1000 + index % 8 * 500}만 원",
        "monthly": f"{60 + index % 12 * 5}만 원",
        "date": f"2026년 {9 + index % 4}월 {1 + index % 27}일",
        "move_date": f"2027년 {1 + index % 6}월 {1 + index % 27}일",
        "name": SYNTHETIC_NAMES[index % len(SYNTHETIC_NAMES)],
        "tenant": f"합성임차인{index % 10}",
        "brokerage": SYNTHETIC_BROKERAGES[index % len(SYNTHETIC_BROKERAGES)],
        "manager": f"합성담당자{index % 7}",
    }


def fragment(text: str, **fields: str) -> Fragment:
    return text, fields


def apply_stt_noise(text: str, seed: int) -> str:
    """필드 값이 없는 대화 문장에만 STT 표기 흔들림을 넣는다.

    필드 근거 문장은 건드리지 않는다. evidence는 원문 부분문자열이어야 하고 필드 값도 원문
    표현이어야 해서, 값이 들어간 문장을 흔들면 정답 계약이 깨진다. 실제 STT 오류는 값 자체도
    망가뜨리므로 이 축은 표면 노이즈만 다룬다는 한계를 manifest에 적는다.
    """

    mode = seed % 4
    if mode == 0:
        return text
    if mode == 1:
        return f"{STT_FILLERS[seed % len(STT_FILLERS)]}, {text}"
    if mode == 2:
        # STT가 문장 끝 구두점을 놓치는 경우.
        return text.rstrip(".")
    words = text.split(" ")
    if len(words) < 3:
        return text
    # 어절 경계가 뭉개져 앞 두 어절이 붙는 경우.
    return " ".join([words[0] + words[1], *words[2:]])


def expand_dialogue(
    *, label: str, blueprint: int, shape: int, fragments: list[Fragment]
) -> tuple[list[Fragment], list[str]]:
    """핵심 사실 사이에 안전한 대화 맥락을 끼워 실제 통화처럼 길고 비정형으로 만든다.

    대화 형태는 shape가 결정한다. 같은 (blueprint, shape)를 공유하는 행은 같은 그룹이 되고
    슬롯 값만 달라진다. 분할은 그룹 단위라 이 행들이 서로 다른 split으로 흩어지지 않는다.
    """

    shift = shape % len(fragments)
    ordered = fragments[shift:] + fragments[:shift]
    if shape in COMPACT_SHAPES:
        tags = ["short_dialogue", "compact_dialogue", "unlabeled_multi_speaker_stt"]
        if shift:
            tags.append("reordered_facts")
        if label == "기타상담":
            tags.append("no_field_proposal")
        return ordered, tags

    expanded: list[Fragment] = [
        fragment(DIALOGUE_OPENINGS[(blueprint + shape) % len(DIALOGUE_OPENINGS)]),
        fragment(CUSTOMER_CONTEXTS[(blueprint * 2 + shape) % len(CUSTOMER_CONTEXTS)]),
    ]
    for position, item in enumerate(ordered):
        expanded.append(item)
        if position == 0:
            expanded.append(
                fragment(AGENT_ACKNOWLEDGEMENTS[(blueprint + shape * 2) % len(AGENT_ACKNOWLEDGEMENTS)])
            )
        elif position == 1:
            expanded.append(
                fragment(INTERRUPTIONS[(blueprint * 3 + shape) % len(INTERRUPTIONS)])
            )
    repeated = shape % 4 == 0
    if repeated:
        expanded.extend(
            [
                fragment(REPEAT_CUE),
                ordered[0],
            ]
        )
    review = MID_CALL_REVIEWS[(blueprint * 2 + shape) % len(MID_CALL_REVIEWS)]
    expanded.extend(fragment(text) for text in review)
    expanded.extend(
        [
            fragment(CONVERSATION_CLOSINGS[(blueprint + shape * 3) % len(CONVERSATION_CLOSINGS)]),
            fragment(CLOSING_CUE),
        ]
    )

    noised: list[Fragment] = []
    noise_applied = False
    for position, (item_text, item_fields) in enumerate(expanded):
        if item_text not in FILLER_TEXTS:
            # 상담 내용 문장은 원문 그대로 둔다.
            noised.append((item_text, item_fields))
            continue
        changed = apply_stt_noise(item_text, blueprint * 7 + shape * 3 + position)
        noise_applied = noise_applied or changed != item_text
        noised.append((changed, item_fields))

    tags = ["long_dialogue", "unlabeled_multi_speaker_stt", "interleaved_context", "disfluency"]
    if shift:
        tags.append("reordered_facts")
    if repeated:
        tags.append("repeated_statement")
    if noise_applied:
        tags.append("stt_surface_noise")
    if label == "기타상담":
        tags.append("no_field_proposal")
    return noised, tags


def build_expected(
    *,
    label: str,
    ledger_type: str,
    fragments: list[Fragment],
    uncertainties: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    transcript = " ".join(text for text, _ in fragments)
    mismatch = (label == "매도의뢰" and ledger_type == "구입장") or (
        label == "매수문의" and ledger_type == "매물장"
    )
    allow_fields = not mismatch and label != "기타상담"
    fields: dict[str, str] = {}
    evidence: dict[str, str] = {}
    if allow_fields:
        for text, values_by_field in fragments:
            for field_name, value in values_by_field.items():
                fields[field_name] = value
                evidence[field_name] = text
    if fields:
        field_summary = ", ".join(f"{name} {value}" for name, value in fields.items())
        summary = f"{label} 상담의 확인된 조건: {field_summary}."
    elif mismatch:
        summary = (
            f"{label}로 판단했으나 현재 장부가 {ledger_type}이라 필드를 제안하지 않았습니다."
            f" 상담 요지: {key_sentences(transcript)}"
        )
    else:
        summary = (
            "장부 필드 제안 대상이 아닌 기타상담이라 상담 로그만 남깁니다."
            f" 상담 요지: {key_sentences(transcript)}"
        )
    if uncertainties:
        summary = f"{summary} 추가 확인: {'; '.join(uncertainties)}."
    return transcript, {
        "consultation_type": label,
        "ledger_mismatch": mismatch,
        "fields": fields,
        "evidence": evidence,
        "uncertainties": uncertainties or [],
        "summary": summary,
    }


def property_fragments(blueprint: int, index: int) -> tuple[str, list[Fragment], list[str]]:
    value = values(index)
    address = fragment(
        f"{value['complex']} {value['building']} {value['unit']} 매물을 접수해 주세요.",
        단지=value["complex"],
        동=value["building"],
        호=value["unit"],
    )
    if blueprint == 0:
        return "매물장", [
            fragment("제가 소유한 주택을 매도하려고 연락드렸습니다."),
            address,
            fragment(f"희망 매매가는 {value['sale_price']}입니다.", 매매가=value["sale_price"]),
        ], []
    if blueprint == 1:
        return "매물장", [
            fragment("전세 임대 의뢰를 접수하려고 합니다."),
            address,
            fragment(
                f"전세보증금은 {value['jeonse_price']}이고 현재 보증금도 {value['jeonse_price']}이며 현재는 공실입니다.",
                전세보증금=value["jeonse_price"],
                **{"현재 보증금": value["jeonse_price"]},
                현상태="공실",
            ),
            fragment(f"입주는 {value['move_date']}부터 가능합니다.", **{"명도 조건": value["move_date"]}),
        ], []
    if blueprint == 2:
        return "매물장", [
            fragment("월세로 내놓을 집이 있습니다."),
            address,
            fragment(
                f"월세 보증금은 {value['deposit']}, 월세는 {value['monthly']}입니다.",
                **{
                    "월세 보증금": value["deposit"],
                    "월세 차임": value["monthly"],
                    "현재 보증금": value["deposit"],
                    "현재 차임": value["monthly"],
                },
            ),
            fragment(f"융자는 {1000 + index % 5 * 500}만 원 남아 있습니다.", 융자=f"{1000 + index % 5 * 500}만 원"),
        ], []
    if blueprint == 3:
        return "매물장", [
            address,
            fragment(
                f"{value['area']} {value['type']} 타입이고 방향은 {value['direction']}입니다.",
                평형=value["area"],
                타입=value["type"],
                방향=value["direction"],
            ),
            fragment(
                "거실은 확장되어 있고 붙박이장이 있으며 시설 상태는 양호합니다.",
                **{"확장 여부": "확장", "붙박이": "붙박이장 있음", "시설 상태": "양호"},
            ),
        ], []
    if blueprint == 4:
        return "매물장", [
            address,
            fragment(
                f"접수일은 {value['date']}이고 현재 현매물로 광고 준비 중입니다.",
                접수일=value["date"],
                현매물="현매물",
                진행상태="광고 준비 중",
            ),
            fragment("잔금 후 일주일 이내 명도하는 조건입니다.", **{"명도 조건": "잔금 후 일주일 이내"}),
        ], []
    if blueprint == 5:
        return "매물장", [
            address,
            fragment(
                f"임대인은 {value['name']}이고 연락처는 {PLACEHOLDER_PHONE}입니다.",
                임대인=value["name"],
                **{"임대인 전화": PLACEHOLDER_PHONE},
            ),
            fragment(
                f"현재 임차인은 {value['tenant']}이고 임차인 전화는 {PLACEHOLDER_PHONE}이며 만기일은 {value['date']}입니다.",
                임차인=value["tenant"],
                **{"임차인 전화": PLACEHOLDER_PHONE},
                만기일=value["date"],
            ),
            fragment(
                f"관련 중개업소는 {value['brokerage']}, 담당자는 {value['manager']}입니다.",
                **{"관련 중개업소": value["brokerage"], "담당자": value["manager"]},
            ),
            fragment("비고에는 임차 일정 재확인이라고 적어 주세요.", 비고="임차 일정 재확인"),
        ], []
    if blueprint == 6:
        return "매물장", [
            address,
            fragment("가격은 8억에서 9억 사이로 생각하지만 아직 가족과 협의 중입니다."),
            fragment("정확한 희망 가격은 다음 상담에서 확정하겠습니다."),
        ], ["희망 가격이 범위로만 언급되어 매매가 확인 필요"]
    if blueprint == 7:
        return "매물장", [
            address,
            fragment("처음에는 7억이라고 말씀드렸지만 7억 5천만 원일 수도 있어 확인이 필요합니다."),
            fragment("가격은 확정하지 말고 주소 정보만 먼저 등록해 주세요."),
        ], ["서로 다른 희망 가격이 언급되어 매매가 확인 필요"]
    if blueprint == 8:
        return "구입장", [
            fragment("제가 소유한 매물을 팔려고 연락드렸습니다."),
            address,
            fragment(f"희망 매매가는 {value['sale_price']}입니다."),
        ], ["현재 구입장과 매도의뢰 상담 유형이 일치하지 않음"]
    return "구입장", [
        fragment("전세로 내놓을 임대 물건을 접수하려고 합니다."),
        address,
        fragment(f"전세보증금은 {value['jeonse_price']}입니다."),
    ], ["현재 구입장과 매도의뢰 상담 유형이 일치하지 않음"]


def buyer_fragments(blueprint: int, index: int) -> tuple[str, list[Fragment], list[str]]:
    value = values(index + 1000)
    if blueprint == 0:
        return "구입장", [
            fragment("주택 매매 매물을 찾고 있습니다.", **{"거래 구분": "매매"}),
            fragment(
                f"희망 단지는 {value['complex']}, 희망 평형은 {value['area']}입니다.",
                **{"희망 단지": value["complex"], "희망 평형": value["area"]},
            ),
            fragment(f"예산은 {value['sale_price']}입니다.", **{"금액 원문": value["sale_price"]}),
        ], []
    if blueprint == 1:
        return "구입장", [
            fragment("아파트 전세를 구하고 있습니다.", **{"거래 구분": "전세"}),
            fragment(
                f"희망 지역은 {value['region']}이고 {value['area']}를 원합니다.",
                **{"희망 지역": value["region"], "희망 평형": value["area"]},
            ),
            fragment(f"보증금은 {value['jeonse_price']}까지 가능합니다.", **{"금액 원문": value["jeonse_price"]}),
        ], []
    if blueprint == 2:
        return "구입장", [
            fragment("월세 주택을 알아보고 있습니다.", **{"거래 구분": "월세"}),
            fragment(f"희망 단지는 {value['complex']}입니다.", **{"희망 단지": value["complex"]}),
            fragment(
                f"조건은 보증금 {value['deposit']}에 월세 {value['monthly']}입니다.",
                **{"금액 원문": f"보증금 {value['deposit']}에 월세 {value['monthly']}"},
            ),
        ], []
    if blueprint == 3:
        return "구입장", [
            fragment("매매로 구입할 집을 찾고 있습니다.", **{"거래 구분": "매매"}),
            fragment(f"희망 지역은 {value['region']}입니다.", **{"희망 지역": value["region"]}),
            fragment(f"이사 희망일은 {value['move_date']}입니다.", **{"이사일 원문": value["move_date"]}),
            fragment(
                f"구입자는 {value['name']}이고 전화번호는 {PLACEHOLDER_PHONE}입니다.",
                **{"구입자 이름": value["name"], "전화번호": PLACEHOLDER_PHONE},
            ),
        ], []
    if blueprint == 4:
        return "구입장", [
            fragment(f"접수일은 {value['date']}이고 전세 상담입니다.", 접수일=value["date"], **{"거래 구분": "전세"}),
            fragment(
                f"최종 연락일도 {value['date']}입니다.",
                최종접촉일=value["date"],
            ),
            fragment(f"희망 단지는 {value['complex']}입니다.", **{"희망 단지": value["complex"]}),
            fragment(
                f"관련 중개업소는 {value['brokerage']}, 담당자는 {value['manager']}입니다.",
                **{"관련 중개업소": value["brokerage"], "담당자": value["manager"]},
            ),
        ], []
    if blueprint == 5:
        return "구입장", [
            fragment("월세 상담으로 아직 진행 중이고 완료되지 않았습니다.", **{"거래 구분": "월세", "진행단계": "진행 중", "완료 여부": "미완료"}),
            fragment(f"업무용 별칭은 합성고객{index % 20}입니다.", **{"구입자 별칭": f"합성고객{index % 20}"}),
            fragment(f"희망 지역은 {value['region']}입니다.", **{"희망 지역": value["region"]}),
            fragment("분류는 실거주이고 반려동물 가능 여부를 확인해 주세요.", 분류="실거주", 비고="반려동물 가능 여부 확인"),
        ], []
    if blueprint == 6:
        return "구입장", [
            fragment("매매로 집을 알아보고 있습니다.", **{"거래 구분": "매매"}),
            fragment(f"희망 단지는 {value['complex']}입니다.", **{"희망 단지": value["complex"]}),
            fragment("예산은 시세를 본 뒤 정하겠고 이사 날짜도 아직 모르겠습니다."),
        ], ["금액 조건과 이사일이 확정되지 않음"]
    if blueprint == 7:
        return "구입장", [
            fragment("전세를 구하고 있습니다.", **{"거래 구분": "전세"}),
            fragment("처음에는 별빛동이라고 했지만 솔바람동일 수도 있습니다."),
            fragment("희망 지역은 확인 후 다시 말씀드리겠습니다."),
        ], ["서로 다른 희망 지역이 언급되어 확인 필요"]
    if blueprint == 8:
        return "매물장", [
            fragment("매매로 살 집을 찾고 있습니다."),
            fragment(f"희망 단지는 {value['complex']}이고 예산은 {value['sale_price']}입니다."),
        ], ["현재 매물장과 매수문의 상담 유형이 일치하지 않음"]
    return "매물장", [
        fragment("전세로 들어갈 집을 찾고 있습니다."),
        fragment(f"희망 지역은 {value['region']}이고 보증금은 {value['jeonse_price']}입니다."),
    ], ["현재 매물장과 매수문의 상담 유형이 일치하지 않음"]


OTHER_BLUEPRINTS = (
    "{complex} 주변 시세가 어떻게 형성되는지 일반적인 설명만 부탁드립니다.",
    "오늘은 장부 등록 없이 {region}의 생활 환경만 안내받고 싶습니다.",
    "공동중개 가능 여부를 확인하려고 연락했지만 의뢰 권한은 아직 확인되지 않았습니다.",
    "부동산 계약 때 준비할 서류가 무엇인지 일반적인 절차를 문의합니다.",
    "{complex} 광고를 보았는데 실제 의뢰가 아니라 공개 정보만 확인하려고 합니다.",
    "매도와 매수 중 어느 쪽으로 진행할지 정하지 못해 우선 상담만 요청합니다.",
    "가격을 {sale_price} 또는 {jeonse_price}로 들었지만 어떤 거래인지 확인되지 않았습니다.",
    "다른 중개업소와 조건을 대조하는 중이며 신규 장부 등록은 원하지 않습니다.",
    "{building} {unit} 이야기가 나왔지만 실제 의뢰 대상인지는 확인되지 않았습니다.",
    "상담 내용을 설명만 듣고 결정은 다음에 하겠습니다. 오늘은 로그만 남겨 주세요.",
)


def build_core_fragments(
    cell: CellSpec, blueprint: int, index: int
) -> tuple[list[Fragment], list[str]]:
    """blueprint가 만드는 장부가 셀 목표와 어긋나지 않는지 확인하며 핵심 문장을 만든다."""

    if cell.label == "매도의뢰":
        ledger_type, fragments, uncertainties = property_fragments(blueprint, index)
    elif cell.label == "매수문의":
        ledger_type, fragments, uncertainties = buyer_fragments(blueprint, index)
    else:
        value = values(index + LABEL_IDENTITY_OFFSET["기타상담"])
        ledger_type = cell.ledger_type
        fragments = [
            fragment(OTHER_BLUEPRINTS[blueprint].format(**value)),
            fragment("필드 제안 없이 상담 로그만 작성해 주세요."),
        ]
        uncertainties = []
    if ledger_type != cell.ledger_type:
        raise ValueError(
            f"{cell.slug}: blueprint {blueprint}의 장부 {ledger_type}가 "
            f"셀 목표 {cell.ledger_type}와 다릅니다"
        )
    return fragments, uncertainties


def identity_fragment(label: str, customer_name: str) -> Fragment:
    """모든 사례에 합성 고객의 본인 이름 발화를 남긴다."""

    if label == "매도의뢰":
        return fragment(
            f"제 이름은 {customer_name}이고 이 매물의 임대인입니다.", 임대인=customer_name
        )
    if label == "매수문의":
        return fragment(
            f"제 이름은 {customer_name}이고 제가 직접 구입할 집을 찾고 있습니다.",
            **{"구입자 이름": customer_name},
        )
    return fragment(f"제 이름은 {customer_name}이고 오늘은 일반 문의로 연락드렸습니다.")


def group_id_of(cell: CellSpec, blueprint: int, shape: int) -> str:
    return f"f2-full-v05-{cell.slug}-bp{blueprint:02d}-s{shape:02d}"


def cell_targets() -> dict[str, int]:
    """셀별 목표 건수. 여섯 조합은 서로 겹치지 않는다."""

    return {
        f"{cell.ledger_type}+{cell.label}": (
            len(cell.blueprints) * SHAPES_PER_BLUEPRINT * cell.rows_per_group
        )
        for cell in CELLS
    }


def group_targets() -> dict[str, int]:
    return {
        group_id_of(cell, blueprint, shape): cell.rows_per_group
        for cell in CELLS
        for blueprint in cell.blueprints
        for shape in range(SHAPES_PER_BLUEPRINT)
    }


def compact_target_counts() -> tuple[int, int]:
    """압축형 전체 건수와 그중 필드 정답이 있는 건수를 반환한다."""

    compact_rows = sum(
        len(cell.blueprints) * len(COMPACT_SHAPES) * cell.rows_per_group for cell in CELLS
    )
    compact_rows_with_fields = sum(
        len(cell.blueprints) * len(COMPACT_SHAPES) * cell.rows_per_group
        for cell in CELLS
        if cell.label != "기타상담" and not is_ledger_mismatch(cell.ledger_type, cell.label)
    )
    return compact_rows, compact_rows_with_fields


def make_records() -> list[dict[str, Any]]:
    """셀 목표표를 따라 (blueprint, 대화 형태) 그룹마다 정해진 수만큼 사례를 만든다."""

    rows: list[dict[str, Any]] = []
    for cell in CELLS:
        ordinal = 0
        for blueprint in cell.blueprints:
            for shape in range(SHAPES_PER_BLUEPRINT):
                for _ in range(cell.rows_per_group):
                    ordinal += 1
                    index = cell.index_base + ordinal
                    core, uncertainties = build_core_fragments(cell, blueprint, index)
                    customer_name = values(index + LABEL_IDENTITY_OFFSET[cell.label])["name"]
                    fragments = [*core, identity_fragment(cell.label, customer_name)]
                    if shape not in COMPACT_SHAPES:
                        fragments.append(
                            fragment(
                                f"연락 가능 시간은 {9 + ordinal % 10}시 "
                                f"{(ordinal // 10) % 6 * 10:02d}분 이후입니다."
                            )
                        )
                    fragments, difficulty_tags = expand_dialogue(
                        label=cell.label,
                        blueprint=blueprint,
                        shape=shape,
                        fragments=fragments,
                    )
                    transcript, expected = build_expected(
                        label=cell.label,
                        ledger_type=cell.ledger_type,
                        fragments=fragments,
                        uncertainties=uncertainties,
                    )
                    if expected["ledger_mismatch"]:
                        difficulty_tags.append("ledger_mismatch")
                        difficulty_tags.append("suppressed_field_values")
                    if expected["uncertainties"]:
                        difficulty_tags.append("uncertain_or_conflicting_values")
                    if len(expected["fields"]) >= 5:
                        difficulty_tags.append("many_fields")
                    difficulty_tags.append("spoken_self_identification")
                    rows.append(
                        {
                            "sample_id": f"f2-full-v05-{cell.slug}-{ordinal:04d}",
                            "dataset_version": DATASET_VERSION,
                            "label": cell.label,
                            "transcript": transcript,
                            "ledger_type": cell.ledger_type,
                            "expected": expected,
                            "source_type": SOURCE_TYPE,
                            "source_group_id": group_id_of(cell, blueprint, shape),
                            "split": "unassigned",
                            "contains_real_personal_data": False,
                            "review_status": REVIEW_STATUS,
                            "difficulty_tags": difficulty_tags,
                        }
                    )
    return rows


def validate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_keys = {
        "sample_id",
        "dataset_version",
        "label",
        "transcript",
        "ledger_type",
        "expected",
        "source_type",
        "source_group_id",
        "split",
        "contains_real_personal_data",
        "review_status",
        "difficulty_tags",
    }
    targets = cell_targets()
    if len(rows) != sum(targets.values()):
        raise ValueError(f"expected {sum(targets.values())} rows, got {len(rows)}")
    if any(set(row) != expected_keys for row in rows):
        raise ValueError("full-output schema mismatch")
    ids = [row["sample_id"] for row in rows]
    transcripts = [row["transcript"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate sample_id")
    if len(set(transcripts)) != len(transcripts):
        raise ValueError("duplicate transcript")

    label_counts = Counter(row["label"] for row in rows)
    cell_counts = Counter(f"{row['ledger_type']}+{row['label']}" for row in rows)
    if cell_counts != Counter(targets):
        raise ValueError(f"unexpected cell distribution: {dict(cell_counts)}")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    field_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()
    mismatch_count = 0
    forbidden_patterns = (
        re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    )
    phone_pattern = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
    speaker_prefix_pattern = re.compile(r"(?:^|\s)(?:중개사|고객)\s*:")
    for row in rows:
        if row["contains_real_personal_data"] is not False:
            raise ValueError(f"privacy flag must be false: {row['sample_id']}")
        if row["review_status"] != REVIEW_STATUS:
            raise ValueError(f"review status mismatch: {row['sample_id']}")
        if any(pattern.search(row["transcript"]) for pattern in forbidden_patterns):
            raise ValueError(f"possible personal data: {row['sample_id']}")
        for match in phone_pattern.finditer(row["transcript"]):
            if match.group(0) != PLACEHOLDER_PHONE:
                raise ValueError(f"unexpected phone-like value: {row['sample_id']}")
        if speaker_prefix_pattern.search(row["transcript"]):
            raise ValueError(f"speaker prefix found in STT transcript: {row['sample_id']}")
        if "제 이름은 " not in row["transcript"]:
            raise ValueError(f"spoken customer name missing: {row['sample_id']}")
        if not isinstance(row["difficulty_tags"], list) or not row["difficulty_tags"]:
            raise ValueError(f"missing difficulty tags: {row['sample_id']}")
        difficulty_counts.update(row["difficulty_tags"])
        groups[row["source_group_id"]].append(row)
        expected = row["expected"]
        if expected["consultation_type"] != row["label"]:
            raise ValueError(f"label mismatch: {row['sample_id']}")
        fields = expected["fields"]
        evidence = expected["evidence"]
        if set(fields) != set(evidence):
            raise ValueError(f"field/evidence keys mismatch: {row['sample_id']}")
        if not set(fields) <= ALLOWED_FIELDS[row["ledger_type"]]:
            raise ValueError(f"field is not allowed for ledger: {row['sample_id']}")
        if "개인정보 동의 여부" in fields:
            raise ValueError(f"privacy consent must not be inferred: {row['sample_id']}")
        for field_name, cited in evidence.items():
            if not isinstance(cited, str) or cited not in row["transcript"]:
                raise ValueError(f"evidence is not grounded: {row['sample_id']}:{field_name}")
        if expected["ledger_mismatch"] != is_ledger_mismatch(row["ledger_type"], row["label"]):
            raise ValueError(f"ledger mismatch rule violated: {row['sample_id']}")
        if expected["ledger_mismatch"]:
            mismatch_count += 1
        if (expected["ledger_mismatch"] or row["label"] == "기타상담") and fields:
            raise ValueError(f"forbidden field proposal: {row['sample_id']}")
        if not expected["ledger_mismatch"] and row["label"] == "매도의뢰" and "임대인" not in fields:
            raise ValueError(f"spoken landlord name not extracted: {row['sample_id']}")
        if not expected["ledger_mismatch"] and row["label"] == "매수문의" and "구입자 이름" not in fields:
            raise ValueError(f"spoken buyer name not extracted: {row['sample_id']}")
        field_counts.update(fields.keys())

    expected_group_sizes = group_targets()
    if set(groups) != set(expected_group_sizes):
        raise ValueError("source_group_id set does not match the cell plan")
    for group_id, group_rows in groups.items():
        if len(group_rows) != expected_group_sizes[group_id]:
            raise ValueError(
                f"{group_id}: expected {expected_group_sizes[group_id]} rows, "
                f"got {len(group_rows)}"
            )
        # 그룹은 분할 단위다. 한 그룹이 두 조합에 걸치면 그룹째 빠질 때 조합이 통째로 사라진다.
        if len({(row["label"], row["ledger_type"]) for row in group_rows}) != 1:
            raise ValueError(f"{group_id}: multiple label/ledger combinations")
    compact_rows = [row for row in rows if "compact_dialogue" in row["difficulty_tags"]]
    compact_rows_with_fields = [row for row in compact_rows if row["expected"]["fields"]]
    expected_compact_rows, expected_compact_rows_with_fields = compact_target_counts()
    if len(compact_rows) != expected_compact_rows:
        raise ValueError(
            f"expected {expected_compact_rows} compact rows, got {len(compact_rows)}"
        )
    if len(compact_rows_with_fields) != expected_compact_rows_with_fields:
        raise ValueError(
            "unexpected compact rows with fields: "
            f"expected {expected_compact_rows_with_fields}, got {len(compact_rows_with_fields)}"
        )

    transcript_lengths = [len(row["transcript"]) for row in rows]
    if min(transcript_lengths) < 80 or max(transcript_lengths) > 1200:
        raise ValueError(
            f"transcript length outside 80..1200: {min(transcript_lengths)}..{max(transcript_lengths)}"
        )
    ordered_lengths = sorted(transcript_lengths)
    p95_index = max(0, math.ceil(len(ordered_lengths) * 0.95) - 1)

    def length_summary(selected: list[dict[str, Any]]) -> dict[str, float | int]:
        lengths = sorted(len(row["transcript"]) for row in selected)
        return {
            "minimum": lengths[0],
            "median": statistics.median(lengths),
            "maximum": lengths[-1],
        }

    return {
        "rows": len(rows),
        "labels": dict(sorted(label_counts.items())),
        "cells": dict(sorted(cell_counts.items())),
        "source_groups": len(groups),
        "shapes_per_blueprint": SHAPES_PER_BLUEPRINT,
        "rows_per_group": dict(
            sorted({cell.slug: cell.rows_per_group for cell in CELLS}.items())
        ),
        "ledger_mismatch_rows": mismatch_count,
        "rows_with_fields": sum(bool(row["expected"]["fields"]) for row in rows),
        "compact_rows": len(compact_rows),
        "compact_rows_with_fields": len(compact_rows_with_fields),
        "field_annotation_counts": dict(sorted(field_counts.items())),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "transcript_character_length": {
            "minimum": min(transcript_lengths),
            "median": statistics.median(transcript_lengths),
            "p95": ordered_lengths[p95_index],
            "maximum": max(transcript_lengths),
        },
        "transcript_character_length_by_field_presence": {
            "with_fields": length_summary(
                [row for row in rows if row["expected"]["fields"]]
            ),
            "without_fields": length_summary(
                [row for row in rows if not row["expected"]["fields"]]
            ),
        },
        "compact_transcript_character_length": length_summary(compact_rows),
        "compact_with_fields_character_length": length_summary(compact_rows_with_fields),
    }


def main() -> None:
    rows = make_records()
    report = validate(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"output": str(OUTPUT_PATH), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
