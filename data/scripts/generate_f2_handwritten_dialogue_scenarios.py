"""사람이 쓴 상담 통화를 사실 단위(beat)로 분해해 F2 full-output 학습 후보를 만든다.

이전 판은 대화 뼈대를 고정하고 표현만 바꿔서 900건이 모두 비슷한 통화처럼 읽혔다.
이 도구는 상황과 화자를 blueprint로 두고, 같은 사실을 전달하는 방식(전달 형태),
거래 의지 온도, 표현 변형, 합성 슬롯 값의 네 축으로 확장한다. 고객이 한 턴에 여러
사실을 몰아 말하는 통화, 중개사가 질문을 주도하는 통화, 중간에 서류를 확인하며
끊기는 통화, 상대가 다른 중개사인 공동중개 통화가 모두 나온다.

화자 표기는 남기지 않고 발화를 순서대로 이어 붙여, 장부 종류와 STT 평문을 입력으로
받는 full-output 계약을 그대로 따른다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "f2_llm" / "working"
STEM = "f2_handwritten_dialogue_scenarios.privacy_safe.v0.5"

DATASET_VERSION = "0.5.0"
DATASET_ID = "f2-handwritten-dialogue"
REVIEW_STATUS = "generated_unreviewed"
SOURCE_TYPE = "handwritten_dialogue_blueprint"
GENERATED_AT = "2026-09-02"

MERGED_KEY_ORDER = (
    "sample_id", "dataset_version", "label", "transcript", "ledger_type", "expected",
    "source_type", "source_group_id", "split", "contains_real_personal_data",
    "review_status", "difficulty_tags", "source_scenario_id",
)

PROPERTY_FIELDS = frozenset(
    {
        "단지", "평형", "동", "호", "타입", "방향", "현상태", "현재 보증금", "현재 차임",
        "융자", "만기일", "접수일", "현매물", "진행상태", "명도 조건", "매매가", "전세보증금",
        "월세 보증금", "월세 차임", "확장 여부", "붙박이", "시설 상태", "임대인", "임대인 전화",
        "임차인", "임차인 전화", "관련 중개업소", "담당자", "비고",
    }
)
BUYER_FIELDS = frozenset(
    {
        "접수일", "최종접촉일", "거래 구분", "희망 단지", "희망 지역", "희망 평형", "금액 원문",
        "이사일 원문", "구입자 이름", "구입자 별칭", "전화번호", "관련 중개업소", "진행단계",
        "완료 여부", "담당자", "분류", "비고",
    }
)
ALLOWED_FIELDS = {"매물장": PROPERTY_FIELDS, "구입장": BUYER_FIELDS}

COMPLEXES = (
    "이든여울빛마을", "라온누리파크", "한빛마루타운", "다솜언덕마을", "새봄으뜸단지",
    "푸른들채", "온새미로타운", "별헤는마을", "고운뜨락", "향긋한숲마을",
    "해솔빛마을", "너울해오름", "도담뜰마을", "미르숲마을", "윤슬마루",
    "가온빛파크", "예솔한들마을", "노을담은뜰",
)
CITIES = ("나린온시", "소보람시", "별밭시", "온새미시", "하늬바람시", "너울시", "미르시")
GUS = ("바오름구", "여울구", "다솜구", "새록구", "물빛구", "가람구")
DONGS = ("수풀동", "별빛동", "고운동", "늘봄동", "솔바람동", "아람동", "예솔동")
NAMES = (
    "가온고객", "나래고객", "다온고객", "라온고객", "마루고객", "바다고객",
    "새롬고객", "아람고객", "예솔고객", "하람고객", "윤슬고객", "미르고객",
    "슬기고객", "온새미고객", "너울고객",
)
KIN_NAMES = ("합성가족0", "합성가족1", "합성가족2", "합성가족3", "합성가족4")
TENANT_NAMES = ("합성임차인0", "합성임차인1", "합성임차인2", "합성임차인3", "합성임차인4")
BROKERAGES = (
    "가상한빛공인중개사", "가상라온공인중개사", "가상다온공인중개사",
    "가상새록공인중개사", "가상물빛공인중개사", "가상여울공인중개사",
    "가상해솔공인중개사", "가상너울공인중개사",
)
MANAGERS = ("합성담당자0", "합성담당자1", "합성담당자2", "합성담당자3", "합성담당자4")
DIRECTIONS = ("남향", "남동향", "동향", "서향", "남서향")


def phone_of(index: int) -> str:
    """합성 연락처를 만든다. 무작위 조합이라 실제 번호와 우연히 겹칠 수 있다."""

    return f"010-{1000 + (index * 613) % 9000:04d}-{(index * 3187 + 41) % 10000:04d}"


DIGIT_HAS_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False,
                   "5": False, "6": True, "7": True, "8": True, "9": False}


def has_final(word: str) -> bool:
    """받침 유무를 본다. 숫자는 읽는 소리(영·일·이…)를 기준으로 판단한다."""

    ch = word[-1]
    if ch.isdigit():
        return DIGIT_HAS_FINAL[ch]
    if not ("가" <= ch <= "힣"):
        return True
    return (ord(ch) - 0xAC00) % 28 != 0


def j(word: str, with_final: str, without_final: str) -> str:
    """받침 유무에 따라 조사를 고른다."""

    return word + (with_final if has_final(word) else without_final)


DIGIT_TAKES_EURO = {"0": True, "1": False, "2": False, "3": True, "4": False,
                    "5": False, "6": True, "7": False, "8": False, "9": False}


def ro(word: str) -> str:
    """'으로'와 '로'를 고른다. 받침이 없거나 ㄹ 받침이면 '로'다."""

    ch = word[-1]
    if ch.isdigit():
        return word + ("으로" if DIGIT_TAKES_EURO[ch] else "로")
    if not ("가" <= ch <= "힣"):
        return word + "로"
    return word + ("로" if (ord(ch) - 0xAC00) % 28 in (0, 8) else "으로")


def pick(index: int, *options: str) -> str:
    return options[index % len(options)]


AREA_TABLE = (
    ("20평", "49제곱미터"), ("24평", "59제곱미터"), ("27평", "66제곱미터"),
    ("30평", "74제곱미터"), ("32평", "79제곱미터"), ("34평", "84제곱미터"),
    ("38평", "99제곱미터"), ("45평", "114제곱미터"),
)


def slots(index: int) -> dict[str, str]:
    """실제 사람·주소와 연결되지 않는 반복 가능한 합성 슬롯 값을 만든다."""

    area, exclusive = AREA_TABLE[index % len(AREA_TABLE)]
    area2, exclusive2 = AREA_TABLE[(index + 1) % len(AREA_TABLE)]
    area_small, exclusive_small = AREA_TABLE[index % 3]
    area_large, exclusive_large = AREA_TABLE[6 + index % 2]
    return {
        "complex": COMPLEXES[index % len(COMPLEXES)],
        "complex2": COMPLEXES[(index * 7 + 3) % len(COMPLEXES)],
        "complex3": COMPLEXES[(index * 5 + 11) % len(COMPLEXES)],
        "region": f"{CITIES[index % len(CITIES)]} {GUS[(index * 3) % len(GUS)]} {DONGS[(index * 2) % len(DONGS)]}",
        "building": f"{101 + index % 24}동",
        "unit": f"{201 + (index * 37) % 1700}호",
        "area": area,
        "exclusive": exclusive,
        "area2": area2,
        "exclusive2": exclusive2,
        "area_small": area_small,
        "exclusive_small": exclusive_small,
        "area_large": area_large,
        "exclusive_large": exclusive_large,
        "type": f"{exclusive[:-4]}{'ABC'[index % 3]}",
        "direction": DIRECTIONS[index % len(DIRECTIONS)],
        "floor": f"{4 + index % 18}층",
        "floor_min": f"{5 + index % 8}층",
        "price": f"{5 + index % 11}억 {1 + index % 8}천만 원",
        "price_slip": f"{5 + index % 11}억 {2 + index % 8}천만 원",
        "price_floor": f"{5 + index % 11}억",
        "budget": f"{6 + index % 9}억 {1 + index % 8}천만 원",
        "budget_slip": f"{6 + index % 9}억 {2 + index % 8}천만 원",
        "cash": f"{2 + index % 4}억 {1 + index % 8}천만 원",
        "loan": f"{1 + index % 4}억 {1 + index % 8}천만 원",
        "loan_left": f"{1 + index % 3}억 {1 + index % 8}천만 원",
        "jeonse": f"{2 + index % 6}억 {1 + index % 8}천만 원",
        "jeonse_slip": f"{2 + index % 6}억 {2 + index % 8}천만 원",
        "sale_deposit": f"{1 + index % 4}억 {1 + index % 8}천만 원",
        "wolse_deposit": f"{2 + index % 8}000만 원",
        "wolse_rent": f"{40 + (index % 6) * 10}만 원",
        "wolse_deposit_spoken": ("이천", "삼천", "사천", "오천", "육천", "칠천", "팔천", "구천")[index % 8],
        "wolse_deposit_spoken_slip": ("삼천", "사천", "오천", "육천", "칠천", "팔천", "구천", "이천")[index % 8],
        "wolse_rent_spoken": ("사십", "오십", "육십", "칠십", "팔십", "구십")[index % 6],
        "fee": f"{12 + index % 9}만 원",
        "due": f"{9 + index % 4}월 {1 + index % 27}일",
        "due_next": f"내년 {1 + index % 6}월",
        "move": f"{9 + index % 4}월 {10 + index % 18}일",
        "move_next": f"내년 {1 + index % 3}월",
        "move_from": f"{9 + index % 3}월 중순",
        "move_to": f"{10 + index % 3}월 초",
        "expire": f"{8 + index % 3}월 말",
        "expire_late": f"{11 + index % 2}월 말",
        "depart": f"다음 달 {10 + index % 18}일",
        "hold_years": ("1년 반", "2년", "3년", "4년", "5년")[index % 5],
        "repair_years": ("2년", "3년", "4년", "5년", "6년")[index % 5],
        "aircon": f"{2 + index % 4}대",
        "kids": ("자녀 두 명", "자녀 세 명", "자녀 한 명")[index % 3],
        "name": NAMES[index % len(NAMES)],
        "kin": KIN_NAMES[index % len(KIN_NAMES)],
        "kin2": KIN_NAMES[(index * 3 + 1) % len(KIN_NAMES)],
        "tenant": TENANT_NAMES[index % len(TENANT_NAMES)],
        "alias": f"합성고객{index % 20}",
        "brokerage": BROKERAGES[index % len(BROKERAGES)],
        "brokerage2": BROKERAGES[(index * 5 + 2) % len(BROKERAGES)],
        "manager": MANAGERS[index % len(MANAGERS)],
        "phone": phone_of(index),
        "phone_tail": phone_of(index)[-4:],
    }


@dataclass
class Beat:
    """상담에서 확인되는 사실 하나와 그것을 말하는 방식들."""

    tell: tuple[str, ...]
    ask: tuple[str, ...] = ()
    ack: tuple[str, ...] = ()
    fields: dict[str, str] = field(default_factory=dict)
    ack_fields: dict[str, str] = field(default_factory=dict)
    note: str | None = None
    optional: bool = False
    tags: tuple[str, ...] = ()
    # 0~1은 본론, 2는 곁가지 화제, 3은 통화 마무리 쪽에 오는 내용이다.
    stage: int = 1


@dataclass
class Blueprint:
    """한 통화의 상황, 화자, 사실 구성."""

    key: str
    label: str
    persona: str
    openings: tuple[str, ...]
    identity: tuple[str, ...]
    identity_fields: dict[str, str]
    beats: list[Beat]
    closings: dict[str, tuple[str, ...]]
    tags: tuple[str, ...] = ()


@dataclass
class Script:
    """대화 turn과 정답 후보를 함께 모은다."""

    turns: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    uncertainties: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    identity: str = ""

    def say(self, text: str, **found: str) -> None:
        self.turns.append(text)
        for key, value in found.items():
            self.fields[key] = value
            self.evidence[key] = text

    def note(self, text: str) -> None:
        if text not in self.uncertainties:
            self.uncertainties.append(text)

    def tag(self, *names: str) -> None:
        for name in names:
            if name not in self.tags:
                self.tags.append(name)

    @property
    def transcript(self) -> str:
        return " ".join(self.turns)


TURN_SHAPES = ("pingpong", "front_dump", "agent_led", "interrupted", "terse")
TEMPERATURES = ("high", "mid", "low")


class Rng:
    """행마다 다른 선택을 하게 만드는 결정적 난수기.

    표현 선택을 한 값으로 고정하면 같은 shape의 행들이 문장까지 똑같아진다. 선택 지점마다
    난수를 뽑아 통화 하나하나가 다른 조합을 갖게 한다. 씨앗은 행 인덱스에서 나오므로
    같은 명령을 다시 실행해도 결과는 같다.
    """

    def __init__(self, seed: int) -> None:
        self.state = (seed * 2654435761 + 0x9E3779B9) & 0xFFFFFFFF or 0x9E3779B9

    def _next(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF or 0x9E3779B9
        return self.state

    def below(self, bound: int) -> int:
        return self._next() % max(1, bound)

    def pick(self, options: tuple[str, ...] | list[str]) -> str:
        return options[self.below(len(options))]

    def chance(self, numerator: int, denominator: int) -> bool:
        return self.below(denominator) < numerator


CUSTOMER_FILLERS = ("어… ", "그… ", "아 네, ", "음… ", "저기, ", "아, ")
BACKCHANNELS = ("네.", "아 네네.", "예.", "네 알겠습니다.", "그렇군요.")
INTERRUPTIONS = (
    "아 잠시만요. 서류 좀 보고 말씀드릴게요.",
    "죄송해요, 잠깐만요. 다른 전화가 와서요.",
    "어… 잠깐만요. 제가 지금 밖이라 메모를 못 해서요.",
    "잠시만요. 옆에서 뭐라고 하셔서 잠깐 놓쳤어요.",
    "아 죄송합니다. 애가 불러서 잠깐만요.",
)
REASKS = (
    "네? 죄송한데 다시 한 번 말씀해 주시겠어요?",
    "아 잘 안 들렸어요. 한 번만 더 말씀해 주세요.",
    "죄송합니다, 중간에 끊겨서요. 다시 말씀해 주시겠어요?",
    "네, 마지막 부분만 다시 확인할게요.",
)
MID_SUMMARIES = (
    "여기까지 확인된 것만 먼저 정리하겠습니다.",
    "제가 들은 내용부터 한 번 정리해 볼게요.",
    "지금까지 나온 조건을 정리하면서 가겠습니다.",
    "중간에 한 번 확인하고 넘어가겠습니다.",
)
NEUTRAL_CLOSINGS = (
    "네, 확인해서 다시 연락드리겠습니다.",
    "네, 내용 정리해서 안내드리겠습니다.",
    "알겠습니다. 확인하는 대로 연락드릴게요.",
    "네, 상담 내용 정리해 두겠습니다.",
)
LOW_TEMP_NOTES = {
    "매도의뢰": "고객이 아직 공개 등록을 원하지 않아 접수 여부가 확정되지 않음",
    "매수문의": "고객이 방문·계약 의사를 확정하지 않아 진행 시점이 미정",
    "기타상담": "고객이 계약 의사가 없다고 밝혀 장부 등록 대상이 아님",
}


def usable_beats(beats: list[Beat], turn_shape: str, temp: str, rng: Rng) -> list[Beat]:
    """전달 형태와 온도에 따라 선택 beat를 덜어낸다."""

    result: list[Beat] = []
    for beat in beats:
        if not beat.optional:
            result.append(beat)
            continue
        if turn_shape == "terse":
            continue
        keep = 1 if temp == "low" else 2
        if rng.chance(keep, 3):
            result.append(beat)
    return result


CONTACT_FIELDS = ("임대인 전화", "전화번호")


def compose_beats(bp: Blueprint, v: dict[str, str], turn_shape: str, temp: str, rng: Rng) -> list[Beat]:
    """통화마다 다루는 내용과 순서를 바꾼다.

    blueprint의 핵심 사실만 정해진 순서로 내면 같은 상담이 늘 같은 대본이 된다. 여기서는
    선택 사실을 덜어내고, 곁가지 화제를 통화마다 다른 자리에 끼우고, 연락처처럼 뒤에 오는
    내용을 마지막으로 보낸다. 앞쪽 두 beat는 무슨 상담인지 정하는 부분이라 건드리지 않는다.
    """

    beats = usable_beats(bp.beats, turn_shape, temp, rng)
    if not beats:
        beats = [beat for beat in bp.beats if not beat.optional]

    # 통화마다 다루는 범위가 달라지도록 본론 하나를 통째로 빼기도 한다.
    if len(beats) > 4 and rng.chance(1, 3):
        index = 2 + rng.below(len(beats) - 3)
        beats = beats[:index] + beats[index + 1 :]

    contact = [b for b in beats if set(b.fields) & set(CONTACT_FIELDS)]
    body = [b for b in beats if b not in contact]

    if turn_shape != "terse":
        pool = EXTRA_POOLS[bp.label](v)
        wanted = rng.below(4 if temp != "low" else 3)
        chosen: list[Beat] = []
        for beat in pool:
            if len(chosen) >= wanted:
                break
            if rng.chance(1, 2):
                chosen.append(beat)
        for beat in chosen:
            if beat.stage >= 3:
                body.append(beat)
            else:
                position = min(len(body), 1 + rng.below(max(1, len(body))))
                body.insert(position, beat)

    return body + contact


def flavor(text: str, rng: Rng, script: Script | None = None) -> str:
    """고객 발화 앞에 가끔 머뭇거림을 붙인다. 같은 표현이 연달아 나오지 않게 한다."""

    if not rng.chance(1, 5):
        return text
    filler = rng.pick(CUSTOMER_FILLERS)
    if script is not None and script.turns and script.turns[-1].startswith(filler):
        return text
    return filler + text


def emit_beat(script: Script, beat: Beat, rng: Rng, *, with_ask: bool, with_ack: bool) -> str:
    """beat 하나를 질문·답변·복창 순서로 낸다. 답변 문장을 돌려준다."""

    # 곁가지 화제는 질문 없이 답만 나오면 앞뒤가 붕 뜬다.
    if beat.ask and (with_ask or beat.stage >= 2):
        script.say(rng.pick(beat.ask))
    tell = flavor(rng.pick(beat.tell), rng, script)
    script.say(tell, **beat.fields)
    # 발화가 질문이면 답을 반드시 붙인다. 근거가 복창 문장에 있는 경우도 마찬가지다.
    must_ack = bool(beat.ack_fields) or tell.rstrip().endswith("?")
    if beat.ack and (with_ack or must_ack):
        script.say(rng.pick(beat.ack), **beat.ack_fields)
    elif not beat.ack and with_ack and rng.chance(1, 3):
        script.say(rng.pick(BACKCHANNELS))
    if beat.note:
        script.note(beat.note)
    script.tag(*beat.tags)
    return tell


def render(
    bp: Blueprint, v: dict[str, str], turn_shape: str, temp: str, rng: Rng, *,
    ledger_words_ok: bool = True,
) -> Script:
    """같은 사실 구성을 전달 형태에 따라 다른 통화로 만든다."""

    script = Script()
    script.tag("unlabeled_multi_speaker_stt", *bp.tags, f"turn_shape_{turn_shape}", f"intent_{temp}")
    greeted = rng.chance(6, 7)
    if greeted:
        script.say(rng.pick(bp.openings))
    else:
        # 인사 없이 시작하면 발신자가 먼저 용건을 말한다.
        script.tag("no_greeting")

    beats = compose_beats(bp, v, turn_shape, temp, rng)
    identity_text = flavor(rng.pick(bp.identity), rng, script)

    def place_identity(script: Script) -> None:
        script.say(identity_text, **bp.identity_fields)
        script.identity = identity_text

    if turn_shape == "front_dump":
        # 중개사의 응답이 되묻는 질문이면 몰아 말하기를 그 앞에서 끊는다.
        limit = 2 + rng.below(3)
        chosen: list[tuple[Beat, str]] = []
        for beat in beats[:limit]:
            ack_first = beat.ack[0] if beat.ack else ""
            if ack_first and ack_first.rstrip().endswith("?"):
                break
            chosen.append((beat, rng.pick(beat.tell)))
        head_len = len(chosen)
        rest = beats[head_len:]
        if chosen:
            script.tag("front_loaded_disclosure")
        merged = " ".join([identity_text] + [tell for _, tell in chosen])
        script.turns.append(merged)
        script.identity = identity_text
        for key, value in bp.identity_fields.items():
            script.fields[key] = value
            script.evidence[key] = identity_text
        for beat, tell in chosen:
            for key, value in beat.fields.items():
                script.fields[key] = value
                script.evidence[key] = tell
            if beat.note:
                script.note(beat.note)
            script.tag(*beat.tags)
        for beat, _ in chosen:
            if beat.ack:
                script.say(rng.pick(beat.ack), **beat.ack_fields)
        if rng.chance(2, 3):
            script.say(rng.pick(MID_SUMMARIES))
        for beat in rest:
            emit_beat(script, beat, rng, with_ask=rng.chance(3, 4), with_ack=rng.chance(1, 2))
    elif turn_shape == "agent_led":
        script.tag("agent_led_questioning")
        summary_at = 1 + rng.below(max(1, len(beats) - 1))
        for position, beat in enumerate(beats):
            if position == 0:
                place_identity(script)
            emit_beat(script, beat, rng, with_ask=True, with_ack=rng.chance(3, 4))
            if position == summary_at and rng.chance(2, 3):
                script.say(rng.pick(MID_SUMMARIES))
    elif turn_shape == "interrupted":
        script.tag("interrupted_call", "disfluency")
        break_at = 1 + rng.below(max(1, len(beats) - 1))
        reask_at = min(len(beats) - 1, break_at + 1 + rng.below(2))
        identity_at = rng.below(2) if greeted else 0
        for position, beat in enumerate(beats):
            if position == identity_at:
                place_identity(script)
            if position == break_at:
                script.say(rng.pick(INTERRUPTIONS))
            tell = emit_beat(script, beat, rng, with_ask=rng.chance(4, 5), with_ack=rng.chance(1, 3))
            if position == reask_at:
                script.say(rng.pick(REASKS))
                script.say(tell)
                script.tag("repeated_statement")
    elif turn_shape == "terse":
        script.tag("short_dialogue", "compact_dialogue")
        for position, beat in enumerate(beats):
            if position == 0:
                place_identity(script)
            emit_beat(script, beat, rng, with_ask=rng.chance(1, 2), with_ack=False)
    else:
        script.tag("long_dialogue")
        identity_at = rng.below(2) if greeted else 0
        for position, beat in enumerate(beats):
            if position == identity_at:
                place_identity(script)
            emit_beat(script, beat, rng, with_ask=rng.chance(5, 6), with_ack=rng.chance(1, 3))

    if not script.identity:
        place_identity(script)
    if temp == "low":
        script.note(LOW_TEMP_NOTES[bp.label])
    options = bp.closings[temp]
    if not ledger_words_ok:
        # 장부가 어긋난 통화에서 특정 장부 이름을 말하면 정답이 원문에 새어 나간다.
        filtered = tuple(o for o in options if "매물장" not in o and "구입장" not in o)
        options = filtered or NEUTRAL_CLOSINGS
    script.say(rng.pick(options))
    return script



GREET_STD = (
    "네, {b}입니다.",
    "{b}입니다. 무엇을 도와드릴까요?",
    "안녕하세요. {b}입니다.",
    "네 {b} 사무소입니다.",
    "여보세요, {b}입니다.",
    "{b}입니다. 말씀하세요.",
    "네 {b}입니다. 무엇을 도와드릴까요?",
    "감사합니다. {b}입니다.",
    "{b} 사무소입니다. 안녕하세요.",
    "네, 전화 주셔서 감사합니다. {b}입니다.",
    "{b}예요. 네 말씀하세요.",
    "안녕하세요, {b} 사무소예요.",
    "네 여보세요. {b}입니다.",
    "{b}입니다. 어떤 일로 전화 주셨어요?",
)
GREET_PLAIN = (
    "안녕하세요. 무엇을 도와드릴까요?",
    "네 말씀하세요.",
    "여보세요?",
    "네, 듣고 있습니다.",
    "네 안녕하세요. 어떤 일이세요?",
)


def greet(v: dict[str, str], *extra: str) -> tuple[str, ...]:
    return tuple(text.format(b=v["brokerage"]) for text in GREET_STD) + extra


def bp_sell_resident(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-resident",
        label="매도의뢰",
        persona="거주 중인 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} {v['complex']} {v['building']} {v['unit']}를 매도하려고 전화드렸습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 매도 건으로 연락드렸어요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, {v['complex']} {v['building']} {v['unit']} 집을 내놓으려고요.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                ask=("몇 평인가요?", "평형이 어떻게 되세요?", "평수와 타입 알려주시겠어요?"),
                tell=(
                    f"{v['area']}이고 전용면적은 {v['exclusive']}입니다. 타입은 {v['type']}이고 {v['direction']}이에요.",
                    f"{v['area']}입니다. 전용 {v['exclusive']}이고 {v['type']} 타입에 {v['direction']}이고요.",
                    f"{v['area']}, 전용 {j(v['exclusive'], '이에요', '예요')}. {v['type']} 타입이고 향은 {v['direction']}입니다.",
                ),
                fields={"평형": v["area"], "타입": v["type"], "방향": v["direction"]},
            ),
            Beat(
                ask=("희망하시는 매매가는 얼마인가요?", "가격은 얼마로 생각하고 계세요?", "희망가를 알려주시겠어요?"),
                tell=(
                    f"{v['price']}입니다.",
                    f"{v['price']} 정도 받고 싶어요.",
                    f"{v['price']}으로 생각하고 있습니다.",
                ),
                ack=(f"매매가 {v['price']}으로 확인하겠습니다.", f"네, {v['price']} 적어두겠습니다.",
                     f"{v['price']}이요. 확인했습니다."),
                fields={"매매가": v["price"]},
            ),
            Beat(
                tell=(
                    f"현재 저희 가족이 거주하고 있고 {v['move']} 이후에 이사할 수 있습니다.",
                    f"지금은 저희가 살고 있어요. {v['move']} 지나면 비워드릴 수 있습니다.",
                    f"저희가 실거주 중이고 {v['move']}부터는 명도가 가능합니다.",
                ),
                ask=("현재 누가 거주하고 계신가요?", "지금 실거주 중이신가요?", "거주 상태가 어떻게 되나요?"),
                fields={"현상태": "소유자 거주", "명도 조건": f"{v['move']} 이후 이사 가능"},
            ),
            Beat(
                ask=("대출은 얼마나 남아 있나요?", "융자 상황은 어떻게 되세요?", "근저당은 어느 정도인가요?"),
                tell=(
                    f"대출은 {v['loan_left']} 정도 남아 있습니다.",
                    f"융자는 {v['loan_left']} 남았어요.",
                    f"{v['loan_left']} 정도 대출이 있습니다.",
                ),
                fields={"융자": v["loan_left"]},
                optional=True,
            ),
            Beat(
                ask=("내부 상태는 어떤가요?", "확장이나 수리는 되어 있나요?", "내부 수리 이력이 있으신가요?"),
                tell=(
                    f"거실과 작은방이 확장되어 있고 {v['repair_years']} 전에 주방하고 욕실을 수리했습니다.",
                    f"확장형이고 {v['repair_years']} 전에 주방과 욕실을 새로 했어요.",
                    f"거실 확장했고 {v['repair_years']} 전 주방·욕실 수리했습니다.",
                ),
                fields={"확장 여부": "거실·작은방 확장", "시설 상태": f"{v['repair_years']} 전 주방·욕실 수리"},
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주시겠어요?", "연락 가능한 번호 알려주세요.", "번호는 어떻게 저장할까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 연락 주세요.", f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"임대인 전화": v["phone"]},
            ),
        ],
        closings={
            "high": (
                "올해 안에 팔고 싶어서 조건 맞는 분 있으면 바로 집 보여드릴 수 있습니다.",
                "빨리 진행하고 싶어요. 보러 오신다면 언제든 맞춰드리겠습니다.",
                "가능하면 이번 달 안에 계약까지 하고 싶습니다.",
            ),
            "mid": (
                "네, 소유권을 확인한 뒤 매물로 접수하겠습니다.",
                "등기 확인하고 매물장에 올려두겠습니다.",
                "네, 확인되는 대로 접수해 두겠습니다.",
            ),
            "low": (
                "우선 상담만 기록해 주시고 등록은 조금 더 생각해 보고 말씀드릴게요.",
                "아직 확정은 아니라서 등록은 보류해 주세요.",
                "일단 시세만 받아보고 다시 연락드리겠습니다.",
            ),
        },
        tags=("owner_occupied", "many_fields"),
    )


def bp_sell_jeonse_coowner(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-jeonse-coowner",
        label="매도의뢰",
        persona="전세 세입자가 있는 공동명의 소유자",
        openings=greet(v),
        identity=(
            f"내 이름은 {j(v['name'], '인데', 'ㄴ데')} {v['complex']} 하나 팔라 카는데예.",
            f"제 이름은 {j(v['name'], '입니더', '입니더')}. {v['complex']} 집을 하나 내놓을라 합니더.",
            f"내 이름 {j(v['name'], '이라예', '라예')}. {v['complex']} 매도 좀 물어볼라꼬예.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"]},
        beats=[
            Beat(
                ask=("몇 동 몇 호인가요?", "동호수 알려주시겠어요?", "동과 호수가 어떻게 되세요?"),
                tell=(
                    f"{v['building']} {v['unit']}입니더.",
                    f"{v['building']} {v['unit']}라예.",
                    f"어… {v['building']} {v['unit']}. 맞심더.",
                ),
                fields={"동": v["building"], "호": v["unit"]},
            ),
            Beat(
                ask=("평수는 어떻게 되세요?", "평형 알려주시겠어요?", "몇 평인가요?"),
                tell=(
                    f"평수는 {v['area']}이고 전용으로는 {v['exclusive']}라예.",
                    f"{v['area']}입니더. 전용 {j(v['exclusive'], '이고예', '고예')}.",
                    f"{v['area']}쯤 됩니더.",
                ),
                fields={"평형": v["area"]},
            ),
            Beat(
                ask=("생각하시는 매매가는 얼마인가요?", "희망가는 어느 정도십니까?", "가격은 얼마로 볼까요?"),
                tell=(
                    f"{v['price']} 정도는 받아야 안 되겠나 싶습니더.",
                    f"{v['price']}은 받고 싶심더.",
                    f"{v['price']} 생각하고 있는데예.",
                ),
                ack=(f"희망 매매가 {v['price']}으로 적겠습니다.", f"네, {v['price']} 확인했습니다.",
                     f"{v['price']}으로 기록하겠습니다."),
                fields={"매매가": v["price"]},
            ),
            Beat(
                ask=("현재 누가 살고 있나요?", "거주자가 있습니까?", "지금 세입자가 있으신가요?"),
                tell=(
                    f"전세 세입자가 살고 있어예. 보증금이 {v['sale_deposit']}이고 만기는 {v['due']}입니더.",
                    f"세입자 있심더. 전세 {v['sale_deposit']}에 만기가 {v['due']}라예.",
                    f"전세 놨심더. {v['sale_deposit']}이고 {v['due']}에 끝납니더.",
                ),
                fields={"현재 보증금": v["sale_deposit"], "만기일": v["due"], "현상태": "임차인 거주"},
            ),
            Beat(
                ask=("세입자는 만기 때 나간다고 하던가요?", "임차인 퇴거 계획은 확인하셨나요?",
                     "만기에 비워주시는 건가요?"),
                tell=(
                    "나간다는 말은 했는데 새집을 못 구하면 한두 달 더 살 수도 있다 카데예.",
                    "나간다 캤는데 확실하진 않심더.",
                    "그건 아직 확실치가 않아예.",
                ),
                note="임차인 퇴거 시점이 확정되지 않아 명도 조건을 정하지 못함",
                tags=("uncertain_handover",),
            ),
            Beat(
                ask=("대출은 없으신가요?", "융자는 어떻게 되나요?", "근저당 설정이 있습니까?"),
                tell=(
                    f"대출은 없는데 이 아파트가 나하고 {v['kin']} 공동명의라예. 매도는 하기로 했는데 "
                    "가격은 한 번 더 이야기해야 됩니더.",
                    f"융자는 없심더. 근데 {v['kin']}하고 공동명의라 가격은 상의해봐야 됩니더.",
                    f"대출은 없어예. 다만 {v['kin']}하고 같이 가진 집이라예.",
                ),
                fields={"융자": "없음"},
                note="공동명의자와 매매가를 다시 협의하기로 해 가격이 확정되지 않음",
                tags=("co_ownership",),
            ),
            Beat(
                ask=("연락처 하나 남겨주시겠어요?", "번호 좀 알려주세요.", "연락은 어디로 드리면 될까요?"),
                tell=(f"{v['phone']}입니더.", f"{v['phone']} 이거로 하이소.", f"번호는 {j(v['phone'], '이라예', '라예')}."),
                fields={"임대인 전화": v["phone"]},
                optional=True,
            ),
        ],
        closings={
            "high": (
                "예, 시세 보고 가격 괜찮으면 바로 내놓을랍니더.",
                "빨리 진행했으면 좋겠심더. 연락 주이소.",
                "예, 이번 달 안에 정리했으면 합니더.",
            ),
            "mid": (
                "그러면 상담 내용을 기록하고 최근 시세를 확인해드리겠습니다.",
                "네, 시세 확인해서 다시 연락드리겠습니다.",
                "우선 상담 기록만 남기고 시세를 뽑아보겠습니다.",
            ),
            "low": (
                "일단 물어만 본 거라예. 정하면 다시 전화하겠심더.",
                "아직 확실한 건 아이라예. 나중에 다시 연락드리께예.",
                "예, 급한 건 아니라서 천천히 보겠심더.",
            ),
        },
        tags=("dialect_gyeongsang", "tenant_in_place"),
    )


def bp_sell_cautious_private(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-cautious-private",
        label="매도의뢰",
        persona="비공개를 원하는 신중한 소유자",
        openings=greet(v),
        identity=(
            f"저는 {j(v['name'], '이라고', '라고')} 하는데 {v['complex']} {v['building']} {v['unit']} 매도 문제로 상담받고 싶어서요.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, {v['complex']} {v['building']} {v['unit']} 건으로 여쭤보려고요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 매도 상담을 받고 싶습니다.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                ask=("해당 아파트는 몇 평인가요?", "평형과 타입이 어떻게 되나요?", "평수 알려주시겠어요?"),
                tell=(
                    f"{v['area']}이고 전용면적은 {v['exclusive']}입니다. {v['type']} 타입이고 {v['direction']}이에요.",
                    f"{v['area']}입니다. {v['type']} 타입에 {v['direction']}이고요.",
                    f"{v['area']}, 전용 {v['exclusive']}입니다. {v['type']}이고 {v['direction']}이고요.",
                ),
                fields={"평형": v["area"], "타입": v["type"], "방향": v["direction"]},
            ),
            Beat(
                ask=("희망 매매가는 얼마로 생각하고 계세요?", "가격은 어느 선을 보고 계신가요?",
                     "희망가가 어떻게 되세요?"),
                tell=(
                    f"같은 평형이 {v['price']}에 올라와 있어서 저도 일단 {v['price']} 정도를 생각하고 있습니다.",
                    f"호가가 {v['price']}이라 저도 {v['price']}으로 보고 있어요.",
                    f"{v['price']} 정도요. 다른 집 호가를 참고했습니다.",
                ),
                fields={"매매가": v["price"]},
            ),
            Beat(
                ask=("현재 소유자분이 거주 중이신가요?", "지금 누가 살고 계신가요?", "거주 상태를 알려주세요."),
                tell=(
                    f"네, 저희 가족이 살고 있습니다. 입주한 지 {v['hold_years']} 정도밖에 안 돼서 상태는 좋고 "
                    f"확장형에 시스템에어컨도 {v['aircon']} 설치되어 있습니다.",
                    f"저희가 거주 중입니다. {v['hold_years']} 됐고 확장형에 에어컨 {v['aircon']} 있어요.",
                    f"네 실거주 중이에요. 상태는 깨끗합니다. 확장형이고요.",
                ),
                fields={"현상태": "소유자 거주", "확장 여부": "확장형",
                        "시설 상태": f"시스템에어컨 {v['aircon']} 설치"},
            ),
            Beat(
                ask=("매도 시점은 언제쯤 생각하시나요?", "언제까지 정리하고 싶으세요?", "매도 희망 시기가 있나요?"),
                tell=(
                    "회사가 다른 지역으로 이전하면 올해 말쯤 팔려고 하는데 아직 이전이 확정되지는 않았어요.",
                    "직장 이동이 확정되면 그때 팔 생각이라 시점은 아직 모르겠습니다.",
                    "상황을 봐야 해서 시기는 아직 못 정했어요.",
                ),
                note="매도 시점이 회사 이전 확정 여부에 달려 있어 미정",
            ),
            Beat(
                ask=("대출은 어느 정도 있으신가요?", "융자 상황을 알려주세요.", "근저당은 얼마인가요?"),
                tell=(f"대출은 {v['loan_left']} 정도 남아 있습니다.", f"융자 {v['loan_left']} 있습니다.",
                      f"{v['loan_left']} 남았어요."),
                fields={"융자": v["loan_left"]},
                optional=True,
            ),
            Beat(
                ask=("등록 방식은 어떻게 할까요?", "공개 매물로 올려도 될까요?", "노출 범위를 정해두실까요?"),
                tell=(
                    "지금 매물을 등록하면 인터넷에 사진이 바로 공개되나요? 아직 주변 사람들에게 알리고 싶지는 않아서요.",
                    "인터넷에 바로 올라가는 건 부담스러워요. 아는 사람이 볼까 봐서요.",
                    "공개는 안 했으면 합니다. 조용히 진행하고 싶어요.",
                ),
                ack=(
                    "소유자분이 원하시면 공개 매물로 등록하지 않고 조건에 맞는 매수 희망자에게만 소개할 수 있습니다.",
                    "비공개로 두고 조건 맞는 손님에게만 안내드릴 수 있습니다.",
                    "네, 비공개 상태로 관리하겠습니다.",
                ),
                ack_fields={"현매물": "비공개 요청", "진행상태": "상담 접수"},
                note="고객이 인터넷 공개를 원하지 않아 공개 등록은 보류",
                tags=("private_listing_request",),
            ),
        ],
        closings={
            "high": (
                "조건이 맞는 분이 있으면 바로 보여드릴 수 있습니다. 비공개로만 진행해 주세요.",
                "빨리 정리하고 싶긴 해요. 다만 공개는 하지 말아주세요.",
                "적당한 분 계시면 이번 주에도 보여드릴 수 있습니다.",
            ),
            "mid": (
                "우선 최근 거래가격만 문자로 받아본 뒤 가족과 상의하겠습니다.",
                "시세만 먼저 보내주시면 상의해 보겠습니다.",
                "네, 자료 받아보고 다시 연락드릴게요.",
            ),
            "low": (
                "바로 등록하지는 말아주세요. 상담만 기록해 주시면 됩니다.",
                "아직 결정 전이라 등록은 하지 말아주세요.",
                "오늘은 상담만으로 남겨주세요.",
            ),
        },
        tags=("cautious_seller", "many_questions"),
    )


def bp_sell_urgent_wolse(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-urgent-wolse",
        label="매도의뢰",
        persona="출국을 앞둔 급매 소유자",
        openings=greet(v),
        identity=(
            f"사장님, 나는 {j(v['name'], '이라고', '라고')} 하는디 외국에 나가게 돼서 아파트를 빨리 팔아야 쓰겄어요.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 출국 때문에 집을 급하게 정리해야 되야요.",
            f"내 이름은 {j(v['name'], '인디', 'ㄴ디')} 나가서 살게 돼서 집을 팔라고 전화했어라.",
        ),
        identity_fields={"임대인": v["name"]},
        beats=[
            Beat(
                ask=("어느 단지인가요?", "단지와 동호수를 알려주세요.", "어디 아파트세요?"),
                tell=(
                    f"{v['complex']} {v['building']} {v['unit']}예요. 평수는 {v['area']}이고 전용 {v['exclusive']}여.",
                    f"{v['complex']} {v['building']} {j(v['unit'], '이요', '요')}. {v['area']}이고요.",
                    f"{j(v['complex'], '이요', '요')}. {v['building']} {v['unit']}인디 {v['area']}여.",
                ),
                fields={"단지": v["complex"], "동": v["building"], "호": v["unit"], "평형": v["area"]},
            ),
            Beat(
                ask=("희망하시는 매매가는 얼마인가요?", "가격은 얼마로 내놓을까요?", "희망가를 말씀해 주세요."),
                tell=(
                    f"매매가는 {v['price']}으로 내놓고 싶은디 빨리 거래되면 {v['price_floor']}까지는 생각해볼 수 있어요.",
                    f"{v['price']}이요. 급하면 {v['price_floor']}까지도 봐야지요.",
                    f"{v['price']}으로 하고 조정은 상황 봐서 할라요.",
                ),
                fields={"매매가": v["price"]},
                note="빠른 거래 시 하한을 언급했지만 확정 조정가가 아니라 희망가만 유지",
            ),
            Beat(
                ask=("현재 누가 거주하고 있나요?", "세입자가 있으신가요?", "거주 상태는 어떤가요?"),
                tell=(
                    f"월세 세입자가 살고 있어요. 보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}이고 "
                    f"계약 만기는 {v['due_next']}이요.",
                    f"월세 놨어라. {v['wolse_deposit']}에 {v['wolse_rent']}이고 만기는 {v['due_next']}여.",
                    f"세입자 있어요. 보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}이고 만기는 {v['due_next']}이여라.",
                ),
                fields={"월세 보증금": v["wolse_deposit"], "월세 차임": v["wolse_rent"],
                        "만기일": v["due_next"], "현상태": "임차인 거주"},
            ),
            Beat(
                ask=("세입자를 승계하는 조건으로 매도해도 될까요?", "임차인 승계 조건도 가능하신가요?",
                     "세입자 있는 채로 파셔도 되나요?"),
                tell=(
                    "예, 가능하면 그렇게 해도 돼요. 세입자도 아파트를 팔 수 있다는 건 알고 있고요.",
                    "승계해도 되야요. 세입자도 알고 있어라.",
                    "예 그렇게 해도 됩니다.",
                ),
                fields={"명도 조건": "임차인 승계 가능"},
            ),
            Beat(
                ask=("대출은 얼마나 남았나요?", "융자가 있으신가요?", "근저당은요?"),
                tell=(
                    f"대출은 {v['loan_left']} 정도 남았는데 잔금을 받으면 바로 갚을 수 있어요.",
                    f"융자 {v['loan_left']} 있는디 잔금으로 정리할라요.",
                    f"{v['loan_left']} 남았어라.",
                ),
                fields={"융자": v["loan_left"]},
                optional=True,
            ),
            Beat(
                ask=("내부 상태는 어떤가요?", "수리는 하셨어요?", "집 컨디션이 어떤가요?"),
                tell=(
                    f"지은 지 좀 됐지만 {v['repair_years']} 전에 주방하고 욕실을 수리했고 거실도 확장되어 있어요.",
                    f"{v['repair_years']} 전에 손봤어라. 거실은 확장돼 있고요.",
                    f"오래되긴 했는디 수리는 해놨어요.",
                ),
                fields={"시설 상태": f"{v['repair_years']} 전 주방·욕실 수리", "확장 여부": "거실 확장"},
                optional=True,
            ),
        ],
        closings={
            "high": (
                f"출국이 {v['depart']}이라 그전에 계약이라도 하고 싶어요.",
                f"{v['depart']}에 나가야 해서 급해요. 빨리 좀 부탁드려요.",
                "이번 달 안에 계약했으면 좋겄어요.",
            ),
            "mid": (
                "네, 말씀하신 조건으로 접수하겠습니다.",
                "네, 매물장에 등록해 두고 연락드리겠습니다.",
                "확인해서 접수해 두겠습니다.",
            ),
            "low": (
                "일단 시세만 좀 알려주쇼. 그거 보고 정할라요.",
                "아직 확정은 아니라서 상담만 남겨주세요.",
                "가격 보고 다시 연락드릴게요.",
            ),
        },
        tags=("dialect_jeolla", "urgent_sale", "tenant_in_place"),
    )


def bp_sell_proxy(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-proxy",
        label="매도의뢰",
        persona="부모 명의를 대신 문의하는 자녀",
        openings=greet(v, *GREET_PLAIN),
        identity=(
            f"저는 {j(v['name'], '이고', '고')} {v['kin']} 명의로 된 아파트를 대신 매도 문의하려고 전화했습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['kin']} 집을 대신 알아보고 있어요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하고요, {v['kin']} 명의 아파트 건으로 여쭤봅니다.",
        ),
        identity_fields={"임대인": v["kin"], "비고": f"{v['name']}이 대리 문의"},
        beats=[
            Beat(
                ask=("어느 단지와 동호수인가요?", "단지랑 동호수 알려주세요.", "어디 아파트인가요?"),
                tell=(
                    f"{v['complex']} {v['building']} {v['unit']}입니다.",
                    f"{j(v['complex'], '이요', '요')}. {v['building']} {v['unit']}입니다.",
                    f"{v['complex']} {v['building']} {j(v['unit'], '이에요', '예요')}.",
                ),
                fields={"단지": v["complex"], "동": v["building"], "호": v["unit"]},
            ),
            Beat(
                ask=("평수는 어떻게 되나요?", "평형 알려주시겠어요?", "몇 평인가요?"),
                tell=(
                    f"평수는 {v['area2']}이었던 것 같은데 잠시만요. 서류를 확인하니까 {v['area']}, "
                    f"전용 {v['exclusive']}이 맞습니다.",
                    f"{v['area2']}인 줄 알았는데 확인해 보니 {v['area']}이 맞네요.",
                    f"잠깐만요… 네, {v['area']}입니다. 제가 잘못 알고 있었어요.",
                ),
                fields={"평형": v["area"]},
                note=f"평형을 {v['area2']}으로 말했다가 서류 확인 후 정정해 마지막 값만 유지",
                tags=("self_correction",),
            ),
            Beat(
                ask=("희망 매매가는 얼마인가요?", "가격은 어떻게 생각하고 계신가요?", "희망가를 알려주세요."),
                tell=(
                    f"{v['kin']}은 {v['price']} 정도를 생각하시는데 최근 시세에 따라 {v['price_floor']}까지는 "
                    "협의할 수 있다고 하셨어요.",
                    f"{v['price']}으로 보고 계세요. 시세 보고 조정은 가능하다고 하십니다.",
                    f"{v['price']}이요. 다만 협의 여지는 있다고 하셨습니다.",
                ),
                fields={"매매가": v["price"]},
                note="협의 하한을 언급했지만 확정 조정가가 아니라 희망가만 유지",
            ),
            Beat(
                ask=("현재 소유자는 한 분인가요?", "명의는 어떻게 되어 있나요?", "소유자 확인 좀 할게요."),
                tell=(
                    f"아니요. {v['kin']}과 {v['kin2']} 두 분의 공동명의입니다. 매도 자체에는 동의했지만 "
                    "매매가는 시세를 확인한 뒤 정하자고 하셨습니다.",
                    f"{v['kin']}하고 {v['kin2']} 공동명의예요. 가격은 아직 두 분이 합의 전입니다.",
                    f"두 분 공동명의입니다. {v['kin2']}도 매도에는 동의하셨어요.",
                ),
                note="공동명의자 두 명의 동의와 위임 확인이 필요하고 매매가는 합의 전임",
                tags=("co_ownership",),
            ),
            Beat(
                ask=("현재 거주자는 어떻게 되나요?", "세입자가 있나요?", "지금 누가 살고 있습니까?"),
                tell=(
                    f"현재는 전세 세입자가 살고 있고 보증금은 {v['sale_deposit']}, 만기는 {v['due_next']}입니다.",
                    f"전세 세입자 있습니다. {v['sale_deposit']}이고 만기 {v['due_next']}이에요.",
                    f"세입자 거주 중이고 보증금은 {v['sale_deposit']}, 만기는 {v['due_next']}입니다.",
                ),
                fields={"현재 보증금": v["sale_deposit"], "만기일": v["due_next"], "현상태": "임차인 거주"},
            ),
            Beat(
                ask=("대출은 확인되셨나요?", "융자가 있나요?", "근저당 여부는요?"),
                tell=(
                    "대출은 없다고 들었지만 등기부는 확인해봐야 합니다.",
                    "없다고 하시는데 제가 등기부를 아직 못 봤어요.",
                    "그건 확인이 필요합니다.",
                ),
                note="융자 유무를 등기부로 확인하지 못해 미확인",
                optional=True,
            ),
            Beat(
                ask=("연락처는 어디로 드릴까요?", "번호 남겨주시겠어요?", "연락은 누구에게 드릴까요?"),
                tell=(
                    f"제 번호로 주세요. {v['phone']}입니다.",
                    f"{v['phone']}으로 연락 주시면 제가 전달하겠습니다.",
                    f"저한테 주세요. {j(v['phone'], '이에요', '예요')}.",
                ),
                fields={"임대인 전화": v["phone"]},
                optional=True,
            ),
        ],
        closings={
            "high": (
                "동의는 다 받아둘 테니 매물부터 올려주세요.",
                "위임장은 이번 주에 준비하겠습니다. 진행 부탁드려요.",
                "빨리 진행했으면 합니다.",
            ),
            "mid": (
                "정식 등록 전에 공동명의자 두 분의 동의와 위임 여부를 확인하겠습니다.",
                "네, 명의자 확인 후 진행하겠습니다.",
                "동의 확인되면 접수하겠습니다.",
            ),
            "low": (
                "상담만 기록해주세요. 아직 인터넷에는 공개하지 말아주시고 가족과 상의한 뒤 다시 연락드리겠습니다.",
                "오늘은 문의만 드린 거예요. 등록은 하지 말아주세요.",
                "가족들과 얘기하고 다시 연락드릴게요.",
            ),
        },
        tags=("proxy_caller", "co_ownership", "many_corrections"),
    )


def bp_sell_rent_listing(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-rent-listing",
        label="매도의뢰",
        persona="월세를 놓으려는 고령 임대인",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이라예', '라예')}. 집주인은 내고예.",
            f"내 이름은 {j(v['name'], '입니더', '입니더')}. 내 집이라예.",
            f"제 이름은 {j(v['name'], '이고예', '고예')}, 명의도 내 앞으로 돼 있심더.",
        ),
        identity_fields={"임대인": v["name"]},
        beats=[
            Beat(
                ask=("전세로 놓으시는 건가요, 월세로 놓으시는 건가요?", "임대 조건은 어떻게 보세요?",
                     "전세와 월세 중 어느 쪽입니까?"),
                tell=(
                    "어… 월세로. 월세로 놔야지예. 전세는 요새 뭐 무섭다 카데예.",
                    "월세라예. 다달이 나오는 게 낫지예.",
                    "월세로 해주이소.",
                ),
            ),
            Beat(
                ask=("어느 단지신가요?", "단지랑 동호수 알려주세요.", "어디 아파트입니까?"),
                tell=(
                    f"{v['complex']}… {v['complex']} 맞나. 예, {v['complex']} {v['building']} {v['unit']}라예.",
                    f"{j(v['complex'], '이라예', '라예')}. {v['building']} {v['unit']}고예.",
                    f"{v['complex']} 있잖습니꺼. 거기 {v['building']} {v['unit']}입니더.",
                ),
                fields={"단지": v["complex"], "동": v["building"], "호": v["unit"]},
            ),
            Beat(
                ask=("보증금이랑 월세는 얼마로 생각하고 계세요?", "월세 조건 알려주세요.",
                     "보증금은 얼마, 월세는 얼마로 볼까요?"),
                tell=(
                    f"어어, 보증금은 {v['wolse_deposit_spoken_slip']}에… 아이다 아이다, "
                    f"{v['wolse_deposit_spoken']}에 월세 {v['wolse_rent_spoken']}. "
                    f"{v['wolse_deposit_spoken']}에 {v['wolse_rent_spoken']}으로 해주이소.",
                    f"{v['wolse_deposit_spoken']}에 {v['wolse_rent_spoken']}이라예.",
                    f"보증금 {v['wolse_deposit_spoken']}, 월세는 {v['wolse_rent_spoken']} 받을랍니더.",
                ),
                ack=(
                    f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}이요. 다시 확인드릴게요, 맞으시죠?",
                    f"네, 보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}으로 적겠습니다.",
                    f"보증금 {v['wolse_deposit']}, 월세 {v['wolse_rent']} 확인했습니다.",
                ),
                ack_fields={"월세 보증금": v["wolse_deposit"], "월세 차임": v["wolse_rent"]},
                note="보증금을 다른 금액으로 말했다가 정정해 마지막 값만 유지",
                tags=("spoken_number_normalization", "agent_readback_evidence", "self_correction"),
            ),
            Beat(
                ask=("지금 그 집에 누가 살고 계세요?", "현재 거주자가 있습니까?", "지금은 비어 있나요?"),
                tell=(
                    "아무도 없어예. 아들이 살다가 나가가 지금 비었심더.",
                    "비었심더. 지난달에 나갔어예.",
                    "지금 아무도 안 삽니더. 공실이라예.",
                ),
                fields={"현상태": "공실"},
            ),
            Beat(
                ask=("도배나 수리는 하고 내놓으실 건가요?", "내부 수리 계획이 있으세요?", "집 상태는 어떻습니까?"),
                tell=(
                    "그건… 아들하고 좀 상의를 해봐야 되겠는데. 내가 혼자 정하기가 좀 그래가.",
                    "어… 그거는 자식들하고 얘기해보고 알려드리께예.",
                    "수리는 아직 모르겠심더.",
                ),
                note="도배·수리 여부는 고객이 가족과 상의 후 알려주기로 해 미정",
                optional=True,
            ),
            Beat(
                ask=("입주는 언제부터 가능하세요?", "입주 가능일은 언제쯤일까요?", "언제부터 들어갈 수 있습니까?"),
                tell=(
                    "그것도 인자… 아들한테 물어보고 다시 전화드리께예.",
                    "그거는 아직 모르겠심더. 다시 연락드리께예.",
                    "날짜는 좀 있다가 말씀드리께예.",
                ),
                note="입주 가능일은 고객이 다시 연락하기로 해 미정",
                optional=True,
            ),
            Beat(
                ask=("연락처는 이 번호로 저장할까요?", "번호 좀 알려주세요.", "연락처 확인하겠습니다."),
                tell=(f"예 예, {v['phone']} 이거로 하이소.", f"{v['phone']} 이 번호라예.",
                      f"예 {v['phone']}으로 해주이소."),
                fields={"임대인 전화": v["phone"]},
            ),
        ],
        closings={
            "high": (
                "사람 있으면 바로 보여드리께예. 빨리 좀 부탁합니더.",
                "이번 달 안에 나갔으면 좋겠심더.",
                "언제든 보여드릴 수 있심더.",
            ),
            "mid": (
                "네, 확인된 것만 매물장에 남기고 나머지는 다시 여쭙겠습니다.",
                "네, 접수해 두고 연락드리겠습니다.",
                "지금 내용으로 등록해 두겠습니다.",
            ),
            "low": (
                "아직 확실친 않은데 일단 물어본 거라예.",
                "가족들하고 얘기하고 다시 전화드리께예.",
                "천천히 봐도 되니까 기록만 해주이소.",
            ),
        },
        tags=("dialect_gyeongsang", "elderly_caller", "deferred_fields"),
    )


def bp_sell_old_manager(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-old-manager",
        label="매도의뢰",
        persona="구축 아파트를 정리하려는 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이유', '유')}. {v['complex']} 집 하나 내놓을라구유.",
            f"내 이름은 {j(v['name'], '이고유', '고유')}, {v['complex']} 매도 좀 물어볼라구 전화했슈.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} 집을 정리하려구유.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"]},
        beats=[
            Beat(
                ask=("동호수가 어떻게 되나요?", "몇 동 몇 호세요?", "동과 호수 알려주세요."),
                tell=(f"{v['building']} {v['unit']}이유.", f"{v['building']} {v['unit']}입니다.",
                      f"어… {v['building']} {v['unit']}유."),
                fields={"동": v["building"], "호": v["unit"]},
            ),
            Beat(
                ask=("평수랑 연식은 어떻게 되나요?", "몇 평인가요?", "평형 알려주시겠어요?"),
                tell=(
                    f"{v['area']}이구유, 지은 지는 좀 됐슈. 전용은 {v['exclusive']}이유.",
                    f"{v['area']}입니다. 오래된 아파트유.",
                    f"{v['area']}이유. 구축이구유.",
                ),
                fields={"평형": v["area"]},
            ),
            Beat(
                ask=("희망 매매가는 얼마인가요?", "가격은 얼마로 볼까요?", "희망가를 알려주세요."),
                tell=(f"{v['price']}이면 좋겠슈.", f"{v['price']} 정도유.", f"{v['price']}으로 해주세유."),
                ack=(f"{v['price']}으로 적겠습니다.", f"네, 매매가 {v['price']} 확인했습니다.",
                     f"{v['price']}이요. 기록하겠습니다."),
                fields={"매매가": v["price"]},
            ),
            Beat(
                ask=("현재 거주자가 있나요?", "지금 누가 살고 있습니까?", "공실인가요?"),
                tell=("지금은 비어 있슈. 작년에 나가고 그대로유.", "공실이유. 아무도 안 살아유.",
                      "비었슈. 그래서 아무 때나 보여드릴 수 있슈."),
                fields={"현상태": "공실"},
            ),
            Beat(
                ask=("내부 상태는 어떤가요?", "수리는 하셨나요?", "도배 장판은요?"),
                tell=(
                    f"{v['repair_years']} 전에 도배 장판은 새로 했슈. 보일러도 갈았구유.",
                    f"수리는 {v['repair_years']} 전에 다 했슈.",
                    "손볼 데는 크게 없슈.",
                ),
                fields={"시설 상태": f"{v['repair_years']} 전 도배·장판 교체"},
                optional=True,
            ),
            Beat(
                ask=("담당자를 지정해 드릴까요?", "저희 쪽 담당은 정해두겠습니다.", "담당자 배정하겠습니다."),
                tell=(
                    f"예, 그렇게 해주세유. {v['manager']}씨가 맡아주시면 좋겠슈.",
                    f"{v['manager']}씨로 해주세유.",
                    "알아서 정해주세유.",
                ),
                ack=(f"네, 담당은 {v['manager']}로 지정하겠습니다.", f"{v['manager']}로 배정해 두겠습니다.",
                     f"담당자는 {v['manager']}입니다."),
                ack_fields={"담당자": v["manager"]},
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주시겠어요?", "번호 좀 주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{j(v['phone'], '이유', '유')}.", f"{v['phone']}으로 해주세유.", f"번호는 {v['phone']}입니다."),
                fields={"임대인 전화": v["phone"]},
            ),
        ],
        closings={
            "high": ("빨리 팔았으면 좋겠슈. 연락 주세유.", "이번 달 안에 정리하고 싶슈.",
                     "보러 온다면 언제든 좋슈."),
            "mid": ("네, 매물장에 접수해 두겠습니다.", "확인해서 등록하겠습니다.",
                    "네, 등록하고 연락드리겠습니다."),
            "low": ("일단 시세나 좀 알려주세유.", "급한 건 아니라서 천천히 봐주세유.",
                    "상담만 기록해 주세유."),
        },
        tags=("dialect_chungcheong", "old_building"),
    )


def bp_buy_newlywed(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-newlywed",
        label="매수문의",
        persona="신혼집을 찾는 부부",
        openings=greet(v),
        identity=(
            f"저는 {j(v['name'], '이고', '고')} 신혼집으로 사용할 아파트를 찾고 있습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 결혼하면서 살 집을 알아보고 있어요.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 신혼집을 보고 있습니다.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분은 어떻게 되세요?", "매매로 보시나요?", "어떤 거래를 찾으세요?"),
                tell=(
                    f"거래 구분은 매매이고 {j(v['complex'], '이나', '나')} {v['complex2']} 단지를 우선적으로 보고 있어요.",
                    f"매매요. {v['complex']}하고 {v['complex2']} 위주로 보고 있습니다.",
                    f"매매로 볼 생각이고 {v['complex']}이 1순위예요.",
                ),
                fields={"거래 구분": "매매", "희망 단지": v["complex"]},
            ),
            Beat(
                ask=("몇 평을 원하시나요?", "평형은 어느 정도 보세요?", "희망 평형 알려주세요."),
                tell=(
                    f"{v['area']}이나 {v['area2']}을 찾고 있고 전용면적으로는 {v['exclusive']}면 됩니다.",
                    f"{v['area']} 정도요. 전용 {v['exclusive']}이면 충분해요.",
                    f"{v['area']}이요.",
                ),
                fields={"희망 평형": v["area"]},
            ),
            Beat(
                ask=("금액 조건은 어떻게 되나요?", "예산은 어느 정도세요?", "자금 계획도 알려주시겠어요?"),
                tell=(
                    f"금액 조건은 최대 {v['budget']}까지이고 현금 {v['cash']}과 대출 {v['loan']}을 사용할 예정입니다.",
                    f"{v['budget']}까지요. 현금 {v['cash']}에 대출 {v['loan']} 예정입니다.",
                    f"최대 {v['budget']}입니다.",
                ),
                ack=(f"매매가 {v['budget']} 이하로 보겠습니다.", f"네, {v['budget']} 기준으로 찾아보겠습니다.",
                     f"{v['budget']} 이하로 정리하겠습니다."),
                fields={"금액 원문": v["budget"]},
            ),
            Beat(
                ask=("선호 조건이 있나요?", "층이나 향은 어떻게 보세요?", "제외하고 싶은 조건이 있을까요?"),
                tell=(
                    f"{v['floor_min']} 이상 {v['direction']}을 원하고 저층과 복도식은 제외하고 싶습니다.",
                    f"{v['floor_min']} 이상이면 좋겠고 {v['direction']} 선호합니다.",
                    "저층만 아니면 됩니다.",
                ),
                note="선호 층과 향은 참고 조건이며 확정 필드로 두지 않음",
                optional=True,
            ),
            Beat(
                ask=("입주 시기는 언제세요?", "이사 희망일이 어떻게 되나요?", "언제까지 들어가야 하세요?"),
                tell=(
                    f"현재 전세계약이 {v['expire']}에 끝나서 {v['move_from']}부터 {v['move_to']} 사이에 "
                    "입주할 수 있어야 합니다.",
                    f"{v['move_from']}에서 {v['move_to']} 사이요.",
                    f"{v['move_to']}까지는 들어가야 합니다.",
                ),
                fields={"이사일 원문": f"{v['move_from']}~{v['move_to']}"},
            ),
            Beat(
                tell=(
                    "아직 자녀는 없지만 내년에 계획하고 있어서 어린이집과 초등학교가 가까우면 좋겠습니다.",
                    "나중에 아이 생각하면 학군도 봐야 할 것 같아요.",
                    "학교 가까운 곳이면 더 좋고요.",
                ),
                ask=("그 외에 고려하실 조건이 있나요?", "생활 여건은 어떤 걸 보세요?", "추가 조건이 있을까요?"),
                note="학군 선호는 참고 사항이며 확정 조건이 아님",
                optional=True,
            ),
            Beat(
                ask=("연락처 알려주시겠어요?", "번호 남겨주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.", f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
            ),
        ],
        closings={
            "high": (
                "네, 상태가 괜찮으면 이번 주말에 방문하고 바로 계약할 수 있습니다.",
                "조건 맞으면 주말에 바로 보러 가겠습니다.",
                "이번 달 안에 계약하고 싶어요.",
            ),
            "mid": (
                "네, 조건에 맞는 매물이 나오면 연락드리겠습니다.",
                "구입장에 등록해 두고 연락드리겠습니다.",
                "네, 접수해 두겠습니다.",
            ),
            "low": (
                "당장은 아니고 시세만 좀 보려고요. 자료만 보내주세요.",
                "아직 계약할 단계는 아니에요. 사진만 먼저 받아볼게요.",
                "일단 알아보는 중이라 급하진 않습니다.",
            ),
        },
        tags=("newlywed", "many_fields"),
    )


def bp_buy_commuter_jeonse(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-commuter-jeonse",
        label="매수문의",
        persona="직장 때문에 이사하는 전세 수요자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '입니더', '입니더')}. 회사 때문에 이쪽으로 이사 와야 돼서 알아보고 있심더.",
            f"내 이름은 {j(v['name'], '이라예', '라예')}. 직장 옮기면서 집을 구합니더.",
            f"제 이름은 {j(v['name'], '이고예', '고예')}, 발령 때문에 전세를 알아봅니더.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분은 어떻게 생각하고 계세요?", "매매인가요 전세인가요?", "어떤 조건으로 보세요?"),
                tell=("매매는 아니고 전세로 구하고 있습니더.", "전세라예.", "전세로 볼랍니더."),
                fields={"거래 구분": "전세"},
            ),
            Beat(
                ask=("희망하는 단지가 있나요?", "보고 계신 단지가 있습니까?", "어느 단지를 원하세요?"),
                tell=(
                    f"{j(v['complex'], '이나', '나')} {v['complex2']}면 좋겠심더. 지하철역 가까운 단지라야 출퇴근하기 편해예.",
                    f"{v['complex']} 위주로 보고 있심더. 역 가까우면 좋겠고예.",
                    f"{j(v['complex'], '이라예', '라예')}.",
                ),
                fields={"희망 단지": v["complex"]},
            ),
            Beat(
                ask=("지역은 어디로 보세요?", "어느 동네가 좋으세요?", "희망 지역을 알려주세요."),
                tell=(
                    f"{v['region']} 쪽이라예.",
                    f"{v['region']}이면 됩니더.",
                    f"{v['region']} 근처로 보고 있심더.",
                ),
                fields={"희망 지역": v["region"]},
            ),
            Beat(
                ask=("평수는 어느 정도로 찾으세요?", "희망 평형이 어떻게 되나요?", "몇 평 보십니까?"),
                tell=(
                    f"{v['area']}으로 보고 있고 전용 {v['exclusive']} 정도면 됩니더.",
                    f"{v['area']}이면 충분합니더.",
                    f"{v['area']} 정도예.",
                ),
                fields={"희망 평형": v["area"]},
            ),
            Beat(
                ask=("전세금 조건은 얼마인가요?", "보증금은 어디까지 가능하세요?", "예산을 알려주세요."),
                tell=(
                    f"최대 {v['jeonse']}까지 가능하고 전세대출을 {v['loan']} 정도 받을 예정입니더.",
                    f"{v['jeonse']}까지라예. 대출도 좀 낄 겁니더.",
                    f"{v['jeonse']} 안쪽으로 봅니더.",
                ),
                ack=(f"전세금 {v['jeonse']} 이하로 정리하겠습니다.", f"네, {v['jeonse']} 확인했습니다.",
                     f"{v['jeonse']} 이하로 보겠습니다."),
                fields={"금액 원문": v["jeonse"]},
            ),
            Beat(
                ask=("입주일은 언제인가요?", "언제 들어가셔야 하나요?", "이사 시기가 어떻게 되세요?"),
                tell=(
                    f"지금 사는 집 계약이 {v['expire']}에 끝나서 {v['move_from']}부터 {v['move_to']} 사이에 "
                    "들어가야 합니더.",
                    f"{v['move_from']}에서 {v['move_to']} 사이라예.",
                    f"{v['move_to']}까지는 들어가야 됩니더.",
                ),
                fields={"이사일 원문": f"{v['move_from']}~{v['move_to']}"},
            ),
            Beat(
                ask=("층이나 방향 조건이 있나요?", "선호하시는 층이 있습니까?", "향은 어떻게 보세요?"),
                tell=(
                    f"층은 {v['floor_min']} 이상이면 좋겠고 방향은 {v['direction']}을 원합니더.",
                    f"{v['floor_min']} 이상이면 좋겠심더.",
                    "너무 낮은 층만 아니면 됩니더.",
                ),
                note="선호 층과 향은 참고 조건이며 확정 필드로 두지 않음",
                optional=True,
            ),
            Beat(
                ask=("연락처 알려주시겠어요?", "번호 좀 남겨주세요.", "연락은 어디로 드릴까예?"),
                tell=(f"{v['phone']}입니더.", f"{v['phone']}으로 주이소.", f"번호는 {j(v['phone'], '이라예', '라예')}."),
                fields={"전화번호": v["phone"]},
            ),
        ],
        closings={
            "high": (
                "예, 조건 맞는 집 있으면 이번 주에 바로 보러 갈 수 있심더.",
                "빨리 정해야 돼서예. 나오면 바로 연락 주이소.",
                "이번 주말에라도 보러 가겠심더.",
            ),
            "mid": (
                "네, 조건에 맞는 매물을 찾아 연락드리겠습니다.",
                "구입장에 등록해 두겠습니다.",
                "네, 접수하고 알려드리겠습니다.",
            ),
            "low": (
                "일단 어떤 게 있는지만 보고 싶심더.",
                "아직 확정은 아이라서 자료만 좀 주이소.",
                "천천히 봐도 됩니더.",
            ),
        },
        tags=("dialect_gyeongsang", "commuter"),
    )


def bp_buy_firstjob_wolse(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-firstjob-wolse",
        label="매수문의",
        persona="혼자 살 집을 찾는 사회초년생",
        openings=greet(v, "안녕하세요. 어떤 아파트를 찾고 계신가요?", *GREET_PLAIN),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 회사 근처에서 혼자 살 집을 알아보고 있습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 자취방을 구하고 있어요.",
            f"제 이름은 {j(v['name'], '이에요', '예요')}. 혼자 살 아파트를 보고 있어요.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분은 어떻게 되나요?", "월세로 보시는 건가요?", "전세인가요 월세인가요?"),
                tell=("거래 구분은 월세로 생각하고 있어요.", "월세요.", "월세로 보고 있습니다."),
                fields={"거래 구분": "월세"},
            ),
            Beat(
                ask=("희망하는 단지가 있나요?", "보시는 단지가 있으세요?", "어느 쪽으로 찾으세요?"),
                tell=(
                    f"{j(v['complex'], '이나', '나')} {v['complex2']}를 보고 있습니다.",
                    f"{v['complex']} 쪽이요.",
                    f"{v['region']}에서 {v['complex']} 위주로요.",
                ),
                fields={"희망 단지": v["complex"]},
            ),
            Beat(
                ask=("몇 평을 원하시나요?", "평형은 어느 정도요?", "넓이는 어느 정도 보세요?"),
                tell=(
                    f"{v['area_small']} 정도면 되고 너무 큰 집은 필요 없습니다.",
                    f"{v['area_small']}이요.",
                    f"{v['area_small']} 정도가 딱 좋을 것 같아요.",
                ),
                fields={"희망 평형": v["area_small"]},
            ),
            Beat(
                ask=("금액 조건은 어떻게 되나요?", "보증금과 월세는요?", "예산을 알려주세요."),
                tell=(
                    f"보증금은 최대 {v['wolse_deposit']}, 월세는 관리비를 제외하고 {v['wolse_rent']} 이하로 "
                    "생각하고 있습니다.",
                    f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']} 이하요.",
                    f"{v['wolse_deposit']}에 {v['wolse_rent']}까지 가능합니다.",
                ),
                fields={"금액 원문": f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}"},
            ),
            Beat(
                ask=("입주 시기는 언제인가요?", "언제쯤 들어가세요?", "이사 시기가 정해졌나요?"),
                tell=(
                    "회사 발령이 아직 확정되지 않아서 두 달 정도 뒤가 될 것 같아요.",
                    "발령이 안 나서 시기는 아직 확실하지 않습니다.",
                    "정확한 날짜는 아직 모르겠어요.",
                ),
                note="회사 발령이 확정되지 않아 입주 시기가 미정",
            ),
            Beat(
                ask=("연락처 남겨주시겠어요?", "번호 알려주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 부탁드려요.", f"{j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                optional=True,
            ),
        ],
        closings={
            "high": (
                "조건 맞는 게 있으면 이번 주에 보러 가고 싶습니다.",
                "발령만 나면 바로 계약할 수 있어요.",
                "빨리 정하고 싶습니다.",
            ),
            "mid": (
                "네, 조건에 맞는 매물을 안내드리겠습니다.",
                "구입장에 남겨두고 연락드리겠습니다.",
                "네, 접수해 두겠습니다.",
            ),
            "low": (
                "아직 바로 계약하는 건 아니고 가격대와 사진만 먼저 받아보고 싶습니다.",
                "지금은 알아보는 단계라 자료만 주세요.",
                "급하진 않아서 천천히 봐도 됩니다.",
            ),
        },
        tags=("first_job", "short_dialogue"),
    )


def bp_buy_large_family(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-large-family",
        label="매수문의",
        persona="대형 평형을 찾는 다자녀 가구",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} 가족이 함께 살 대형 아파트를 찾고 있습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 식구가 많아서 큰 평형을 봅니다.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 온 가족이 같이 살 집을 알아보고 있어요.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분과 희망 단지를 알려주세요.", "매매로 보시나요?", "어떤 조건으로 찾으세요?"),
                tell=(
                    f"거래 구분은 매매입니다. 희망 단지는 {j(v['complex'], '과', '와')} {v['complex2']}이고 두 단지에 "
                    "적합한 매물이 없다면 인근 단지도 볼 수 있습니다.",
                    f"매매고요, {v['complex']} 아니면 {v['complex2']}입니다.",
                    f"매매로 {v['complex']} 보고 있습니다.",
                ),
                fields={"거래 구분": "매매", "희망 단지": v["complex"]},
            ),
            Beat(
                ask=("원하는 평수는 어느 정도인가요?", "평형은요?", "몇 평을 보십니까?"),
                tell=(
                    f"{v['area_large']} 정도를 원하고 전용면적은 최소 {v['exclusive_large']}가 필요합니다. "
                    f"부부와 {v['kids']}, 부모님 한 분이 함께 살 예정이라 방은 네 개 이상이어야 합니다.",
                    f"{v['area_large']}이요. 방 네 개는 있어야 합니다.",
                    f"{v['area_large']} 이상이면 좋겠습니다.",
                ),
                fields={"희망 평형": v["area_large"]},
            ),
            Beat(
                ask=("금액 조건은 어떻게 되나요?", "예산 범위를 알려주세요.", "총 비용은 어느 선인가요?"),
                tell=(
                    f"아파트 매매가는 {v['budget']} 이하로 보고 있고 취득비용과 수리비까지 포함한 전체 비용은 "
                    f"{v['budget_slip']}을 넘으면 안 됩니다.",
                    f"{v['budget']} 이하요. 총비용은 {v['budget_slip']}까지입니다.",
                    f"{v['budget']}까지 봅니다.",
                ),
                ack=(f"매매가 {v['budget']} 이하로 정리하겠습니다.", f"네, {v['budget']} 기준으로 보겠습니다.",
                     f"{v['budget']} 이하 확인했습니다."),
                fields={"금액 원문": v["budget"]},
            ),
            Beat(
                ask=("구축 아파트도 괜찮으신가요?", "연식은 상관없으세요?", "구축도 보실 수 있나요?"),
                tell=(
                    "입지와 구조가 좋으면 구축도 괜찮지만 주차가 편하고 엘리베이터가 두 대 이상이어야 합니다. "
                    "부모님 때문에 병원과 대중교통도 가까워야 합니다.",
                    "구축도 봅니다. 다만 주차는 편해야 해요.",
                    "연식보다는 구조가 중요합니다.",
                ),
                note="주차·엘리베이터·병원 접근성은 참고 조건이며 확정 필드로 두지 않음",
                optional=True,
            ),
            Beat(
                ask=("층과 방향은 어떻게 보세요?", "선호 층이 있나요?", "제외할 층이 있을까요?"),
                tell=(
                    f"층은 {v['floor_min']} 이상, 방향은 {v['direction']}을 선호하고 1층과 꼭대기 층은 "
                    "제외해주세요.",
                    f"{v['floor_min']} 이상이면 좋겠습니다.",
                    "1층만 아니면 됩니다.",
                ),
                note="선호 층과 향은 참고 조건이며 확정 필드로 두지 않음",
                optional=True,
            ),
            Beat(
                ask=("입주 희망일은 언제인가요?", "언제까지 들어가셔야 하나요?", "이사 시기를 알려주세요."),
                tell=(
                    f"입주 희망일은 {v['move_next']}이라 그전까지 명도가 확실해야 합니다.",
                    f"{v['move_next']}입니다. 명도가 확실한 매물이어야 해요.",
                    f"{v['move_next']}까지요.",
                ),
                fields={"이사일 원문": v["move_next"]},
            ),
            Beat(
                ask=("연락처 알려주시겠어요?", "번호 남겨주세요.", "연락처 확인하겠습니다."),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 연락 주세요.", f"번호는 {v['phone']}입니다."),
                fields={"전화번호": v["phone"]},
            ),
        ],
        closings={
            "high": (
                "네, 적합한 아파트가 있으면 이번 주 안에 방문하고 이달 중 계약할 수 있습니다.",
                "조건 맞으면 바로 보러 가겠습니다.",
                "빠르게 진행하고 싶습니다.",
            ),
            "mid": (
                "네, 조건에 맞는 매물을 찾아 연락드리겠습니다.",
                "구입장에 등록하고 안내드리겠습니다.",
                "네, 접수하겠습니다.",
            ),
            "low": (
                "우선 어떤 매물이 있는지만 정리해서 보내주세요.",
                "아직 결정 전이라 자료만 받아보겠습니다.",
                "천천히 보려고 합니다.",
            ),
        },
        tags=("large_family", "many_fields"),
    )


def bp_buy_pet_wolse(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-pet-wolse",
        label="매수문의",
        persona="조건을 여러 번 바꾸는 반려동물 양육자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 처음에는 전세를 알아보려고 했는디 근무 기간이 "
            "확실하지 않아서 월세로 구할라고요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는디요, 전세 볼라다가 월세로 바꿨어라.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 월세로 알아보고 있어라.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("그러면 최종 거래 구분은 월세인가요?", "월세로 확정하신 건가요?", "최종 조건을 확인할게요."),
                tell=("네, 월세가 맞습니다.", "예 월세로 해주쇼.", "월세요. 그걸로 확정입니다."),
                fields={"거래 구분": "월세"},
                note="전세로 문의했다가 월세로 정정해 마지막 조건만 유지",
                tags=("self_correction",),
            ),
            Beat(
                ask=("희망 단지는 어디인가요?", "보시는 단지가 있어요?", "어느 쪽을 원하세요?"),
                tell=(
                    f"{v['region']} 쪽인디 희망 단지는 {j(v['complex'], '이나', '나')} {j(v['complex2'], '이여라', '여라')}.",
                    f"{v['region']}이요. {v['complex']} 쪽으로 보고 있어라.",
                    f"{v['region']}에서 {v['complex']} 위주로 봅니다.",
                ),
                fields={"희망 단지": v["complex"], "희망 지역": v["region"]},
            ),
            Beat(
                ask=("평수는 어느 정도 보세요?", "희망 평형이 어떻게 되나요?", "몇 평 찾으세요?"),
                tell=(
                    f"평수는 처음에는 {v['area_large']}을 생각했는디 혼자 살기에는 너무 큰 것 같아서 {v['area_small']}으로 "
                    f"찾고 싶어라. 전용 {v['exclusive_small']} 정도면 됩니다.",
                    f"{v['area_large']} 볼라다가 {v['area_small']}으로 줄였어라.",
                    f"{v['area_small']}이면 되겄어라.",
                ),
                fields={"희망 평형": v["area_small"]},
                note=f"희망 평형을 {v['area_large']}에서 {v['area_small']}으로 정정해 마지막 값만 유지",
                tags=("self_correction",),
            ),
            Beat(
                ask=("금액 조건은 어떻게 되나요?", "보증금과 월세는요?", "예산을 알려주세요."),
                tell=(
                    f"보증금은 {v['wolse_deposit']} 이하, 월세는 {v['wolse_rent']} 이하로 생각하고 있어라. "
                    "가능하면 보증금을 조금 높이고 월세를 낮추는 조건도 괜찮고요.",
                    f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']} 이하요.",
                    f"{v['wolse_deposit']}에 {v['wolse_rent']}까지 봅니다.",
                ),
                ack=(
                    f"보증금 {v['wolse_deposit']} 이하에 월세 {v['wolse_rent']} 이하로 기록하겠습니다.",
                    f"네, 보증금 {v['wolse_deposit']}, 월세 {v['wolse_rent']} 확인했습니다.",
                    f"{v['wolse_deposit']}에 {v['wolse_rent']} 이하로 보겠습니다.",
                ),
                ack_fields={"금액 원문": f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}"},
                note="보증금을 올리고 월세를 낮추는 조합도 가능하다고 했으나 확정 조건은 아님",
                tags=("agent_readback_evidence",),
            ),
            Beat(
                ask=("입주 시기는 언제인가요?", "언제 들어가시려고요?", "이사 시기가 어떻게 되세요?"),
                tell=(
                    f"현재 집 계약이 {v['expire_late']}에 끝나서 {v['move_next']} 이후에 입주하고 싶어라.",
                    f"{v['move_next']} 이후요.",
                    f"{v['move_next']}쯤이면 좋겄어요.",
                ),
                fields={"이사일 원문": v["move_next"]},
            ),
            Beat(
                ask=("추가 조건도 있나요?", "그 외에 필요한 조건이 있을까요?", "더 말씀하실 게 있나요?"),
                tell=(
                    "강아지 두 마리가 있어서 반려동물 협의가 가능해야 하고 산책할 공원이 가까우면 좋겄어라.",
                    "강아지가 있어라. 협의되는 집이어야 하고요.",
                    "반려동물이 있어서 그것만 확인해 주쇼.",
                ),
                note="반려동물 협의 가능 여부는 매물별로 확인해야 하는 참고 조건임",
                tags=("pet_owner",),
            ),
            Beat(
                ask=("층과 향은 어떻게 보세요?", "선호 층이 있나요?", "향은 상관없으세요?"),
                tell=(
                    f"층은 {v['floor_min']} 이상을 원하고 {v['direction']}을 선호하지만 채광이 좋으면 "
                    "동향도 괜찮아라.",
                    f"{v['floor_min']} 이상이면 좋겄어요.",
                    "너무 낮은 층만 아니면 됩니다.",
                ),
                note="선호 층과 향은 참고 조건이며 확정 필드로 두지 않음",
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주시겠어요?", "번호 알려주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{j(v['phone'], '이여라', '여라')}.", f"{v['phone']}으로 주쇼.", f"번호는 {v['phone']}입니다."),
                fields={"전화번호": v["phone"]},
            ),
        ],
        closings={
            "high": (
                "네, 조건에 맞는 집이 있으면 이번 주말부터 보고 싶어라.",
                "빨리 정하고 싶어라. 나오면 바로 연락 주쇼.",
                "주말에 바로 보러 가겄습니다.",
            ),
            "mid": (
                "네, 조건을 정리해서 등록하고 연락드리겠습니다.",
                "구입장에 남겨두겠습니다.",
                "네, 접수하겠습니다.",
            ),
            "low": (
                "일단 어떤 게 있는지만 보고 싶어라.",
                "아직 확정은 아니라서 자료만 주쇼.",
                "천천히 봐도 되야요.",
            ),
        },
        tags=("dialect_jeolla", "pet_owner", "many_corrections"),
    )


def bp_other_cobroker_pro(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-cobroker-pro",
        label="기타상담",
        persona="공동중개를 제안하는 상대 중개사",
        openings=greet(v),
        identity=(
            f"안녕하세요. {v['brokerage2']}입니다.",
            f"네, {v['brokerage2']}에서 연락드렸습니다.",
            f"{v['brokerage2']}입니다. 매물 하나 여쭤보려고요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(
                    f"{v['complex']} {v['building']} {v['unit']} 매물 아직 진행하시나요?",
                    f"{v['complex']} {v['building']} {v['unit']} 아직 살아 있나요?",
                    f"{v['complex']} {v['unit']} 매물 상태 좀 확인하려고요.",
                ),
                ack=("네, 현재 매도 가능 상태입니다.", "네 아직 진행 중입니다.", "네, 살아 있습니다."),
            ),
            Beat(
                ask=("어떤 손님이신가요?", "찾으시는 조건이 있나요?", "손님 조건을 알려주세요."),
                tell=(
                    f"저희 쪽에 {v['area']} 아파트를 찾는 손님이 있습니다. 매매가 {v['price']}으로 확인하면 될까요?",
                    f"{v['area']} 찾는 손님이 있어서요. 가격이 {v['price']} 맞습니까?",
                    f"{v['area']} 매수 손님입니다. 표시가가 {v['price']}이던데요.",
                ),
                ack=(
                    f"네, 소유자 희망가는 {v['price']}이고 가격 협의 범위는 별도로 확인해야 합니다.",
                    f"네 {v['price']} 맞습니다. 조정 여지는 소유자 확인이 필요합니다.",
                    f"{v['price']} 맞고요, 협의는 따로 여쭤봐야 합니다.",
                ),
            ),
            Beat(
                ask=("입주 조건도 확인하시겠어요?", "명도 조건은 확인하셨나요?", "입주 가능일 확인이 필요하실까요?"),
                tell=(
                    f"현재 소유자가 거주 중이고 {v['move']} 이후 입주 가능한 매물 맞죠?",
                    f"{v['move']} 이후 입주 가능하다고 들었는데 맞나요?",
                    "명도 조건이 어떻게 되는지 확인 부탁드립니다.",
                ),
                ack=("맞습니다. 정확한 잔금일은 협의할 수 있습니다.", "네 맞습니다. 잔금일은 조율 가능합니다.",
                     "네, 그렇게 확인하시면 됩니다."),
            ),
            Beat(
                ask=("방문 일정을 잡을까요?", "언제 보러 오시겠어요?", "일정 조율이 필요하실까요?"),
                tell=(
                    "이번 주 토요일 오전 11시에 방문할 수 있을까요?",
                    "주말 오전에 한 번 보고 싶습니다.",
                    "이번 주 안에 내부를 볼 수 있을까요?",
                ),
                ack=("소유자에게 확인한 뒤 회신드리겠습니다.", "소유자 일정 확인하고 연락드리겠습니다.",
                     "확인해서 알려드리겠습니다."),
                note="방문 일정은 소유자 확인 후 회신하기로 해 확정되지 않음",
            ),
            Beat(
                ask=("손님의 자금계획은 확인하셨나요?", "매수인 자금은 어떻게 되나요?", "자금 계획 확인 부탁드립니다."),
                tell=(
                    f"현금과 대출을 합쳐 {v['budget']}까지 가능하고 기존 주택 처분 조건은 없습니다.",
                    f"{v['budget']}까지 가능하고 조건부는 아닙니다.",
                    f"자금은 {v['budget']}까지 확인했습니다.",
                ),
                optional=True,
            ),
            Beat(
                ask=("공동중개 방식은 어떻게 할까요?", "수수료 배분은 통상 기준으로 할까요?",
                     "진행 방식을 정해두겠습니다."),
                tell=(
                    "네, 매수 측은 저희가 담당하고 매도 측은 그쪽에서 담당하는 것으로 진행하겠습니다.",
                    "통상적인 기준으로 하시죠.",
                    "네, 각자 측 손님을 담당하는 걸로 하겠습니다.",
                ),
                note="공동중개 수수료 배분은 통상 기준으로 협의했고 계약 전 재확인이 필요함",
                optional=True,
            ),
        ],
        closings={
            "high": (
                "소유자에게 방문 가능 여부를 확인해서 바로 연락드리겠습니다.",
                "오늘 중으로 회신드리겠습니다.",
                "확인하는 대로 바로 알려드리겠습니다.",
            ),
            "mid": (
                "네, 확인 후 연락드리겠습니다. 오늘 내용은 상담 로그로 남기겠습니다.",
                "네, 상담 기록만 남기고 회신드리겠습니다.",
                "확인해서 알려드리겠습니다. 장부 등록 건은 아니라 기록만 하겠습니다.",
            ),
            "low": (
                "우선 조건만 확인한 거고 손님 의사는 다시 확인해 보겠습니다.",
                "아직 확정된 건 아니라 참고만 부탁드립니다.",
                "손님이 결정하면 다시 연락드리겠습니다.",
            ),
        },
        tags=("co_brokerage", "broker_to_broker", "no_field_proposal"),
    )


def bp_other_cobroker_assistant(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-cobroker-assistant",
        label="기타상담",
        persona="자격 확인이 필요한 중개보조원",
        openings=greet(v),
        identity=(
            f"저기유, {v['brokerage2']}인데유.",
            f"예, {v['brokerage2']}에서 전화드렸슈.",
            f"{v['brokerage2']}입니다. 매물 하나 여쭤볼게유.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(
                    f"{v['complex']} {v['building']} {v['unit']} 아직 안 나갔쥬?",
                    f"{v['complex']} {v['unit']} 그거 아직 있쥬?",
                    f"{v['complex']} 매물 아직 진행하시나유?",
                ),
                ack=("현재 매도 진행 중입니다. 공동중개 문의이신가요?", "네 진행 중입니다.",
                     "네, 아직 살아 있습니다."),
            ),
            Beat(
                ask=("어떤 조건을 찾는 손님인가요?", "손님 조건 알려주시겠어요?", "어떤 손님이신가요?"),
                tell=(
                    "예, 손님이 하나 있긴 한디 아직 확실한 건 아니에유. 세입자 있는 구축 아파트를 투자용으로 본대유.",
                    "투자용으로 보는 손님이유. 아직 확실친 않구유.",
                    "구축 투자 손님인데 아직 확정은 아니에유.",
                ),
                note="상대 중개사의 손님 매수 의사가 확정되지 않음",
            ),
            Beat(
                ask=("가격 조건은 확인하셨나요?", "표시가는 보셨어요?", "매매가 확인 필요하실까요?"),
                tell=(
                    f"매매가가 {v['price']}이었나유?",
                    f"{v['price']} 맞쥬?",
                    f"가격이 {v['price']}으로 나와 있던데유.",
                ),
                ack=(
                    f"네, 현재 표시 가격은 {v['price']}이고 소유자가 빠른 거래를 원해서 협의 가능성이 있습니다.",
                    f"네 {v['price']} 맞습니다.",
                    f"{v['price']}이고 조정 여지는 확인이 필요합니다.",
                ),
            ),
            Beat(
                ask=("임대 조건도 확인하시겠어요?", "월세 조건 확인이 필요하신가요?", "세입자 조건도 알려드릴까요?"),
                tell=(
                    f"월세가 보증금 {v['wolse_deposit']}에 {v['wolse_rent']} 맞쥬?",
                    f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}이라고 봤는데유.",
                    "세입자 조건 좀 알려주세유.",
                ),
                ack=(f"네, 계약 만기는 {v['due_next']}입니다.", f"맞습니다. 만기는 {v['due_next']}이고요.",
                     "네 그렇게 확인하시면 됩니다."),
                optional=True,
            ),
            Beat(
                ask=("내부 확인은 언제 원하세요?", "방문 일정을 잡을까요?", "언제 보시겠어요?"),
                tell=(
                    "이번 주에 내부를 볼 수 있을까유? 사진이라도 먼저 보내달라 하네유.",
                    "이번 주에 볼 수 있으면 좋겄는디유.",
                    "사진부터 좀 보내주실 수 있나유?",
                ),
                ack=("세입자와 일정을 먼저 조율해야 합니다.", "임차인 동의가 필요해서 확인 후 알려드리겠습니다.",
                     "세입자 일정 확인이 필요합니다."),
                note="내부 방문은 임차인 일정 조율이 필요해 확정되지 않음",
            ),
            Beat(
                ask=("담당 공인중개사 성함과 사무소 등록정보를 알려주시겠어요?",
                     "대표 공인중개사분과 통화할 수 있을까요?", "등록정보 확인이 필요합니다."),
                tell=(
                    "아, 저는 중개보조원이고 대표님은 지금 외근 중이에유.",
                    "제가 보조원이라서유. 대표님은 나가 계셔유.",
                    "대표님이 자리에 안 계셔유.",
                ),
                ack=(
                    "공동중개는 대표 공인중개사 확인 후 진행하겠습니다. 대표님께서 직접 연락주시거나 "
                    "사무소 정보를 보내주세요.",
                    "대표 공인중개사 확인 후에 진행하겠습니다.",
                    "등록정보 확인 전에는 진행이 어렵습니다.",
                ),
                note="상대가 중개보조원이라 대표 공인중개사 확인 전에는 공동중개를 진행할 수 없음",
                tags=("verification_required",),
            ),
        ],
        closings={
            "high": (
                "알겠어유. 대표님한테 바로 연락드리라 하겄슈.",
                "지금 바로 대표님께 전달하겄슈.",
                "오늘 중으로 다시 전화드릴게유.",
            ),
            "mid": (
                "알겠어유. 손님 대출 가능 금액도 확인해서 다시 전화드릴게유.",
                "확인해서 다시 연락드리겄슈.",
                "네, 알아보고 연락드릴게유.",
            ),
            "low": (
                "손님이 아직 확실치 않아서 나중에 다시 연락드릴게유.",
                "일단 물어만 본 거예유.",
                "확정되면 다시 전화드리겄슈.",
            ),
        },
        tags=("co_brokerage", "broker_to_broker", "dialect_chungcheong", "no_field_proposal"),
    )


def bp_other_simple_fee(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-simple-fee",
        label="기타상담",
        persona="관리비와 규정을 묻는 단순 문의자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 그냥 좀 궁금해서 여쭤보는 거예요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 계약할 건 아니고 문의만 드리려고요.",
            f"제 이름은 {j(v['name'], '이에요', '예요')}. 알아만 보는 중이에요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(
                    f"인터넷에 올라온 {v['complex']} 있잖아요. 관리비가 얼마예요?",
                    f"{v['complex']} 매물 보고 전화드렸는데 관리비가 궁금해서요.",
                    f"{v['complex']} 관리비 좀 여쭤보려고요.",
                ),
                ack=("어떤 동이나 매물번호를 보셨을까요?", "매물번호를 알 수 있을까요?",
                     "어느 매물인지 알 수 있을까요?"),
            ),
            Beat(
                tell=(
                    f"그건 잘 모르겠고 매매가 {v['price']}으로 올라온 {v['area']} 아파트요.",
                    f"번호는 모르겠고 {v['area']}짜리요.",
                    f"{v['price']}에 나온 거요.",
                ),
                ack=(
                    f"해당 매물의 관리비는 월평균 {v['fee']} 정도이며 계절과 사용량에 따라 달라질 수 있습니다.",
                    f"관리비는 월 {v['fee']} 안팎입니다.",
                    f"평균 {v['fee']} 정도로 보시면 됩니다.",
                ),
                note="고객이 조회용으로 말한 매물 정보는 접수 의사가 없어 필드로 제안하지 않음",
            ),
            Beat(
                ask=("더 궁금하신 게 있을까요?", "다른 것도 확인해 드릴까요?", "추가로 여쭤보실 게 있나요?"),
                tell=("주차는 무료예요?", "주차비는 따로 있나요?", "주차 등록은 어떻게 되나요?"),
                ack=(
                    "세대당 차량 한 대는 기본 등록이 가능하고 두 번째 차량부터 추가 비용이 발생합니다.",
                    "한 대는 무료이고 두 번째부터는 비용이 붙습니다.",
                    "세대당 한 대 기준입니다.",
                ),
            ),
            Beat(
                tell=("반려동물을 키워도 되나요?", "강아지 키워도 괜찮나요?", "반려동물 규정이 있나요?"),
                ack=(
                    "반려동물 자체가 금지된 단지는 아니지만 소음이나 공용공간 이용 규정은 지켜야 합니다.",
                    "금지는 아니지만 규정은 지키셔야 합니다.",
                    "단지 규정 범위 안에서는 가능합니다.",
                ),
                optional=True,
            ),
            Beat(
                tell=(
                    "아, 그냥 궁금해서 물어본 거예요. 아직 이사하거나 매수할 계획은 없습니다.",
                    "지금 당장 뭘 하려는 건 아니에요.",
                    "계약 생각은 아직 없어요.",
                ),
                note="고객이 매수·이사 계획이 없다고 밝혀 접수 대상이 아님",
            ),
        ],
        closings={
            "high": ("나중에 정하면 그때 다시 연락드릴게요.", "혹시 좋은 매물 나오면 알려주세요.",
                     "다음에 진지하게 볼 때 연락드리겠습니다."),
            "mid": ("네, 필요하실 때 다시 문의해주세요.", "네, 궁금하신 거 있으면 또 연락 주세요.",
                    "네, 상담 내용만 기록해 두겠습니다."),
            "low": ("네, 그냥 알아본 거예요. 감사합니다.", "네 알겠습니다. 수고하세요.",
                    "확인만 하려던 거였어요. 감사합니다."),
        },
        tags=("simple_inquiry", "no_field_proposal", "hypothetical_value_not_fact"),
    )


def bp_other_jeonse_loan(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-jeonse-loan",
        label="기타상담",
        persona="전세대출 절차를 묻는 첫 계약자",
        openings=greet(v, *GREET_PLAIN),
        identity=(
            f"아 제 이름은 {j(v['name'], '입니다', '입니다')}.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 아직 아무것도 정한 게 없어요.",
            f"제 이름은 {j(v['name'], '이에요', '예요')}.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(
                    "제가 처음으로 아파트 전세계약을 하려고 하는데 전세대출 관련해서 물어봐도 될까요?",
                    "전세대출이 어떻게 되는지 몰라서 여쭤보려고요.",
                    "대출 절차를 잘 몰라서 전화드렸습니다.",
                ),
                ack=("네, 현재 보고 계신 아파트가 있나요?", "네, 어떤 부분이 궁금하세요?",
                     "네, 편하게 말씀하세요."),
            ),
            Beat(
                tell=(
                    f"아직 없습니다. {v['region']} 쪽으로 이사하려고 하는데 대출이 얼마나 나오는지부터 "
                    "알고 싶어서요.",
                    f"아직 집은 안 정했어요. {v['region']} 근처에서 볼 생각이고 한도부터 알고 싶어서요.",
                    f"{v['region']} 쪽으로 볼 생각인데 아직 정한 건 없습니다.",
                ),
                ack=(
                    "대출 한도는 소득, 재직 상태, 보증기관과 주택 조건에 따라 달라집니다.",
                    "한도는 개인 조건과 주택 조건에 따라 달라집니다.",
                    "조건이 여러 가지라 일률적으로 말씀드리기 어렵습니다.",
                ),
                note="희망 주택이 정해지지 않아 접수할 조건이 없음",
            ),
            Beat(
                tell=(
                    "중개사무소에서 대출 승인 여부를 바로 확인해주시는 건가요?",
                    "여기서 대출이 되는지 알 수 있나요?",
                    "승인 여부를 미리 알 수 있을까요?",
                ),
                ack=(
                    "저희가 승인할 수는 없습니다. 은행이나 보증기관의 심사가 필요하고 아파트를 정한 뒤 "
                    "해당 주택이 보증 대상인지도 확인해야 합니다.",
                    "저희는 승인 권한이 없고 은행 심사가 필요합니다.",
                    "그건 금융기관 심사 사항입니다.",
                ),
                note="대출 승인 여부는 금융기관 심사 사항이라 중개사무소가 확정할 수 없음",
            ),
            Beat(
                tell=(
                    f"보증금이 {v['jeonse']} 정도 되는 집을 보려고 하는데 그러면 미리 준비할 서류가 있을까요?",
                    f"{v['jeonse']} 정도로 생각하고 있는데 무엇부터 하면 될까요?",
                    f"{v['jeonse']} 정도 집을 볼 건데 준비할 게 있나요?",
                ),
                note="희망 보증금을 언급했지만 대상 주택이 없어 접수 조건으로 두지 않음",
                ack=(
                    "기본적으로 신분증과 재직 및 소득 관련 서류가 필요할 수 있지만 상품마다 다릅니다.",
                    "상품마다 달라서 은행 상담을 먼저 받아보시는 게 좋습니다.",
                    "신분증과 소득 관련 서류가 기본입니다.",
                ),
                optional=True,
            ),
            Beat(
                tell=(
                    "전세사기가 걱정되는데 등기부등본도 봐주시나요?",
                    "권리관계도 확인해 주시나요?",
                    "안전한 집인지 확인이 되나요?",
                ),
                ack=(
                    "실제 계약을 검토할 때 소유자와 권리관계, 선순위 채권 등을 확인해드릴 수 있습니다. "
                    "다만 현재는 특정 아파트가 정해지지 않아서 일반적인 절차만 안내드릴 수 있습니다.",
                    "계약 검토 단계에서 권리관계를 확인해드립니다.",
                    "매물이 정해지면 등기부를 함께 확인합니다.",
                ),
            ),
        ],
        closings={
            "high": ("은행 상담 먼저 받고 이번 주에 다시 연락드리겠습니다.",
                     "한도 나오면 바로 집 보러 오겠습니다.",
                     "빠르게 준비해서 다시 연락드릴게요."),
            "mid": ("네, 알겠습니다. 은행 상담부터 받고 나중에 다시 연락드리겠습니다.",
                    "네, 절차만 알아두고 다시 연락드릴게요.",
                    "네, 상담 내용만 기록해 두겠습니다."),
            "low": ("아직 집도 안 정해서 그냥 물어본 거예요.",
                    "당장은 아니고 미리 알아두려던 거예요.",
                    "네, 참고만 하겠습니다."),
        },
        tags=("loan_consultation", "no_field_proposal"),
    )


def bp_other_lost_contract(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-lost-contract",
        label="기타상담",
        persona="계약서를 분실한 기존 임차인",
        openings=greet(v),
        identity=(
            f"안녕하세요. 작년에 여기서 {v['complex']} 전세계약한 {j(v['name'], '인데요', 'ㄴ데요')}.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 작년에 여기서 {v['complex']} 계약했었어요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 여기서 전세계약을 했던 사람이에요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(
                    "계약서를 잃어버린 것 같아서요.",
                    "이사하면서 계약서가 없어졌어요.",
                    "계약서를 못 찾겠어서 전화드렸어요.",
                ),
                ack=("계약한 동과 호수를 말씀해주시겠어요?", "본인 확인이 필요합니다. 동호수를 알려주세요.",
                     "계약 정보를 확인해 볼게요."),
            ),
            Beat(
                tell=(
                    f"{v['building']} {j(v['unit'], '이고', '고')} 전화번호 뒷자리는 {v['phone_tail']}입니다.",
                    f"{v['building']} {j(v['unit'], '이에요', '예요')}. 뒷번호는 {v['phone_tail']}이고요.",
                    f"{v['building']} {v['unit']}입니다.",
                ),
                ack=(
                    "본인 확인 후 보관된 계약서 사본이 있는지 확인해보겠습니다.",
                    "확인해서 사본이 있는지 보겠습니다.",
                    "네, 보관 자료를 찾아보겠습니다.",
                ),
            ),
            Beat(
                tell=(
                    "사본을 받으면 확정일자를 다시 받아야 하나요?",
                    "확정일자는 어떻게 되나요?",
                    "효력에 문제가 생기는 건 아닌가요?",
                ),
                ack=(
                    "이미 확정일자를 받으셨다면 계약서를 분실했다고 해서 효력이 바로 없어지는 것은 아닙니다. "
                    "정확한 내용은 주민센터나 인터넷등기소를 통해 확인하는 것이 좋습니다.",
                    "분실만으로 효력이 사라지지는 않습니다. 다만 기관 확인이 정확합니다.",
                    "그 부분은 주민센터 확인이 필요합니다.",
                ),
                note="확정일자 효력은 주민센터·인터넷등기소 확인이 필요한 사항임",
            ),
            Beat(
                tell=(
                    "제가 확정일자를 받았는지도 기억이 안 나요.",
                    "그때 받았는지 잘 모르겠어요.",
                    "기억이 안 나서요.",
                ),
                ack=("당시 계약서에 확정일자 표시가 있는지 사본을 확인해보겠습니다.",
                     "사본에서 확인해 보겠습니다.", "자료를 보고 말씀드리겠습니다."),
                optional=True,
            ),
            Beat(
                tell=(
                    "오늘 중으로 계약서 사본을 받을 수 있을까요? 은행에 제출해야 해서요.",
                    "급해서 오늘 받을 수 있으면 좋겠어요.",
                    "언제쯤 받을 수 있을까요?",
                ),
                ack=(
                    "본인 확인과 자료 확인이 끝나면 연락드리겠습니다. 개인정보가 포함되어 있어 가족이나 "
                    "다른 사람에게는 전달할 수 없습니다.",
                    "본인 확인 후에만 전달 가능합니다.",
                    "확인되는 대로 연락드리겠습니다.",
                ),
                note="계약서 사본은 본인 확인 후에만 전달할 수 있어 즉시 제공이 확정되지 않음",
                tags=("identity_verification",),
            ),
        ],
        closings={
            "high": ("네, 제가 신분증을 가지고 직접 방문하겠습니다.",
                     "지금 바로 가겠습니다.",
                     "오늘 안에 들르겠습니다."),
            "mid": ("네, 확인되면 연락 주세요.", "네, 기다리겠습니다.",
                    "네, 상담 기록만 남겨주시면 됩니다."),
            "low": ("급한 건 아니니까 확인되면 알려주세요.",
                    "천천히 찾아봐 주셔도 됩니다.",
                    "네, 나중에 다시 연락드릴게요."),
        },
        tags=("existing_contract", "no_field_proposal"),
    )


def bp_other_tenant_repair(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-tenant-repair",
        label="기타상담",
        persona="수리를 문의하는 임차인",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, {v['complex']} {v['building']} {v['unit']}에 "
            "세 들어 사는 사람이에요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} 임차인이에요.",
            f"제 이름은 {j(v['name'], '이에요', '예요')}. {v['complex']} {v['unit']}에 살고 있어요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(
                    "어… 보일러가 안 돌아가서요. 어제부터 온수가 안 나와요.",
                    "안방 천장에서 물이 새요. 얼룩이 번지고 있어서요.",
                    "난방이 안 돼서 전화드렸어요.",
                ),
                ack=("아 그러셨군요. 그건 임대인분께 먼저 알리셔야 하는 사안이라서요.",
                     "네, 수리 건은 임대인분과 협의가 필요한 부분입니다.",
                     "네 확인했습니다. 수리는 임대인분 결정 사항이에요."),
            ),
            Beat(
                tell=(
                    "그게 집주인분한테 전화를 몇 번 했는데 안 받으셔서요. 그래서 여기로 걸었어요.",
                    "임대인분이 연락이 안 되세요.",
                    "문자도 남겼는데 답이 없어서요.",
                ),
                ack=(
                    "네, 그럼 제가 임대인분께 연락을 한번 넣어보겠습니다. 다만 수리 여부는 그쪽에서 정하십니다.",
                    "제가 대신 연락을 시도해 보겠습니다.",
                    "임대인분께 전달은 해드리겠습니다.",
                ),
                note="임대인 연락 시도는 중개사가 하기로 했고 수리 결정은 임대인 몫이라 확정된 내용 없음",
            ),
            Beat(
                tell=(
                    f"저희 계약이 {v['expire']}에 끝나는데 이런 건 누가 고쳐야 되는 거예요?",
                    "수리비는 누가 부담하나요?",
                    "이건 세입자가 내는 건가요?",
                ),
                ack=(
                    "그건 계약서 특약과 고장 원인에 따라 달라져서 계약서를 보고 판단해야 합니다.",
                    "노후로 인한 건지 사용 과실인지에 따라 달라집니다.",
                    "계약서 특약을 먼저 확인해 봐야 알 수 있습니다.",
                ),
                note="수리비 부담 주체는 계약서 특약과 고장 원인 확인 후 판단해야 함",
            ),
            Beat(
                tell=(
                    "당장 온수가 안 나와서 오늘 안에 연락이 됐으면 좋겠어요.",
                    "빨리 처리됐으면 합니다.",
                    "언제쯤 답을 받을 수 있을까요?",
                ),
                ack=("연락이 닿는 대로 바로 알려드리겠습니다.", "확인해서 회신드리겠습니다.",
                     "최대한 빨리 전달하겠습니다."),
                optional=True,
            ),
        ],
        closings={
            "high": ("오늘 안에 꼭 좀 연락 부탁드립니다.", "급해서요. 빨리 부탁드려요.",
                     "바로 좀 알아봐 주세요."),
            "mid": ("네, 오늘은 수리 문의로만 상담 로그를 남기고 장부에는 올리지 않겠습니다.",
                    "네, 접수 건이 아니라 상담 기록만 남기겠습니다.",
                    "네, 확인해서 연락드리겠습니다."),
            "low": ("급한 건 아니니까 통화되시면 전달만 해주세요.",
                    "천천히 확인해 주셔도 됩니다.",
                    "네, 알겠습니다. 기다릴게요."),
        },
        tags=("tenant_caller", "no_field_proposal"),
    )


def bp_sell_redevelopment(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-redevelopment",
        label="매도의뢰",
        persona="재건축 예정 단지 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} {v['complex']} {v['building']} {v['unit']} 매도 문의드립니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 건인데요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하고요, {v['complex']} {v['building']} {v['unit']} 소유자입니다.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                ask=("평형이 어떻게 되나요?", "몇 평이세요?", "평형과 향 알려주세요."),
                tell=(f"{v['area']}이고 {v['direction']}입니다.", f"{v['area']}이에요. 향은 {v['direction']}이고요.",
                      f"{v['area']}, {v['direction']}입니다."),
                fields={"평형": v["area"], "방향": v["direction"]},
            ),
            Beat(
                ask=("희망가는 얼마로 보세요?", "가격은 어느 선인가요?", "매매가를 알려주세요."),
                tell=(f"{v['price']}이요. 재건축 기대가 있어서 그 정도는 봐야 할 것 같아요.",
                      f"{v['price']}으로 생각합니다.", f"{v['price']} 정도요."),
                fields={"매매가": v["price"]},
            ),
            Beat(
                ask=("재건축은 어디까지 진행됐나요?", "조합 설립은 됐나요?", "사업 단계가 어떻게 되나요?"),
                tell=("조합 설립까지는 됐고 그 뒤로는 아직이에요.",
                      "안전진단은 통과했다고 들었어요.", "정확한 단계는 저도 잘 몰라요."),
                note="재건축 진행 단계는 고객 설명만으로 확인되지 않아 조합·구청 확인이 필요함",
                tags=("redevelopment",),
            ),
            Beat(
                ask=("조합원 지위 전매 제한은 확인하셨어요?", "전매 제한 여부는 아세요?",
                     "지위 승계가 가능한 물건인가요?"),
                tell=("그게 된다는 말도 있고 안 된다는 말도 있어서 확인이 필요해요.",
                      "저도 그 부분이 궁금해서 여쭤보려고 했어요.", "아직 알아보지 못했습니다."),
                note="조합원 지위 전매 제한 여부가 확인되지 않아 거래 가능성 자체를 단정할 수 없음",
            ),
            Beat(
                ask=("현재 거주 상태는요?", "지금 누가 사시나요?", "공실인가요?"),
                tell=("전세 세입자가 있어요.", "저희가 살고 있습니다.", "지금은 비어 있어요."),
                fields={"현상태": "고객 진술 기준"},
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주시겠어요?", "번호 알려주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.", f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"임대인 전화": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("전매만 된다면 바로 진행하고 싶습니다.", "가능하면 이번 달 안에 정리하고 싶어요.",
                     "확인되는 대로 바로 알려주세요."),
            "mid": ("네, 전매 제한 여부부터 확인하고 연락드리겠습니다.",
                    "조합 쪽 확인 후에 접수 여부를 정하겠습니다.",
                    "네, 확인해서 안내드리겠습니다."),
            "low": ("일단 알아만 보는 거라 등록은 하지 말아주세요.",
                    "확인만 부탁드리고 결정은 나중에 할게요.", "급하진 않습니다."),
        },
        tags=("redevelopment", "uncertain_eligibility"),
    )


def bp_sell_swap(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-swap",
        label="매도의뢰",
        persona="갈아타기로 잔금일을 맞춰야 하는 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, {v['complex']} {v['building']} {v['unit']} 팔고 "
            "다른 데로 옮기려고요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 매도하고 "
            "이사하려고 합니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, {v['complex']} {v['building']} {v['unit']} "
            "내놓으려고 전화드렸어요.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                ask=("평형이랑 타입은요?", "몇 평이세요?", "평형 알려주시겠어요?"),
                tell=(f"{v['area']}이고 {v['type']} 타입입니다.",
                      f"{v['area']}이에요. {v['type']}이고 {v['direction']}이고요.",
                      f"{v['area']}, {v['type']} 타입이에요."),
                fields={"평형": v["area"], "타입": v["type"]},
            ),
            Beat(
                ask=("희망 매매가는요?", "가격은 얼마로 보세요?", "얼마에 내놓을까요?"),
                tell=(f"{v['price']}이요.", f"{v['price']}으로 해주세요.",
                      f"{v['price']} 생각하고 있습니다."),
                ack=(f"매매가 {v['price']}으로 적겠습니다.", f"네 {v['price']} 확인했습니다.",
                     f"{v['price']}이요. 기록하겠습니다."),
                fields={"매매가": v["price"]},
            ),
            Beat(
                ask=("이사 갈 집은 정하셨어요?", "옮기실 곳은 계약하셨나요?", "다음 집은 어떻게 되세요?"),
                tell=(f"{v['complex2']} 쪽으로 계약을 걸어놨어요. 잔금이 {v['move']}입니다.",
                      f"다음 집 잔금이 {v['move']}이라 그날에 맞춰야 해요.",
                      "아직 계약 전이에요. 이 집이 나가야 진행할 수 있습니다."),
                note="새 집 잔금 일정에 맞춰야 해서 잔금일 조정 여지가 좁음",
                tags=("swap_deal",),
            ),
            Beat(
                ask=("그럼 명도 조건은 어떻게 잡을까요?", "잔금일은 언제로 볼까요?",
                     "입주 가능일은요?"),
                tell=(f"잔금일을 {v['move']}에 맞춰주시면 그날 비워드릴 수 있어요.",
                      f"{v['move']} 잔금이면 바로 명도 가능합니다.",
                      "그건 매수인 사정에 맞춰볼 수 있어요."),
                fields={"명도 조건": f"{v['move']} 잔금 시 명도"},
            ),
            Beat(
                ask=("융자는 얼마나 있으세요?", "대출은요?", "근저당 확인 좀 할게요."),
                tell=(f"{v['loan_left']} 남았고 잔금으로 정리할 겁니다.",
                      f"대출은 {v['loan_left']}입니다.", "대출은 없습니다."),
                fields={"융자": "고객 진술 기준"},
                optional=True,
            ),
            Beat(
                ask=("연락처 알려주세요.", "번호 남겨주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 부탁드려요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"임대인 전화": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": (f"{v['move']} 잔금이라 시간이 없어요. 빨리 부탁드립니다.",
                     "일정이 촉박해서 최대한 서둘러 주세요.", "이번 주라도 보여드릴 수 있습니다."),
            "mid": ("네, 일정 맞는 매수인 위주로 찾아보겠습니다.",
                    "잔금일 조건까지 넣어서 접수하겠습니다.", "네, 등록해 두겠습니다."),
            "low": ("다음 집 계약이 확정되면 다시 연락드릴게요.",
                    "아직 확정 전이라 등록은 보류해 주세요.", "일정부터 정리하고 다시 연락드리겠습니다."),
        },
        tags=("swap_deal", "tight_schedule"),
    )


def bp_sell_presale_right(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-presale-right",
        label="매도의뢰",
        persona="분양권을 전매하려는 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} {v['complex']} 분양권을 넘기려고 합니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} 분양권 전매 문의드려요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, {v['complex']} 분양받은 걸 팔려고요.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"]},
        beats=[
            Beat(
                ask=("동호수는 나왔나요?", "몇 동 몇 호로 당첨되셨어요?", "호수 배정은 됐나요?"),
                tell=(f"{v['building']} {v['unit']}입니다.", f"{v['building']} {v['unit']}로 나왔어요.",
                      f"{v['building']} {v['unit']}이요."),
                fields={"동": v["building"], "호": v["unit"]},
            ),
            Beat(
                ask=("평형은요?", "몇 평형 분양받으셨어요?", "타입이 어떻게 되나요?"),
                tell=(f"{v['area']}이고 {v['type']} 타입이에요.", f"{v['area']}에 {v['type']} 타입입니다.",
                      f"{v['area']}, {v['type']}입니다."),
                fields={"평형": v["area"], "타입": v["type"]},
            ),
            Beat(
                ask=("얼마에 넘기고 싶으세요?", "희망 금액은요?", "프리미엄은 얼마로 보세요?"),
                tell=(f"분양가에 프리미엄 붙여서 {v['price']} 정도로 보고 있어요.",
                      f"{v['price']}이요.", f"{v['price']}이면 넘기겠습니다."),
                fields={"매매가": v["price"]},
                note="분양가와 프리미엄 구분이 명확하지 않아 금액 구성 확인이 필요함",
            ),
            Beat(
                ask=("전매 제한 기간은 지났나요?", "전매가 가능한 물건인가요?",
                     "계약일이 언제였어요?"),
                tell=("그게 이번 달에 풀린다고 들었는데 정확한 날짜는 확인해야 해요.",
                      "풀린 걸로 알고 있어요.", "그건 저도 확인이 필요합니다."),
                note="전매 제한 해제 시점이 확인되지 않아 거래 가능 시점을 단정할 수 없음",
                tags=("transfer_restriction",),
            ),
            Beat(
                ask=("중도금 대출은 실행됐나요?", "납부는 어디까지 하셨어요?", "중도금은 어떻게 되나요?"),
                tell=("중도금 2회차까지 냈어요.", "중도금 대출로 진행 중입니다.",
                      "그건 서류를 봐야 정확히 알겠어요."),
                note="중도금 승계 조건은 시행사·은행 확인이 필요함",
                optional=True,
            ),
            Beat(
                ask=("연락처 알려주시겠어요?", "번호 좀 남겨주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"임대인 전화": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("전매 풀리면 바로 진행하고 싶습니다.", "빨리 넘기고 싶어요.",
                     "매수인 있으면 바로 연결해 주세요."),
            "mid": ("네, 전매 제한과 승계 조건부터 확인하고 안내드리겠습니다.",
                    "확인해서 접수 여부를 알려드리겠습니다.", "네, 알아보고 연락드리겠습니다."),
            "low": ("일단 알아만 보는 중이라 등록은 하지 말아주세요.",
                    "확인만 해주시면 나중에 다시 연락드릴게요.", "아직 결정은 안 했어요."),
        },
        tags=("presale_right", "transfer_restriction"),
    )


def bp_sell_tenant_conflict(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-tenant-conflict",
        label="매도의뢰",
        persona="임차인 명도가 걸린 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, {v['complex']} {v['building']} {v['unit']} "
            "집을 내놓으려는데 상황이 좀 복잡해요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 매도 건입니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 합니다. {v['complex']} {v['building']} {v['unit']} 소유자예요.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                ask=("현재 임차인이 있으신가요?", "지금 누가 살고 있나요?", "거주 상태를 알려주세요."),
                tell=(f"전세 세입자가 있고 보증금은 {v['sale_deposit']}, 만기는 {v['due_next']}입니다.",
                      f"세입자 거주 중이에요. {v['sale_deposit']}에 만기 {v['due_next']}입니다.",
                      f"임차인이 있습니다. 보증금 {v['sale_deposit']}이고 만기가 {v['due_next']}이에요."),
                fields={"현재 보증금": v["sale_deposit"], "만기일": v["due_next"], "현상태": "임차인 거주"},
            ),
            Beat(
                ask=("임차인분과 이야기는 되셨나요?", "세입자분은 뭐라고 하세요?",
                     "퇴거 협의는 어떻게 됐나요?"),
                tell=("계약갱신을 하겠다고 하셔서 지금 얘기가 잘 안 되고 있어요.",
                      "나가기 어렵다고 하셔서 난감합니다.",
                      "연락은 되는데 서로 입장이 달라요."),
                note="임차인이 계약 갱신을 요구하고 있어 명도 가능 여부가 확정되지 않음",
                tags=("handover_dispute",),
            ),
            Beat(
                ask=("성함과 연락처는 아시나요?", "임차인 정보도 남겨둘까요?",
                     "세입자분 연락처를 받을 수 있을까요?"),
                tell=(f"임차인은 {v['tenant']}이고 연락처는 제가 물어보고 알려드릴게요.",
                      f"{j(v['tenant'], '이에요', '예요')}. 번호는 나중에요.",
                      f"{v['tenant']}인데 지금 상황에서 번호를 드리기는 좀 그래요."),
                fields={"임차인": v["tenant"]},
                note="임차인 전화는 고객이 제공하지 않아 미확인",
            ),
            Beat(
                ask=("희망 매매가는 얼마인가요?", "가격은 어떻게 볼까요?", "얼마에 내놓을까요?"),
                tell=(f"{v['price']}이요. 명도가 어려우면 조금 낮출 수도 있어요.",
                      f"{v['price']}으로 하고 상황 봐서 조정할게요.", f"{v['price']}입니다."),
                fields={"매매가": v["price"]},
                note="명도 상황에 따라 가격 조정 여지를 언급했으나 확정 조정가는 아님",
            ),
            Beat(
                ask=("승계 조건으로도 보실 수 있나요?", "세입자 있는 채로 파는 것도 괜찮으세요?",
                     "투자자에게 넘기는 건 어떠세요?"),
                tell=("그것도 괜찮아요. 그게 더 빠르면 그렇게 할게요.",
                      "실거주 매수인이면 좋겠지만 어쩔 수 없죠.",
                      "그건 좀 더 생각해 볼게요."),
                optional=True,
            ),
            Beat(
                ask=("연락처 알려주세요.", "번호 남겨주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"임대인 전화": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("빨리 정리하고 싶어요. 조건 맞는 분 있으면 연결해 주세요.",
                     "명도만 되면 바로 진행합니다.", "서둘러 주시면 감사하겠습니다."),
            "mid": ("네, 명도 조건은 미정으로 두고 접수하겠습니다.",
                    "임차인 협의 결과를 보고 조건을 채우겠습니다.", "네, 그렇게 등록해 두겠습니다."),
            "low": ("세입자분과 얘기가 정리되면 다시 연락드릴게요.",
                    "지금은 상담만 남겨주세요.", "아직 내놓을 단계는 아닌 것 같아요."),
        },
        tags=("handover_dispute", "tenant_in_place"),
    )


def bp_sell_price_cut(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-price-cut",
        label="매도의뢰",
        persona="이미 접수한 매물의 가격을 내리려는 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 저번에 {v['complex']} {v['building']} {v['unit']} "
            "내놓은 사람인데요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 매물 건으로요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데 {v['complex']} {v['building']} {v['unit']} "
            "그거 지금 나와 있죠?",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                tell=("가격을 좀 내려야 할 것 같아서 전화드렸어요.",
                      "문의가 없어서 조정하려고요.", "가격을 낮춰서 다시 올려주세요."),
                ack=("네, 현재 등록된 조건을 확인하겠습니다.", "네, 어느 정도로 조정할까요?",
                     "네 말씀하세요."),
            ),
            Beat(
                ask=("얼마로 내릴까요?", "조정 금액을 말씀해 주세요.", "새 희망가는 얼마인가요?"),
                tell=(f"{v['price']}으로 낮춰주세요.", f"{v['price']}이요.",
                      f"{v['price']}으로 다시 올려주시면 됩니다."),
                ack=(f"네, 매매가를 {v['price']}으로 변경하겠습니다.",
                     f"{v['price']}으로 수정하겠습니다.", f"네 {v['price']} 확인했습니다."),
                fields={"매매가": v["price"]},
                tags=("price_revision",),
            ),
            Beat(
                ask=("더 조정 여지도 있으신가요?", "협의는 어느 정도까지 가능하세요?",
                     "네고 여지는 있을까요?"),
                tell=("일단 그 가격으로 올려주시고 협의는 사람 보고 할게요.",
                      "더는 어렵습니다.", "조금은 더 볼 수 있는데 지금 정하진 않을게요."),
                note="추가 조정 여지를 언급했지만 폭이 확정되지 않아 변경된 희망가만 유지",
            ),
            Beat(
                ask=("다른 조건은 그대로 둘까요?", "명도나 입주 조건은 변동 없으신가요?",
                     "나머지 내용은 동일한가요?"),
                tell=("네 나머지는 그대로예요.", "다른 건 변한 게 없습니다.",
                      "입주일만 조금 여유가 생겼어요."),
                fields={"진행상태": "가격 조정 요청"},
                optional=True,
            ),
            Beat(
                ask=("광고도 다시 올릴까요?", "노출은 어떻게 할까요?", "사진은 그대로 쓸까요?"),
                tell=("네 그대로 올려주세요.", "사진은 그대로 두셔도 됩니다.",
                      "이번엔 좀 더 눈에 띄게 해주세요."),
                optional=True,
                stage=2,
            ),
        ],
        closings={
            "high": ("이번엔 좀 빨리 나갔으면 좋겠어요.", "가격 내렸으니 연락 오면 바로 알려주세요.",
                     "적극적으로 좀 부탁드립니다."),
            "mid": ("네, 조정된 가격으로 반영하겠습니다.", "변경해서 다시 안내드리겠습니다.",
                    "네, 수정해 두겠습니다."),
            "low": ("일단 그렇게만 해두고 지켜볼게요.", "급한 건 아니에요.",
                    "반응 보고 다시 얘기하죠."),
        },
        tags=("price_revision", "existing_listing"),
    )


def bp_sell_hold(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-hold",
        label="매도의뢰",
        persona="접수한 매물을 잠시 내리려는 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, {v['complex']} {v['building']} {v['unit']} "
            "매물 내놓은 사람이에요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 건입니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, {v['complex']} {v['building']} {v['unit']} "
            "그 매물이요.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                tell=("그거 잠깐 내려주실 수 있을까요?", "일단 광고를 좀 내려주세요.",
                      "매물을 잠시 보류하고 싶어요."),
                ack=("네, 사유를 여쭤봐도 될까요?", "네, 보류로 변경하겠습니다.",
                     "네, 어떤 이유이신지 알 수 있을까요?"),
                fields={"현매물": "보류 요청"},
                tags=("listing_hold",),
            ),
            Beat(
                tell=("가족들이랑 얘기가 좀 안 끝나서요.", "세금 문제를 좀 알아보려고요.",
                      "이사 계획이 바뀔 수도 있어서요."),
                note="보류 사유가 확정 사항이 아니라 재개 시점을 정할 수 없음",
            ),
            Beat(
                ask=("언제쯤 다시 진행하실까요?", "재개 시점은 정하셨나요?",
                     "얼마나 보류할까요?"),
                tell=("그건 아직 모르겠어요. 정리되면 연락드릴게요.",
                      "한 달 정도만 내려주세요.", "일단 무기한으로 부탁드려요."),
                note="매물 재개 시점이 미정",
            ),
            Beat(
                ask=("가격은 그대로 둘까요?", "다시 올릴 때 조건은 동일한가요?",
                     "조건 변경도 있으신가요?"),
                tell=(f"네 {v['price']} 그대로요.", "다시 올릴 때 얘기할게요.",
                      "가격은 그때 다시 정할게요."),
                optional=True,
            ),
            Beat(
                ask=("문의 오면 어떻게 안내할까요?", "연락은 계속 드려도 될까요?",
                     "그동안 문의는 어떻게 처리할까요?"),
                tell=("정말 괜찮은 분 있으면 연락 주세요.", "당분간은 연락 안 주셔도 됩니다.",
                      "문자로만 남겨주세요."),
                optional=True,
                stage=3,
            ),
        ],
        closings={
            "high": ("정리되는 대로 바로 다시 올리겠습니다.", "빠르면 다음 주에 다시 연락드릴게요.",
                     "곧 다시 진행할 것 같아요."),
            "mid": ("네, 보류로 변경하고 상담 로그에 남기겠습니다.",
                    "네, 노출만 내려두겠습니다.", "네, 그렇게 처리하겠습니다."),
            "low": ("당분간은 그냥 두겠습니다.", "언제 다시 할지는 모르겠어요.",
                    "일단 내려주시면 됩니다."),
        },
        tags=("listing_hold", "existing_listing"),
    )


def bp_sell_low_floor(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="sell-low-floor",
        label="매도의뢰",
        persona="저층 물건을 내놓는 소유자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} {v['complex']} {v['building']} {v['unit']} 매도하려고요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} {v['building']} {v['unit']} 내놓겠습니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하고요, {v['complex']} {v['building']} {v['unit']}이에요.",
        ),
        identity_fields={"임대인": v["name"], "단지": v["complex"], "동": v["building"], "호": v["unit"]},
        beats=[
            Beat(
                ask=("몇 층이세요?", "층수가 어떻게 되나요?", "층과 향 알려주세요."),
                tell=(f"2층이에요. {v['area']}이고 {v['direction']}입니다.",
                      f"저층이에요. 2층이고 {v['area']}, {v['direction']}입니다.",
                      f"2층입니다. {v['area']}, {v['direction']}이에요."),
                fields={"평형": v["area"], "방향": v["direction"], "비고": "저층(2층) 물건"},
                tags=("low_floor",),
            ),
            Beat(
                ask=("희망가는 얼마인가요?", "가격은요?", "얼마로 내놓을까요?"),
                tell=(f"{v['price']}이요. 저층이라 시세보다 낮게 잡았어요.",
                      f"{v['price']}입니다.", f"{v['price']}으로 해주세요."),
                fields={"매매가": v["price"]},
            ),
            Beat(
                ask=("저층이라 불편한 점은 없으셨어요?", "소음이나 사생활 문제는 어떠세요?",
                     "저층 단점이 있을까요?"),
                tell=("앞에 나무가 있어서 생각보다 괜찮았어요.",
                      "아이 있는 집이면 오히려 편해요.", "겨울에 좀 춥긴 했어요."),
                optional=True,
                stage=2,
            ),
            Beat(
                ask=("내부 상태는 어떤가요?", "수리는 하셨어요?", "확장은 되어 있나요?"),
                tell=(f"{v['repair_years']} 전에 올수리했어요. 확장도 되어 있고요.",
                      "도배만 새로 했습니다.", "수리는 따로 안 했어요."),
                fields={"시설 상태": "고객 진술 기준"},
            ),
            Beat(
                ask=("거주 상태는요?", "지금 사시나요?", "공실인가요?"),
                tell=("저희가 살고 있어요.", "지금은 비어 있습니다.",
                      "세입자가 있어요."),
                fields={"현상태": "고객 진술 기준"},
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주세요.", "번호 알려주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"임대인 전화": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("저층이라도 필요한 분이 있을 테니 적극적으로 부탁드려요.",
                     "빨리 나갔으면 좋겠습니다.", "조건 맞으면 바로 보여드릴게요."),
            "mid": ("네, 저층 조건을 명확히 표시해서 접수하겠습니다.",
                    "네, 매물장에 올려두겠습니다.", "확인해서 등록하겠습니다."),
            "low": ("일단 시세만 좀 보고 결정할게요.", "등록은 조금 있다가 할게요.",
                    "상담만 남겨주세요."),
        },
        tags=("low_floor",),
    )


def bp_buy_investor(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-investor",
        label="매수문의",
        persona="전세 낀 물건을 찾는 투자자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} 실거주는 아니고 투자용으로 보고 있습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 전세 낀 물건 위주로 찾고 있어요.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 임대 놓을 집을 찾고 있습니다.",
        ),
        identity_fields={"구입자 이름": v["name"], "분류": "투자 목적"},
        beats=[
            Beat(
                ask=("거래 구분은 매매로 보시는 거죠?", "매매인가요?", "어떤 거래를 원하세요?"),
                tell=("네 매매입니다. 세입자 있는 채로 사는 게 좋아요.",
                      "매매요. 전세 승계 가능한 물건이면 좋겠습니다.",
                      "매매입니다."),
                fields={"거래 구분": "매매"},
            ),
            Beat(
                ask=("지역이나 단지는 정하셨나요?", "어느 쪽을 보세요?", "희망 지역을 알려주세요."),
                tell=(f"{v['region']} 쪽이면 다 봅니다. {v['complex']} 정도가 무난하던데요.",
                      f"{v['region']}에서 {v['complex']} 위주로 보고 있어요.",
                      f"{v['region']}이요. 단지는 조건 맞으면 어디든 봅니다."),
                fields={"희망 지역": v["region"]},
            ),
            Beat(
                ask=("평형은 어느 정도 보세요?", "몇 평 찾으세요?", "선호 평형이 있나요?"),
                tell=(f"{v['area_small']}이 세가 잘 나가서 그쪽으로 봅니다.",
                      f"{v['area_small']} 정도요.", f"{v['area_small']}이면 됩니다."),
                fields={"희망 평형": v["area_small"]},
            ),
            Beat(
                ask=("금액은 어느 선까지 보세요?", "예산이 어떻게 되나요?", "투자금은 얼마로 잡으세요?"),
                tell=(f"매매가 {v['budget']} 이하이면서 전세가 {v['jeonse']} 이상 나오는 물건이면 좋겠어요.",
                      f"{v['budget']}까지 봅니다. 실투자금은 최대한 줄이고 싶고요.",
                      f"{v['budget']} 안쪽이요."),
                fields={"금액 원문": v["budget"]},
                note="실투자금 조건은 전세가에 따라 달라져 확정 금액이 아님",
            ),
            Beat(
                ask=("입주 시기는 상관없으신가요?", "명도가 필요하세요?", "실입주 계획은 없으신 거죠?"),
                tell=("네 명도는 필요 없어요. 세입자 그대로 승계할 겁니다.",
                      "실입주 안 합니다. 만기 긴 물건이 오히려 좋아요.",
                      "그건 상관없습니다."),
                fields={"이사일 원문": "실입주 계획 없음"},
            ),
            Beat(
                ask=("이런 조건 나오면 바로 보실 수 있나요?", "결정은 빠르게 하시는 편인가요?",
                     "자금은 준비되셨어요?"),
                tell=("네 자금은 준비돼 있어요.", "조건만 맞으면 빠르게 갑니다.",
                      "대출을 좀 알아봐야 해서 확답은 어렵습니다."),
                optional=True,
                stage=2,
            ),
            Beat(
                ask=("연락처 남겨주세요.", "번호 알려주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("조건 맞는 거 나오면 바로 연락 주세요. 바로 봅니다.",
                     "물건만 좋으면 이번 주에 결정할 수 있어요.", "적극적으로 부탁드립니다."),
            "mid": ("네, 조건에 맞는 물건 나오면 연락드리겠습니다.",
                    "구입장에 등록해 두겠습니다.", "네, 접수하겠습니다."),
            "low": ("일단 어떤 물건이 있는지만 보내주세요.", "지금 당장은 아니고 시세만 보려고요.",
                    "천천히 보겠습니다."),
        },
        tags=("investor", "no_move_in"),
    )


def bp_buy_for_parent(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-for-parent",
        label="매수문의",
        persona="부모님 집을 대신 알아보는 자녀",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 부모님이 사실 집을 대신 알아보고 있어요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['kin']} 집을 알아보려고 전화드렸습니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, 부모님 집을 좀 보려고요.",
        ),
        identity_fields={"구입자 이름": v["name"], "비고": f"{v['kin']} 거주 예정, 자녀가 대리 문의"},
        beats=[
            Beat(
                ask=("거래 구분은 어떻게 되나요?", "매매로 보세요?", "어떤 조건으로 찾으세요?"),
                tell=("매매로 보고 있어요.", "매매입니다.", "매매요. 전세는 생각 안 합니다."),
                fields={"거래 구분": "매매"},
            ),
            Beat(
                ask=("어느 지역을 보세요?", "희망 지역이 있나요?", "어디 근처면 좋을까요?"),
                tell=(f"제가 사는 데서 가까운 {v['region']} 쪽이면 좋겠어요.",
                      f"{v['region']}이요. 병원이 가까우면 더 좋고요.",
                      f"{v['region']} 근처로 보고 있습니다."),
                fields={"희망 지역": v["region"]},
            ),
            Beat(
                ask=("평형은 어느 정도가 좋을까요?", "몇 평 보세요?", "넓이는요?"),
                tell=(f"두 분만 사실 거라 {v['area_small']} 정도면 충분해요.",
                      f"{v['area_small']}이요.", f"{v['area_small']} 정도가 관리하기 편할 것 같아요."),
                fields={"희망 평형": v["area_small"]},
            ),
            Beat(
                ask=("예산은 어떻게 되나요?", "금액 조건을 알려주세요.", "얼마까지 보세요?"),
                tell=(f"{v['budget']} 정도까지요. 부모님 집 판 돈으로 하실 거예요.",
                      f"{v['budget']}까지 가능합니다.", f"{v['budget']} 안쪽이면 좋겠어요."),
                fields={"금액 원문": v["budget"]},
                note="자금이 기존 주택 처분에 연동돼 시점과 금액이 바뀔 수 있음",
            ),
            Beat(
                ask=("층은 어느 정도가 좋으세요?", "선호하는 층이 있나요?", "저층도 괜찮으세요?"),
                tell=("무릎이 안 좋으셔서 엘리베이터는 꼭 있어야 하고 저층이면 더 좋아요.",
                      "고층은 무서워하셔서 중간층 정도요.", "그건 보고 정하려고요."),
                note="층과 엘리베이터 조건은 참고 사항이며 확정 필드로 두지 않음",
            ),
            Beat(
                ask=("입주 시기는요?", "언제쯤 이사하실 예정인가요?", "시기가 정해졌나요?"),
                tell=(f"{v['move_next']} 정도로 보고 있어요.",
                      "아직 정확하진 않아요. 집이 팔려야 정해집니다.",
                      f"{v['move_next']}쯤이면 좋겠습니다."),
                fields={"이사일 원문": v["move_next"]},
                optional=True,
            ),
            Beat(
                ask=("연락은 누구에게 드릴까요?", "번호 남겨주세요.", "연락처 알려주시겠어요?"),
                tell=(f"저한테 주세요. {v['phone']}입니다.",
                      f"{v['phone']}으로 연락 주시면 제가 전달할게요.",
                      f"제 번호가 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("좋은 물건 있으면 제가 먼저 보고 부모님 모시고 갈게요.",
                     "빨리 정하고 싶습니다.", "주말에 같이 보러 갈 수 있어요."),
            "mid": ("네, 조건 맞는 매물 찾아 연락드리겠습니다.",
                    "구입장에 등록해 두겠습니다.", "네, 접수해 두겠습니다."),
            "low": ("부모님이랑 상의해보고 다시 연락드릴게요.",
                    "아직 확정은 아니라서 자료만 받아볼게요.", "천천히 알아보는 중이에요."),
        },
        tags=("proxy_caller", "elderly_resident"),
    )


def bp_buy_corporate(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-corporate",
        label="매수문의",
        persona="직원 사택을 구하는 회사 담당자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 회사에서 직원 사택을 알아보고 있습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 법인 명의로 사택을 구하려고 합니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 합니다. 회사 사택 담당자예요.",
        ),
        identity_fields={"구입자 이름": v["name"], "분류": "법인 사택"},
        beats=[
            Beat(
                ask=("거래 구분은 어떻게 되나요?", "전세로 보시나요?", "어떤 조건이신가요?"),
                tell=("전세로 보고 있습니다. 법인 명의 계약이 가능해야 해요.",
                      "전세입니다. 법인 계약이 가능한지가 중요합니다.",
                      "전세요. 회사 명의로 진행합니다."),
                fields={"거래 구분": "전세"},
                note="법인 명의 계약 가능 여부는 임대인 확인이 필요함",
                tags=("corporate_lease",),
            ),
            Beat(
                ask=("어느 지역이 필요하신가요?", "위치 조건이 있나요?", "어디 근처를 보세요?"),
                tell=(f"사무실이 {v['region']}에 있어서 그 근처면 됩니다.",
                      f"{v['region']} 안이면 좋겠습니다.",
                      f"{v['region']}에서 도보 거리면 가장 좋고요."),
                fields={"희망 지역": v["region"]},
            ),
            Beat(
                ask=("평형은 어느 정도 필요하세요?", "몇 평 보세요?", "인원은 몇 명인가요?"),
                tell=(f"직원 두 명이 쓸 거라 {v['area']} 정도면 됩니다.",
                      f"{v['area']}이요.", f"{v['area']} 정도가 적당할 것 같습니다."),
                fields={"희망 평형": v["area"]},
            ),
            Beat(
                ask=("예산은 어떻게 되나요?", "보증금 한도가 있나요?", "금액 조건을 알려주세요."),
                tell=(f"보증금은 {v['jeonse']}까지 승인이 났습니다.",
                      f"{v['jeonse']} 이하로 봐주세요.", f"{v['jeonse']}까지 가능합니다."),
                ack=(f"전세 보증금 {v['jeonse']} 이하로 정리하겠습니다.",
                     f"네, {v['jeonse']} 확인했습니다.", f"{v['jeonse']} 이하로 보겠습니다."),
                fields={"금액 원문": v["jeonse"]},
            ),
            Beat(
                ask=("입주 시기는요?", "언제부터 필요하세요?", "일정이 어떻게 되나요?"),
                tell=(f"{v['move_next']}에 직원이 오기로 되어 있어서 그 전에 필요합니다.",
                      f"{v['move_next']}까지는 들어가야 합니다.",
                      "시기는 아직 확정 전입니다."),
                fields={"이사일 원문": v["move_next"]},
                optional=True,
            ),
            Beat(
                ask=("계약 절차는 어떻게 되나요?", "결재 과정이 있으신가요?",
                     "바로 계약이 가능하신가요?"),
                tell=("물건을 정하면 내부 결재를 받아야 해서 며칠 걸립니다.",
                      "제가 보고 결재를 올려야 합니다.",
                      "계약은 대표 명의로 하고 저는 실무만 봅니다."),
                note="법인 내부 결재 절차가 있어 계약 시점이 확정되지 않음",
                fields={"진행단계": "상담 접수"},
            ),
            Beat(
                ask=("연락처 남겨주시겠어요?", "번호 알려주세요.", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("일정이 급해서 이번 주에 보고 싶습니다.",
                     "결재는 빨리 올릴 수 있으니 물건만 알려주세요.", "가능하면 이번 달 안에 정리하고 싶습니다."),
            "mid": ("네, 법인 계약 가능한 물건 위주로 찾아보겠습니다.",
                    "조건 정리해서 등록하겠습니다.", "네, 확인해서 연락드리겠습니다."),
            "low": ("우선 시세만 파악하려던 거라 자료만 주세요.",
                    "예산 확정되면 다시 연락드리겠습니다.", "아직 검토 단계입니다."),
        },
        tags=("corporate_lease", "approval_needed"),
    )


def bp_buy_remote_worker(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-remote-worker",
        label="매수문의",
        persona="재택근무 공간이 필요한 수요자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 재택근무를 해서 방 하나를 작업실로 쓸 집을 찾아요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 집에서 일해서 조용한 집이 필요합니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, 재택이라 방 개수가 중요해요.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분은요?", "전세인가요 매매인가요?", "어떤 조건으로 보세요?"),
                tell=("전세로 보고 있어요.", "매매요.", "전세인데 조건 좋으면 매매도 봅니다."),
                fields={"거래 구분": "전세"},
            ),
            Beat(
                ask=("희망 지역이나 단지가 있나요?", "어느 쪽을 보세요?", "지역을 알려주세요."),
                tell=(f"{v['region']}에서 {v['complex']} 쪽을 보고 있어요.",
                      f"{v['region']}에 있는 {v['complex']}이면 됩니다.",
                      f"{v['complex']} 위주로 보는데 {v['region']} 안이면 다 좋아요."),
                fields={"희망 지역": v["region"], "희망 단지": v["complex"]},
            ),
            Beat(
                ask=("평형은 어느 정도요?", "방은 몇 개 필요하세요?", "넓이는 어떻게 보세요?"),
                tell=(f"{v['area']} 정도요. 방 세 개는 있어야 하나를 작업실로 씁니다.",
                      f"{v['area']}이요. 방이 중요해요.", f"{v['area']} 정도면 됩니다."),
                fields={"희망 평형": v["area"]},
            ),
            Beat(
                ask=("금액 조건은요?", "보증금은 얼마까지요?", "예산을 알려주세요."),
                tell=(f"{v['jeonse']}까지 봅니다.", f"{v['jeonse']} 이하요.",
                      f"{v['jeonse']} 정도로 생각하고 있어요."),
                fields={"금액 원문": v["jeonse"]},
            ),
            Beat(
                ask=("그 외 조건이 있으신가요?", "중요하게 보시는 게 있을까요?",
                     "추가로 필요한 조건이 있나요?"),
                tell=("낮에 통화를 많이 해서 소음이 적은 집이면 좋겠어요.",
                      "인터넷이 잘 되는지도 봐야 하고요.",
                      "위층 소음이 심하지 않은 집이면 좋겠습니다."),
                note="소음·인터넷 조건은 확인이 필요한 참고 사항이며 확정 필드가 아님",
            ),
            Beat(
                ask=("입주는 언제쯤요?", "이사 시기가 어떻게 되세요?", "언제 들어가세요?"),
                tell=(f"{v['move_next']} 정도요.", "급하진 않아요. 좋은 집 나오면요.",
                      f"{v['move_next']}까지면 좋겠습니다."),
                fields={"이사일 원문": v["move_next"]},
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주세요.", "번호 알려주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("조건 맞으면 바로 보러 가겠습니다.", "빨리 옮기고 싶어요.",
                     "이번 주말에 시간 됩니다."),
            "mid": ("네, 조건에 맞는 매물 찾아 연락드리겠습니다.",
                    "구입장에 등록하겠습니다.", "네, 접수해 두겠습니다."),
            "low": ("급한 건 아니라 좋은 집 나올 때 알려주세요.",
                    "일단 시세만 보려고요.", "천천히 보겠습니다."),
        },
        tags=("remote_work",),
    )


def bp_buy_school_district(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-school-district",
        label="매수문의",
        persona="학교 배정 때문에 이사하려는 학부모",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고', '고')} 아이 학교 때문에 이사를 알아보고 있습니다.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 학군 때문에 옮기려고요.",
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 아이 배정 문제로 문의드립니다.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분은요?", "매매인가요 전세인가요?", "어떤 조건으로 보세요?"),
                tell=("전세로 먼저 가보려고요.", "매매입니다.",
                      "전세가 나으면 전세, 아니면 매매도 봅니다."),
                fields={"거래 구분": "전세"},
            ),
            Beat(
                ask=("어느 학교를 보고 계세요?", "배정 학교가 정해져 있나요?",
                     "어느 쪽 학군을 원하세요?"),
                tell=(f"{v['region']} 쪽 초등학교로 배정되는 단지를 찾고 있어요.",
                      f"{v['region']}에 있는 학교로 보내고 싶어서요.",
                      f"학교는 정했는데 {v['region']}에서 어느 단지가 배정되는지를 모르겠어요."),
                fields={"희망 지역": v["region"]},
                note="학교 배정 여부는 교육청·학교 확인이 필요한 사항이라 단지를 단정할 수 없음",
                tags=("school_district",),
            ),
            Beat(
                ask=("단지는 정하셨나요?", "보고 계신 단지가 있어요?", "선호 단지가 있나요?"),
                tell=(f"{v['complex']}이 배정된다고 들었는데 맞는지 모르겠어요.",
                      f"{v['complex']} 정도를 보고 있습니다.",
                      f"배정만 되면 되는데 일단 {v['complex']} 기준으로 봐주세요."),
                fields={"희망 단지": v["complex"]},
                optional=True,
            ),
            Beat(
                ask=("평형은 어느 정도요?", "몇 평 보세요?", "넓이는요?"),
                tell=(f"{v['area']}이면 됩니다.", f"{v['area']} 정도요.",
                      f"{v['area']} 이상이면 좋겠어요."),
                fields={"희망 평형": v["area"]},
            ),
            Beat(
                ask=("예산은요?", "금액 조건을 알려주세요.", "얼마까지 보세요?"),
                tell=(f"{v['jeonse']}까지 봅니다.", f"{v['jeonse']} 이하요.",
                      f"{v['jeonse']} 정도로 생각합니다."),
                fields={"금액 원문": v["jeonse"]},
            ),
            Beat(
                ask=("언제까지 들어가셔야 하나요?", "입주 시기가 정해졌나요?", "일정이 어떻게 되세요?"),
                tell=("전입신고가 배정 기준일 전에 되어야 해서 늦어도 다음 달까지는 들어가야 해요.",
                      f"{v['move_next']} 전에는 옮겨야 합니다.",
                      "학기 시작 전에는 정리하고 싶어요."),
                fields={"이사일 원문": "배정 기준일 전"},
            ),
            Beat(
                ask=("연락처 남겨주세요.", "번호 알려주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다.", f"{v['phone']}으로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("기간이 정해져 있어서 급합니다. 나오면 바로 알려주세요.",
                     "이번 주에 보고 결정하고 싶어요.", "최대한 빨리 부탁드립니다."),
            "mid": ("네, 배정 여부부터 확인해 보시고 조건 맞는 매물 안내드리겠습니다.",
                    "구입장에 등록해 두겠습니다.", "네, 접수하겠습니다."),
            "low": ("배정부터 확인하고 다시 연락드릴게요.",
                    "아직 확정 전이라 자료만 받을게요.", "학교부터 알아보겠습니다."),
        },
        tags=("school_district", "deadline_driven"),
    )


def bp_buy_urgent_jeonse(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="buy-urgent-jeonse",
        label="매수문의",
        persona="만기가 임박해 급한 전세 수요자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 전세 만기가 코앞이라 급하게 알아보고 있어요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 급하게 전세를 구해야 합니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, 시간이 없어서 전화드렸어요.",
        ),
        identity_fields={"구입자 이름": v["name"]},
        beats=[
            Beat(
                ask=("거래 구분은 전세죠?", "전세로 찾으시는 거죠?", "조건이 어떻게 되세요?"),
                tell=("네 전세요.", "전세입니다.", "전세로만 봅니다."),
                fields={"거래 구분": "전세"},
            ),
            Beat(
                ask=("언제까지 들어가셔야 하나요?", "만기가 언제세요?", "일정이 어떻게 되나요?"),
                tell=(f"{v['expire']}에 만기라 그 전에는 무조건 나가야 해요.",
                      f"{v['expire']}까지입니다. 시간이 없어요.",
                      f"{v['expire']} 전에 이사해야 합니다."),
                fields={"이사일 원문": f"{v['expire']} 이전"},
                tags=("deadline_driven",),
            ),
            Beat(
                ask=("지역은 어디를 보세요?", "어느 쪽이든 괜찮으신가요?", "희망 지역이 있나요?"),
                tell=(f"{v['region']} 안이면 어디든 봅니다.",
                      f"{v['region']}이요. 지금은 가릴 처지가 아니에요.",
                      f"{v['region']} 근처로 보고 있어요."),
                fields={"희망 지역": v["region"]},
            ),
            Beat(
                ask=("평형은요?", "몇 평 보세요?", "넓이 조건이 있나요?"),
                tell=(f"{v['area']} 정도면 됩니다.", f"{v['area']}이요.",
                      f"{v['area']} 정도인데 더 작아도 괜찮아요."),
                fields={"희망 평형": v["area"]},
            ),
            Beat(
                ask=("보증금은 얼마까지 가능하세요?", "예산이 어떻게 되나요?", "금액 조건은요?"),
                tell=(f"{v['jeonse']}까지요. 지금 집 보증금 받아서 넣을 겁니다.",
                      f"{v['jeonse']} 이하요.", f"{v['jeonse']}까지 가능합니다."),
                ack=(f"보증금 {v['jeonse']} 이하로 보겠습니다.", f"네 {v['jeonse']} 확인했습니다.",
                     f"{v['jeonse']}으로 정리하겠습니다."),
                fields={"금액 원문": v["jeonse"]},
                note="보증금이 기존 계약 반환금에 연동돼 일정이 어긋나면 조건이 바뀔 수 있음",
            ),
            Beat(
                ask=("대출은 필요하신가요?", "자금 계획은 어떻게 되나요?", "대출도 보시나요?"),
                tell=("전세대출을 조금 받아야 할 것 같아요. 아직 신청 전입니다.",
                      "대출 없이 갑니다.", "지금 은행에 알아보는 중이에요."),
                note="전세대출 신청 전이라 실행 가능 여부가 확인되지 않음",
                optional=True,
            ),
            Beat(
                ask=("연락처 남겨주세요.", "번호 알려주시겠어요?", "연락은 어디로 드릴까요?"),
                tell=(f"{v['phone']}입니다. 아무 때나 전화 주세요.",
                      f"{v['phone']}으로 바로 주세요.",
                      f"번호는 {j(v['phone'], '이에요', '예요')}."),
                fields={"전화번호": v["phone"]},
                stage=3,
            ),
        ],
        closings={
            "high": ("오늘이라도 볼 수 있으니 나오면 바로 연락 주세요.",
                     "시간이 없어서요. 급하게 부탁드립니다.", "지금 바로 보러 갈 수 있습니다."),
            "mid": ("네, 조건 맞는 매물 나오는 대로 연락드리겠습니다.",
                    "구입장에 급건으로 등록하겠습니다.", "네, 접수하겠습니다."),
            "low": ("일단 어떤 게 있는지만 알려주세요.", "집주인과 연장 얘기도 해보고 있어요.",
                    "상황 보고 다시 연락드릴게요."),
        },
        tags=("deadline_driven", "urgent_lease"),
    )


def bp_other_cobroker_quick(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-cobroker-quick",
        label="기타상담",
        persona="매물 상태만 확인하는 상대 중개사",
        openings=greet(v),
        identity=(
            f"{v['brokerage2']}입니다. 하나만 여쭤볼게요.",
            f"네 {v['brokerage2']}인데요.",
            f"{v['brokerage2']}에서 전화드렸습니다.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(f"{v['complex']} {v['building']} {v['unit']} 아직 살아 있나요?",
                      f"{v['complex']} {v['unit']} 그거 나갔나요?",
                      f"{v['complex']} 매물 상태만 확인하려고요."),
                ack=("네 아직 진행 중입니다.", "그건 지난주에 계약됐습니다.",
                     "확인해 보고 말씀드리겠습니다."),
            ),
            Beat(
                tell=(f"가격은 {v['price']} 그대로죠?", "가격 변동 있었나요?",
                      "조건은 그대로인가요?"),
                ack=(f"네 {v['price']} 그대로입니다.", "조정 여지는 소유자 확인이 필요합니다.",
                     "가격은 변동 없습니다."),
            ),
            Beat(
                tell=("손님한테 보여드려도 될까요?", "저희 손님 모시고 가도 되나요?",
                      "공동중개 가능하신가요?"),
                ack=("네, 소유자 일정 확인해서 알려드리겠습니다.",
                     "네 가능합니다.", "일정만 맞으면 가능합니다."),
                note="방문 일정은 소유자 확인 후 정하기로 함",
            ),
            Beat(
                tell=("손님이 아직 확정은 아니에요.", "일단 물건만 파악하는 중입니다.",
                      "조건 보고 손님한테 얘기해 볼게요."),
                note="상대 중개사의 손님 의사가 확정되지 않음",
                optional=True,
            ),
        ],
        closings={
            "high": ("손님 확인하고 바로 다시 전화드릴게요.", "오늘 중으로 연락드리겠습니다.",
                     "확인되면 바로 연락드릴게요."),
            "mid": ("네, 확인해서 연락드리겠습니다.", "네, 상담 기록만 남기겠습니다.",
                    "알겠습니다. 다시 연락드리죠."),
            "low": ("일단 참고만 하겠습니다.", "확정되면 다시 연락드릴게요.",
                    "네, 나중에 다시 여쭙겠습니다."),
        },
        tags=("co_brokerage", "broker_to_broker", "no_field_proposal"),
    )


def bp_other_schedule_change(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-schedule-change",
        label="기타상담",
        persona="계약 일정을 조율하려는 계약 당사자",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 지난달에 여기서 계약한 사람이에요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 계약 건으로 문의드립니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, 계약 일정 때문에 전화드렸어요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=(f"잔금일이 {v['move']}인데 며칠 미룰 수 있을까요?",
                      "잔금 날짜를 조정하고 싶어서요.",
                      "대출 실행이 늦어져서 일정이 어긋날 것 같아요."),
                ack=("상대방 동의가 필요한 사항이라 먼저 확인해 보겠습니다.",
                     "네, 매도인분께 여쭤보겠습니다.",
                     "일정 변경은 양측 합의가 있어야 합니다."),
                note="잔금일 변경은 상대방 동의가 필요해 확정되지 않음",
                tags=("schedule_change",),
            ),
            Beat(
                ask=("얼마나 미루셔야 하나요?", "며칠 정도 필요하세요?", "언제로 하면 될까요?"),
                tell=("일주일 정도면 됩니다.", "은행 일정을 봐야 정확히 알겠어요.",
                      "사흘만 미뤄도 괜찮습니다."),
                note="변경 희망 일자가 확정되지 않음",
            ),
            Beat(
                ask=("계약서에 특약이 있으신가요?", "지연 시 조건은 확인하셨어요?",
                     "위약 관련 조항은 보셨나요?"),
                tell=("그건 제가 확인을 못 했어요.", "특약에 뭐라고 되어 있는지 봐주실 수 있나요?",
                      "그 부분이 걱정돼서 여쭤보는 거예요."),
                ack=("계약서 원본을 보고 안내드리겠습니다.",
                     "특약 내용에 따라 달라집니다.", "확인해서 알려드리겠습니다."),
                note="지연 시 책임은 계약서 특약 확인 후 판단해야 함",
            ),
            Beat(
                tell=("이사 업체도 이미 예약해서 걱정이에요.",
                      "잔금이 밀리면 이사도 밀려서요.",
                      "그날 못 하면 어떻게 되는지도 알고 싶어요."),
                ack=("양측 일정까지 같이 조율해 보겠습니다.",
                     "확인해서 정리해 드리겠습니다.", "그 부분도 함께 여쭤보겠습니다."),
                optional=True,
                stage=2,
            ),
        ],
        closings={
            "high": ("오늘 중으로 답을 들을 수 있을까요? 급합니다.",
                     "빨리 확인 부탁드립니다.", "은행에 알려줘야 해서 서둘러 주세요."),
            "mid": ("네, 상대방과 확인하고 연락드리겠습니다.",
                    "네, 상담 내용만 기록해 두겠습니다.", "확인해서 알려드리겠습니다."),
            "low": ("아직 확정은 아니고 가능한지만 알고 싶었어요.",
                    "혹시 몰라서 미리 여쭤본 거예요.", "천천히 확인해 주셔도 됩니다."),
        },
        tags=("schedule_change", "existing_contract", "no_field_proposal"),
    )


def bp_other_landlord_arrears(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-landlord-arrears",
        label="기타상담",
        persona="월세 미납을 상담하는 임대인",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, {v['complex']} {v['unit']} 임대인이에요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. {v['complex']} 집주인입니다.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 합니다. 여기서 월세 계약했던 집주인이에요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=("세입자가 월세를 두 달째 안 내서요.",
                      "월세가 밀리고 있는데 어떻게 해야 하나요?",
                      "임차인이 연락도 잘 안 됩니다."),
                ack=("우선 내용증명 등 절차를 확인해 보셔야 합니다.",
                     "몇 개월 연체인지에 따라 대응이 달라집니다.",
                     "상황을 좀 더 여쭤봐도 될까요?"),
                note="월세 연체 대응은 법적 절차라 중개사무소가 단정해 안내할 수 없음",
                tags=("arrears",),
            ),
            Beat(
                ask=("보증금은 얼마인가요?", "계약 조건이 어떻게 되나요?", "보증금과 월세를 알려주세요."),
                tell=(f"보증금 {v['wolse_deposit']}에 월세 {v['wolse_rent']}이에요.",
                      f"{v['wolse_deposit']}에 {v['wolse_rent']}입니다.",
                      "그건 계약서를 봐야 정확해요."),
                note="계약 조건은 상담 참고용이며 새 매물 접수 정보가 아님",
            ),
            Beat(
                ask=("계약 만기는 언제인가요?", "만기가 얼마나 남았어요?", "계약 기간을 알려주세요."),
                tell=(f"{v['due_next']}까지예요.", "아직 반년 넘게 남았습니다.",
                      "만기는 좀 남았어요."),
            ),
            Beat(
                tell=("보증금에서 까면 되는 거 아닌가요?",
                      "그냥 나가라고 할 수는 없나요?",
                      "제가 직접 찾아가도 되나요?"),
                ack=("임의로 처리하시면 오히려 문제가 될 수 있어 절차를 지키셔야 합니다.",
                     "그 부분은 법률 상담을 받아보시는 게 정확합니다.",
                     "직접 대응하시기 전에 확인이 필요합니다."),
                note="연체 처리 방법은 법률 상담이 필요한 사항임",
            ),
            Beat(
                tell=("이참에 그냥 팔아버릴까 싶기도 해요.",
                      "세입자 나가면 매도도 생각하고 있어요.",
                      "일단 이 문제부터 정리하고 싶어요."),
                note="매도 의사는 가정적 언급이라 매물 접수 조건으로 두지 않음",
                optional=True,
                stage=2,
            ),
        ],
        closings={
            "high": ("빨리 정리하고 싶어요. 도와주세요.",
                     "오늘이라도 방법을 알려주시면 좋겠습니다.", "급합니다."),
            "mid": ("네, 절차 안내드리고 상담 내용만 기록하겠습니다.",
                    "확인해서 연락드리겠습니다.", "네, 상담 로그로 남기겠습니다."),
            "low": ("일단 어떻게 되는지만 알고 싶었어요.",
                    "좀 더 지켜보려고요.", "네, 참고만 하겠습니다."),
        },
        tags=("arrears", "existing_contract", "no_field_proposal"),
    )


def bp_other_move_in_report(v: dict[str, str]) -> Blueprint:
    return Blueprint(
        key="other-move-in-report",
        label="기타상담",
        persona="전입신고 절차를 묻는 신규 임차인",
        openings=greet(v),
        identity=(
            f"제 이름은 {j(v['name'], '이고요', '고요')}, 이번에 {v['complex']}로 이사 가는 사람이에요.",
            f"제 이름은 {j(v['name'], '입니다', '입니다')}. 곧 입주하는데 절차를 몰라서요.",
            f"제 이름은 {j(v['name'], '이라고', '라고')} 하는데요, 처음 이사라 여쭤볼 게 있어요.",
        ),
        identity_fields={},
        beats=[
            Beat(
                tell=("전입신고는 언제 해야 하나요?", "이사하고 바로 하면 되나요?",
                      "전입신고를 미루면 안 되나요?"),
                ack=("잔금 치르고 이사한 날 바로 하시는 것이 안전합니다.",
                     "가능한 한 이사 당일에 하시는 게 좋습니다.",
                     "미루시면 보호를 못 받는 기간이 생깁니다."),
                note="전입신고 시점 안내는 일반 절차이며 개별 사안은 주민센터 확인이 필요함",
            ),
            Beat(
                tell=("확정일자는 따로 받아야 하나요?", "확정일자가 뭔가요?",
                      "전입신고랑 확정일자가 다른 건가요?"),
                ack=("네, 다른 절차입니다. 계약서에 확정일자를 따로 받으셔야 합니다.",
                     "주민센터에서 함께 처리하실 수 있습니다.",
                     "인터넷등기소에서도 가능합니다."),
            ),
            Beat(
                tell=("전세보증보험도 들어야 할까요?", "보증보험은 어떻게 가입하나요?",
                      "보험은 꼭 필요한가요?"),
                ack=("가입 요건이 있어서 주택 조건과 보증기관 기준을 확인하셔야 합니다.",
                     "보증기관에 직접 문의하시는 것이 정확합니다.",
                     "권해드리지만 가입 가능 여부는 확인이 필요합니다."),
                note="보증보험 가입 가능 여부는 보증기관 확인이 필요함",
                optional=True,
            ),
            Beat(
                ask=("이사는 언제 하세요?", "입주일이 정해졌나요?", "일정은 어떻게 되세요?"),
                tell=(f"{v['move']}이에요.", f"{v['move']}에 들어갑니다.",
                      "다음 주에 이사합니다."),
            ),
            Beat(
                tell=("관리비 정산은 누가 하나요?", "공과금은 어떻게 정리하나요?",
                      "이사 당일에 뭘 확인해야 하나요?"),
                ack=("이사 당일 관리사무소에서 정산하시면 됩니다.",
                     "전 세대 정산 내역을 확인하시면 됩니다.",
                     "당일에 함께 확인하시는 게 좋습니다."),
                optional=True,
                stage=2,
            ),
        ],
        closings={
            "high": ("알겠습니다. 이사 당일에 바로 처리할게요.",
                     "오늘 주민센터 가보겠습니다.", "감사합니다. 바로 준비하겠습니다."),
            "mid": ("네, 절차 안내만 드리고 상담 기록으로 남기겠습니다.",
                    "네, 궁금하신 거 있으면 또 연락 주세요.", "네, 도움 되셨으면 좋겠습니다."),
            "low": ("아직 이사는 멀었는데 미리 알아본 거예요.",
                    "참고만 하겠습니다.", "네, 나중에 다시 여쭤볼게요."),
        },
        tags=("procedure_inquiry", "no_field_proposal"),
    )


# --- 통화마다 다르게 끼어드는 곁가지 화제 ---
#
# blueprint의 핵심 사실만 쓰면 같은 상담이 늘 같은 순서로 흘러 대본처럼 보인다. 실제 통화는
# 본론 사이에 관리비, 주차, 학교, 소음 같은 이야기가 무작위로 끼어든다. 아래 pool에서 통화마다
# 다른 화제를 골라 다른 위치에 끼워 넣는다. 대부분 장부 필드가 아니라 참고 사항으로만 남는다.


def extra_sell_beats(v: dict[str, str]) -> list[Beat]:
    return [
        Beat(
            ask=("관리비는 보통 얼마나 나오나요?", "관리비 수준도 알 수 있을까요?", "관리비는 어느 정도예요?"),
            tell=(f"겨울에는 {v['fee']} 정도 나오고 여름에는 좀 덜 나와요.",
                  f"평균 {v['fee']} 정도였던 것 같아요.", "그건 정확히 기억이 안 나네요. 고지서를 봐야 알겠어요."),
            note="관리비는 고객 기억에 의존한 참고 정보라 접수 항목으로 두지 않음",
            optional=True, stage=2,
        ),
        Beat(
            ask=("주차는 몇 대까지 가능한가요?", "주차 자리는 넉넉한가요?", "주차 상황은 어떤가요?"),
            tell=("세대당 한 대는 되고 두 번째부터는 돈을 좀 더 내요.",
                  "저녁 늦게 오면 자리가 없을 때도 있어요.", "지하주차장이 있어서 크게 불편하진 않아요."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("혹시 지금 다른 사무소에도 내놓으셨나요?", "다른 곳에도 접수하셨어요?",
                 "저희만 진행하는 건가요?"),
            tell=(f"{v['brokerage2']}에도 한 번 물어봤어요.", "아직 여기만요.",
                  "몇 군데 더 알아보려고요."),
            note="다른 중개업소 동시 접수 여부는 고객 확인이 더 필요함",
            optional=True, stage=2,
        ),
        Beat(
            ask=("사진은 언제 찍으러 가면 될까요?", "매물 사진 촬영 일정을 잡을까요?",
                 "집 사진은 어떻게 할까요?"),
            tell=("주말에 정리하고 연락드릴게요.", "지금은 좀 어수선해서요. 치우고 알려드릴게요.",
                  "언제든 오셔도 됩니다."),
            note="사진 촬영 일정은 정해지지 않음",
            optional=True, stage=2,
        ),
        Beat(
            ask=("근처에 학교는 어떤가요?", "학군 문의가 들어오면 뭐라고 안내할까요?",
                 "주변 환경은 어떤가요?"),
            tell=("초등학교는 걸어서 5분 정도예요.", "단지 바로 앞에 초등학교가 있어요.",
                  "학교는 좀 떨어져 있는 편이에요."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("층간소음이나 하자 이력은 없으신가요?", "집에 손볼 데는 없나요?",
                 "특별히 알려주실 하자가 있을까요?"),
            tell=("따로 없어요. 조용한 편이에요.", "베란다 쪽에 곰팡이가 조금 있었는데 지금은 괜찮아요.",
                  "그건 제가 살면서 불편했던 건 없었어요."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("중개수수료는 어떻게 되는지 아세요?", "수수료 안내도 드릴까요?",
                 "복비 관련해서 궁금한 거 있으세요?"),
            tell=("아 그것도 나중에 알려주세요.", "그건 계약할 때 얘기하면 되죠?",
                  "대충은 아는데 정확히는 모르겠어요."),
            note="중개수수료는 계약 단계에서 다시 안내하기로 함",
            optional=True, stage=2,
        ),
        Beat(
            ask=("이사는 어디로 가세요?", "다음 집은 정하셨어요?", "이사 계획은 잡히셨나요?"),
            tell=(f"{v['region']} 쪽으로 갈 것 같아요.", "아직 못 정했어요. 이 집이 나가야 정할 것 같아요.",
                  "회사 근처로 가려고요."),
            optional=True, stage=2,
        ),
    ]


def extra_buy_beats(v: dict[str, str]) -> list[Beat]:
    return [
        Beat(
            ask=("혹시 지금 보고 계신 매물이 있으신가요?", "다른 데서도 보고 계세요?",
                 "이미 보신 집이 있나요?"),
            tell=(f"{v['complex3']}에서 하나 봤는데 별로였어요.", "아직 실제로 본 집은 없어요.",
                  "인터넷으로만 몇 개 봤습니다."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("관리비도 조건에 넣어드릴까요?", "관리비는 얼마까지 괜찮으세요?",
                 "관리비 부담은 어느 정도까지 보세요?"),
            tell=(f"{v['fee']} 넘어가면 좀 부담스러워요.", "그건 크게 상관없어요.",
                  "많이만 안 나오면 됩니다."),
            note="관리비 상한은 참고 조건이며 확정 필드로 두지 않음",
            optional=True, stage=2,
        ),
        Beat(
            ask=("주차는 몇 대 필요하세요?", "차량은 몇 대인가요?", "주차 조건도 있으신가요?"),
            tell=("차가 두 대라서 주차가 되는 곳이면 좋겠어요.", "한 대예요. 크게 상관없습니다.",
                  "주차만 편하면 좋겠어요."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("역이나 버스는 얼마나 가까워야 할까요?", "교통은 어떻게 보세요?",
                 "출퇴근은 어떻게 하세요?"),
            tell=("지하철역에서 걸어서 10분 안쪽이면 좋겠어요.", "차로 다녀서 역은 상관없어요.",
                  "버스만 있어도 괜찮습니다."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("집은 언제 보실 수 있으세요?", "방문 가능한 시간대가 있나요?",
                 "평일에도 시간이 되세요?"),
            tell=("평일은 어렵고 주말 오전이면 됩니다.", "저녁 7시 이후면 언제든 괜찮아요.",
                  "그건 그때 조율하면 될 것 같아요."),
            note="방문 가능 시간은 확정된 일정이 아님",
            optional=True, stage=2,
        ),
        Beat(
            ask=("수리된 집을 원하시나요?", "인테리어 상태는 어느 정도를 보세요?",
                 "올수리된 집만 보시나요?"),
            tell=("수리된 집이면 좋지만 아니어도 봅니다.", "도배 정도는 저희가 해도 돼요.",
                  "가능하면 손 안 대도 되는 집이면 좋겠어요."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("혹시 급한 사정이 있으신가요?", "언제까지 정해야 하세요?",
                 "시간 여유는 좀 있으세요?"),
            tell=("계약 만기가 있어서 좀 급해요.", "여유는 좀 있습니다.",
                  "당장은 아니지만 마음에 들면 바로 하고 싶어요."),
            optional=True, stage=2,
        ),
        Beat(
            ask=("문자로 매물 보내드려도 될까요?", "자료는 어떻게 보내드릴까요?",
                 "사진 먼저 받아보시겠어요?"),
            tell=("네 문자로 보내주세요.", "사진 먼저 보고 고를게요.",
                  "전화로 말씀해 주시면 제가 메모할게요."),
            optional=True, stage=3,
        ),
    ]


def extra_other_beats(v: dict[str, str]) -> list[Beat]:
    return [
        Beat(
            tell=("그리고 요즘 그쪽 시세는 좀 어때요?", "요즘 거래는 좀 되나요?",
                  "그 동네 분위기는 어떤가요?"),
            ack=("최근에는 문의가 조금 늘었습니다.", "거래는 있는 편입니다.",
                 "단지마다 차이가 있어서 확인이 필요합니다."),
            note="시세 동향 안내는 일반 정보이며 특정 매물 조건이 아님",
            optional=True, stage=2,
        ),
        Beat(
            tell=("혹시 상담 비용이 따로 드나요?", "전화 문의도 비용이 있나요?",
                  "이런 것도 수수료가 붙나요?"),
            ack=("전화 상담은 따로 비용을 받지 않습니다.", "상담 자체는 무료입니다.",
                 "계약이 이뤄질 때만 중개보수가 발생합니다."),
            optional=True, stage=2,
        ),
        Beat(
            tell=("영업 시간은 어떻게 되세요?", "몇 시까지 하세요?", "주말에도 문 여시나요?"),
            ack=("평일은 저녁 7시까지 하고 주말은 오후까지 합니다.", "주말에도 오전에는 나와 있습니다.",
                 "일요일은 쉽니다."),
            optional=True, stage=3,
        ),
        Beat(
            tell=("문자로 남겨주셔도 되나요?", "제가 전화를 잘 못 받아서요.",
                  "나중에 다시 전화드려도 될까요?"),
            ack=("네, 문자로 남겨드리겠습니다.", "네 편하실 때 연락 주세요.",
                 "네, 기록해 두겠습니다."),
            optional=True, stage=3,
        ),
        Beat(
            tell=("혹시 제 정보가 어디 저장되나요?", "개인정보는 어떻게 관리되나요?",
                  "이름 남기면 어디에 쓰이나요?"),
            ack=("상담 기록으로만 남기고 동의 없이 다른 곳에 쓰지 않습니다.",
                 "상담 목적으로만 보관합니다.", "필요 없으시면 남기지 않아도 됩니다."),
            note="개인정보 저장 범위를 안내했으며 장부 등록 사항은 아님",
            optional=True, stage=2,
        ),
    ]


EXTRA_POOLS: dict[str, Callable[[dict[str, str]], list[Beat]]] = {
    "매도의뢰": extra_sell_beats,
    "매수문의": extra_buy_beats,
    "기타상담": extra_other_beats,
}


BLUEPRINTS: dict[int, Callable[[dict[str, str]], Blueprint]] = {
    0: bp_sell_resident,
    1: bp_sell_jeonse_coowner,
    2: bp_sell_cautious_private,
    3: bp_sell_urgent_wolse,
    4: bp_sell_proxy,
    5: bp_sell_rent_listing,
    6: bp_sell_old_manager,
    7: bp_sell_redevelopment,
    8: bp_sell_swap,
    9: bp_sell_presale_right,
    10: bp_sell_tenant_conflict,
    11: bp_sell_price_cut,
    12: bp_sell_hold,
    13: bp_sell_low_floor,
    20: bp_buy_newlywed,
    21: bp_buy_commuter_jeonse,
    22: bp_buy_firstjob_wolse,
    23: bp_buy_large_family,
    24: bp_buy_pet_wolse,
    25: bp_buy_investor,
    26: bp_buy_for_parent,
    27: bp_buy_corporate,
    28: bp_buy_remote_worker,
    29: bp_buy_school_district,
    30: bp_buy_urgent_jeonse,
    40: bp_other_cobroker_pro,
    41: bp_other_cobroker_assistant,
    42: bp_other_simple_fee,
    43: bp_other_jeonse_loan,
    44: bp_other_lost_contract,
    45: bp_other_tenant_repair,
    46: bp_other_cobroker_quick,
    47: bp_other_schedule_change,
    48: bp_other_landlord_arrears,
    49: bp_other_move_in_report,
}

SELL_BLUEPRINTS = tuple(range(0, 14))
BUY_BLUEPRINTS = tuple(range(20, 31))
OTHER_BLUEPRINTS = tuple(range(40, 50))


@dataclass(frozen=True)
class CellSpec:
    name: str
    label: str
    ledger: str
    blueprints: tuple[int, ...]
    shapes: int
    rows_per_group: int
    slot_offset: int


# 셀 비중은 "무엇을 배워야 하는가"로 정한다.
#
# 필드 추출이 이 모델의 본업이라 장부와 상담 유형이 맞는 행을 다수로 둔다. 기타상담은
# 필드를 만들지 않는 판단 자체가 모델의 일이라 실제 상담 비중만큼 남긴다. 장부 불일치는
# consultation_type과 ledger_type만 있으면 계산되는 값이라 많이 배울 필요가 없지만,
# 장부가 어긋났을 때 엉뚱한 필드를 만들지 않게 하려면 최소한은 필요하다.
CELLS = (
    # slot_offset은 어휘 풀 크기의 공배수를 피해 다른 셀이 같은 슬롯 조합을 쓰지 않게 한다.
    CellSpec("sell-on-property", "매도의뢰", "매물장", SELL_BLUEPRINTS, 9, 4, 0),
    CellSpec("buy-on-buyer", "매수문의", "구입장", BUY_BLUEPRINTS, 11, 4, 2003),
    CellSpec("sell-on-buyer", "매도의뢰", "구입장", SELL_BLUEPRINTS, 2, 4, 4001),
    CellSpec("buy-on-property", "매수문의", "매물장", BUY_BLUEPRINTS, 2, 4, 6007),
    CellSpec("other-on-property", "기타상담", "매물장", OTHER_BLUEPRINTS, 4, 4, 8009),
    CellSpec("other-on-buyer", "기타상담", "구입장", OTHER_BLUEPRINTS, 4, 4, 10007),
)

def build_row(cell: CellSpec, blueprint: int, shape: int, slot_index: int, seq: int) -> dict[str, Any]:
    # 5와 3은 서로소라 shape가 늘어도 두 축이 고르게 섞인다.
    turn_shape = TURN_SHAPES[shape % len(TURN_SHAPES)]
    temp = TEMPERATURES[shape % len(TEMPERATURES)]
    v = slots(slot_index)
    rng = Rng(slot_index * 131 + blueprint * 17 + shape)
    bp = BLUEPRINTS[blueprint](v)
    label = bp.label
    mismatch = label != "기타상담" and (
        (label == "매도의뢰" and cell.ledger != "매물장")
        or (label == "매수문의" and cell.ledger != "구입장")
    )
    script = render(bp, v, turn_shape, temp, rng, ledger_words_ok=not mismatch)
    # 장부 불일치는 열려 있는 장부와 상담 내용의 차이로만 판단해야 한다. 통화 안에서
    # 장부 종류를 언급하면 모델이 그 문장만 보고 맞히게 되므로 transcript는 건드리지 않는다.

    fields = dict(script.fields)
    evidence = dict(script.evidence)
    uncertainties = list(script.uncertainties)
    tags = list(script.tags)

    if label == "기타상담":
        fields, evidence = {}, {}
        summary = "기타상담으로 판단해 장부 필드를 제안하지 않았습니다."
        if uncertainties:
            summary += " 추가 확인: " + " / ".join(uncertainties) + "."
        tags = tags + ["no_field_proposal"] if "no_field_proposal" not in tags else tags
    elif mismatch:
        fields, evidence = {}, {}
        uncertainties = [f"현재 {cell.ledger}과 {label} 상담 유형이 일치하지 않음"]
        summary = f"{label}로 판단했으나 현재 장부가 {j(cell.ledger, '이라', '라')} 필드를 제안하지 않았습니다."
        tags = tags + ["ledger_mismatch"]
    else:
        summary = f"{label} 상담의 확인된 조건: " + ", ".join(f"{k} {val}" for k, val in fields.items()) + "."
        if uncertainties:
            summary += " 추가 확인: " + " / ".join(uncertainties) + "."
        if len(fields) >= 8 and "many_fields" not in tags:
            tags.append("many_fields")

    row = {
        "sample_id": f"f2-full-v05-hw-{cell.name}-{seq:04d}",
        "dataset_version": DATASET_VERSION,
        "label": label,
        "transcript": script.transcript,
        "ledger_type": cell.ledger,
        "expected": {
            "consultation_type": label,
            "ledger_mismatch": mismatch,
            "fields": fields,
            "evidence": evidence,
            "uncertainties": uncertainties,
            "summary": summary,
        },
        "source_type": SOURCE_TYPE,
        "source_group_id": f"f2-full-v05-hw-{cell.name}-bp{blueprint:02d}-s{shape:02d}",
        "split": "unassigned",
        "contains_real_personal_data": False,
        "review_status": REVIEW_STATUS,
        "difficulty_tags": tags,
        "source_scenario_id": None,
    }
    return row, script.identity, bp.persona


def make_records() -> tuple[list[dict[str, Any]], dict[str, str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    personas: Counter[str] = Counter()
    slot_index = 0
    for cell in CELLS:
        seq = 0
        for blueprint in cell.blueprints:
            for shape in range(cell.shapes):
                for _ in range(cell.rows_per_group):
                    seq += 1
                    slot_index += 1
                    row, identity, persona = build_row(cell, blueprint, shape, slot_index, seq)
                    rows.append(row)
                    identities[row["sample_id"]] = identity
                    personas[persona] += 1
    return rows, identities, personas


FORBIDDEN_PATTERNS = (
    re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)
PHONE_PATTERN = re.compile(r"01[016789]-\d{4}-\d{4}")
LOOSE_PHONE_PATTERN = re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}")
SPEAKER_PREFIX_PATTERN = re.compile(r"(?:^|\s)(?:중개사|고객)\s*:")


def validate(rows: list[dict[str, Any]], identities: dict[str, str]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    label_counts: Counter[str] = Counter()
    cell_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    transcripts: set[str] = set()
    sample_ids: set[str] = set()
    phones: set[str] = set()
    mismatch_rows = 0
    rows_with_fields = 0

    for row in rows:
        if tuple(row) != MERGED_KEY_ORDER:
            raise ValueError(f"key order mismatch: {row['sample_id']}")
        if row["dataset_version"] != DATASET_VERSION:
            raise ValueError(f"version mismatch: {row['sample_id']}")
        if row["split"] != "unassigned":
            raise ValueError(f"split must be unassigned: {row['sample_id']}")
        if row["contains_real_personal_data"] is not False:
            raise ValueError(f"privacy flag must be false: {row['sample_id']}")
        if row["review_status"] != REVIEW_STATUS:
            raise ValueError(f"review status mismatch: {row['sample_id']}")
        if row["sample_id"] in sample_ids:
            raise ValueError(f"duplicate sample_id: {row['sample_id']}")
        sample_ids.add(row["sample_id"])

        text = row["transcript"]
        if text in transcripts:
            raise ValueError(f"duplicate transcript: {row['sample_id']}")
        transcripts.add(text)
        if any(pattern.search(text) for pattern in FORBIDDEN_PATTERNS):
            raise ValueError(f"possible personal data: {row['sample_id']}")
        if SPEAKER_PREFIX_PATTERN.search(text):
            raise ValueError(f"speaker prefix found in STT transcript: {row['sample_id']}")
        identity = identities[row["sample_id"]]
        if not identity or identity not in text:
            raise ValueError(f"caller self-identification missing: {row['sample_id']}")
        for match in LOOSE_PHONE_PATTERN.finditer(text):
            if not PHONE_PATTERN.fullmatch(match.group(0)):
                raise ValueError(f"unexpected phone format: {row['sample_id']} {match.group(0)}")
            phones.add(match.group(0))
        if not row["difficulty_tags"]:
            raise ValueError(f"missing difficulty tags: {row['sample_id']}")
        tag_counts.update(row["difficulty_tags"])

        expected = row["expected"]
        if set(expected) != {
            "consultation_type", "ledger_mismatch", "fields", "evidence", "uncertainties", "summary"
        }:
            raise ValueError(f"expected key mismatch: {row['sample_id']}")
        if expected["consultation_type"] != row["label"]:
            raise ValueError(f"label mismatch: {row['sample_id']}")
        fields = expected["fields"]
        evidence = expected["evidence"]
        if set(fields) != set(evidence):
            raise ValueError(f"fields and evidence keys differ: {row['sample_id']}")
        if not set(fields) <= ALLOWED_FIELDS[row["ledger_type"]]:
            raise ValueError(
                f"field outside ledger vocabulary: {row['sample_id']} "
                f"{sorted(set(fields) - ALLOWED_FIELDS[row['ledger_type']])}"
            )
        for key, snippet in evidence.items():
            if snippet not in text:
                raise ValueError(f"evidence not found in transcript: {row['sample_id']} {key}")
        if row["label"] == "기타상담" and fields:
            raise ValueError(f"기타상담 must not propose fields: {row['sample_id']}")
        if expected["ledger_mismatch"]:
            mismatch_rows += 1
            if fields or evidence:
                raise ValueError(f"mismatch row must not propose fields: {row['sample_id']}")
            if not expected["uncertainties"]:
                raise ValueError(f"mismatch row needs uncertainty note: {row['sample_id']}")
        if fields:
            rows_with_fields += 1
            field_counts.update(fields.keys())
        if not expected["summary"]:
            raise ValueError(f"empty summary: {row['sample_id']}")

        groups[row["source_group_id"]].append(row)
        label_counts[row["label"]] += 1
        cell_counts[f"{row['ledger_type']}+{row['label']}"] += 1

    for group_id, members in groups.items():
        if len({m["ledger_type"] for m in members}) != 1 or len({m["label"] for m in members}) != 1:
            raise ValueError(f"group spans multiple cells: {group_id}")

    lengths = sorted(len(row["transcript"]) for row in rows)
    return {
        "rows": len(rows),
        "source_groups": len(groups),
        "blueprints": len(BLUEPRINTS),
        "duplicate_sample_ids": 0,
        "duplicate_transcripts": 0,
        "distinct_phone_numbers": len(phones),
        "ledger_mismatch_rows": mismatch_rows,
        "rows_with_fields": rows_with_fields,
        "rows_without_fields": len(rows) - rows_with_fields,
        "transcript_chars_min": lengths[0],
        "transcript_chars_median": lengths[len(lengths) // 2],
        "transcript_chars_max": lengths[-1],
        "label_distribution": dict(sorted(label_counts.items())),
        "cell_distribution": dict(cell_counts.most_common()),
        "field_distribution": dict(field_counts.most_common()),
        "difficulty_tag_distribution": dict(tag_counts.most_common()),
    }


def write_outputs(rows: list[dict[str, Any]], report: dict[str, Any], personas: Counter[str]) -> None:
    data_path = OUT_DIR / f"{STEM}.jsonl"
    with data_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()

    def yaml_map(mapping: dict[str, Any], indent: str) -> str:
        return "\n".join(f"{indent}{key}: {value}" for key, value in mapping.items())

    manifest = f"""dataset_id: {DATASET_ID}
dataset_version: {DATASET_VERSION}
status: draft_label_review_pending
created_at: {GENERATED_AT}
updated_at: {GENERATED_AT}

purpose:
  - 사람이 쓴 상담 통화를 사실 단위로 분해해 F2 full-output 학습·검증 후보를 만든다
  - 상황, 화자, 전달 형태, 거래 의지 온도를 흩어 실제 통화에 가까운 분포를 만든다

format: jsonl
data_file: {STEM}.jsonl
privacy_record: {STEM}.privacy.md

schema:
  record_id_field: sample_id
  fields:
{chr(10).join(f"    - {key}" for key in MERGED_KEY_ORDER)}
  label_values: [매도의뢰, 매수문의, 기타상담]
  notes:
    - expected는 consultation_type, ledger_mismatch, fields, evidence, uncertainties, summary의 6-key 객체다.
    - 키 순서와 스키마를 f2_merged_full_output_scenarios v0.5와 동일하게 맞췄다.
    - evidence 값은 transcript의 실제 부분 문자열이며 중개사 복창 문장이 근거가 되는 사례를 포함한다.
    - 공동중개 사례는 발신자가 다른 중개사라 고객 이름 대신 사무소명으로 자기소개한다.

axes:
  blueprints: {report['blueprints']}
  turn_shapes: {list(TURN_SHAPES)}
  intent_temperatures: {list(TEMPERATURES)}
  wording_variants: 4
  persona_distribution:
{yaml_map(dict(personas.most_common()), '    ')}

lineage:
  source_types:
    - {SOURCE_TYPE}
  source_reference:
    - data/f2_llm/working/f2_handwritten_dialogue_samples.privacy_safe.v0.5.md
  derivation: >-
    각 통화를 사실 단위 beat로 적고, 전달 형태(질의응답, 앞부분 몰아 말하기, 중개사 주도,
    중간 끊김, 짧은 통화), 거래 의지 온도(높음·중간·낮음), 표현 변형, 합성 슬롯 값으로 확장했다.
    같은 (cell, blueprint, shape)를 공유하는 행은 슬롯 값만 다르며 하나의 source_group_id를 갖는다.
  usage_terms: 프로젝트 내부 개발·학습·평가 전용 합성 데이터
  human_verified: false
  supersedes: null
  generation:
    tooling: data/scripts/generate_f2_handwritten_dialogue_scenarios.py
    random_seed: null
    reproducible: true
    command: python3 data/scripts/generate_f2_handwritten_dialogue_scenarios.py

counts:
  total: {report['rows']}
  train: 0
  validation: 0
  test: 0
label_distribution:
{yaml_map(report['label_distribution'], '  ')}
cell_distribution:
{yaml_map(report['cell_distribution'], '  ')}
source_distribution:
  {SOURCE_TYPE}: {report['rows']}

split:
  method: unassigned_working_draft
  group_key: source_group_id
  random_seed: null
  requirements:
    - source_group_id를 서로 다른 split으로 나누지 않는다.
    - 같은 blueprint에서 나온 행은 사실 구성이 겹치므로 분할 보고서에서 blueprint 분포도 확인한다.

privacy:
  classification: 내부
  contains_real_personal_data: false
  processing_purpose: F2 full-output 모델 개발·학습·평가
  storage_location: Git 저장소의 data/f2_llm/working
  access_subjects: 프로젝트 저장소 접근 권한이 있는 팀원
  external_transfer: 명시적으로 실행한 승인된 RunPod 실험 환경에서만 합성 transcript 처리 가능
  retention_and_deletion: working 초안은 검수 승인 또는 반려 시 새 버전 발행이나 삭제로 처리
  controls:
    - 실제 상담 원문을 읽지 않고 작성자가 쓴 대화만 확장
    - 인명·단지·지역·중개업소는 합성 어휘 풀만 사용
    - 주민등록번호와 이메일 형식 검사
    - 전화번호는 010-XXXX-XXXX 형식만 허용하고 그 외 형식은 생성 실패로 처리
  reidentification_mapping: none

validation:
  validated_at: {GENERATED_AT}
  validated_by: data/scripts/generate_f2_handwritten_dialogue_scenarios.py
  method: >-
    키 순서, expected 6-key, 라벨·장부 불일치 규칙, fields/evidence 대응, 장부별 허용 필드,
    근거 원문 포함, 기타상담 필드 금지, 발신자 자기소개 문장 포함, sample_id·transcript 중복,
    그룹 단일 셀, 개인정보 패턴과 전화번호 형식을 검사했다.
  results:
{yaml_map({k: val for k, val in report.items() if isinstance(val, int)}, '    ')}

checksums:
  algorithm: sha256
  {STEM}.jsonl: {digest}

known_limitations:
  - 사람 검수 전 초안이며 필드 정답, 근거, 상담 로그 초안은 작성자 판단이다.
  - 방언 표기는 작성자가 만든 근사치이며 실제 지역 화자의 발화 분포를 대표하지 않는다.
  - 전화번호는 무작위 조합이라 실제 가입 번호와 우연히 일치할 수 있다.
  - blueprint가 {report['blueprints']}종이라 사실 구성은 그 범위 안에서 반복된다.
  - train·validation·test 분할이 아직 없으며 모든 행이 unassigned다.
  - 값 자체를 훼손하는 실제 STT 오류는 evidence 부분 문자열 계약 때문에 아직 담지 못했다.
allowed_use: 분할·SFT 변환 도구 검증, 사람이 검수할 라벨 초안, 비공개 개발 학습·평가
prohibited_use:
  - 사람 검수 전 정식 골드 평가 또는 운영 성능 주장
  - 같은 source_group_id를 서로 다른 split에 배치
"""
    (OUT_DIR / f"{STEM}.manifest.yaml").write_text(manifest, encoding="utf-8")

    privacy = f"""---
status: 검수 전 초안
updated: {GENERATED_AT}
---

# F2 손으로 쓴 대화 확장 데이터 개인정보 기록

## 처리 범위

- 작성자가 쓴 상담 통화 {report['blueprints']}종을 blueprint로 두고 {report['rows']}건으로 확장했다.
- 실제 상담 녹취, STT 결과, 고객 정보를 읽거나 참조하지 않았다.
- 인물, 단지, 도시, 구, 동, 중개업소, 담당자는 모두 합성 어휘 풀에서만 나온다.

## 전화번호

- 형식은 `010-XXXX-XXXX`이며 슬롯 인덱스에서 결정적으로 만든다.
- 생성된 서로 다른 번호는 {report['distinct_phone_numbers']}개다.
- 무작위 조합이므로 실제 가입 번호와 우연히 일치할 수 있다. 실제 인물과 연결된 정보는 아니지만
  외부 공개나 발신 테스트에는 사용하지 않는다.

## 자동 검증 결과

`python3 data/scripts/generate_f2_handwritten_dialogue_scenarios.py`로 다음을 확인했다.

- 총 {report['rows']}건, `source_group_id` {report['source_groups']}개
- `sample_id`와 transcript 중복 0건
- 주민등록번호·이메일 형식 0건
- `010-XXXX-XXXX` 외 전화번호 표기 0건
- `contains_real_personal_data=false` 아닌 행 0건
- expected 6-key, 라벨·장부 불일치, fields/evidence, 근거 원문 계약 오류 0건
- 필드 보유 {report['rows_with_fields']}건, 필드 없음 {report['rows_without_fields']}건,
  장부 불일치 {report['ledger_mismatch_rows']}건

## 저장·접근·외부 처리

- 저장 위치: Git 저장소 `data/f2_llm/working/`
- 접근 주체: 프로젝트 저장소 접근 권한이 있는 팀원
- 외부 처리: 명시적으로 실행한 승인된 RunPod 학습·평가 환경에서만 허용
- 보존·삭제: working 초안은 검수 승인 또는 반려 시 새 버전 발행이나 삭제로 처리

## 남은 한계

- 필드 정답, evidence, summary는 사람 검수 전 초안이다.
- 방언 표기는 작성자가 만든 근사치이며 실제 지역 화자 발화가 아니다.
- 합성 데이터이므로 실제 상담·STT 분포를 대표한다고 볼 수 없다.
"""
    (OUT_DIR / f"{STEM}.privacy.md").write_text(privacy, encoding="utf-8")


NORMALIZED_FIELDS = frozenset(
    {"현상태", "명도 조건", "확장 여부", "시설 상태", "비고", "융자", "거래 구분",
     "금액 원문", "이사일 원문", "현매물", "진행상태", "진행단계", "분류", "완료 여부"}
)


def check_blueprints() -> None:
    """표현 변형을 어떻게 고르든 선언한 필드 값이 발화에 남아 있는지 확인한다.

    값을 정규화해 적는 필드는 예외로 둔다. 그 외 필드는 근거 문장에 값이 그대로 나와야
    정답이 원문보다 앞서 나가지 않는다.
    """

    for slot_index in range(1, 60):
        v = slots(slot_index)
        for blueprint_id, factory in BLUEPRINTS.items():
            bp = factory(v)
            for position, beat in enumerate(bp.beats):
                for tell in beat.tell:
                    for key, value in beat.fields.items():
                        if key not in NORMALIZED_FIELDS and value not in tell:
                            raise ValueError(
                                f"blueprint {blueprint_id} beat {position}: '{key}' 값이 발화에 없음"
                            )
                for ack in beat.ack:
                    for key, value in beat.ack_fields.items():
                        if key not in NORMALIZED_FIELDS and value not in ack:
                            raise ValueError(
                                f"blueprint {blueprint_id} beat {position}: '{key}' 값이 복창에 없음"
                            )


def main() -> None:
    check_blueprints()
    rows, identities, personas = make_records()
    report = validate(rows, identities)
    write_outputs(rows, report, personas)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
