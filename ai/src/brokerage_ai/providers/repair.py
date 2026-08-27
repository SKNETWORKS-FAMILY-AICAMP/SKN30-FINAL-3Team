"""계약을 어긴 구조화 출력을 모델에게 되먹여 다시 만들게 한다.

구조화 출력의 **교차 필드 규칙은 JSON schema 로 표현할 수 없다.** "마감일을 세우려면 근거
제약이 하나 이상 있어야 한다" 같은 규칙은 스키마 문법에 자리가 없어 모델이 그 존재를 모른 채
답하고, 우리는 답을 받은 뒤 `model_validator` 에서 거절한다. 프롬프트로 알려 주더라도 규칙이
쌓이면 그중 하나를 흘린다.

그래서 재시도만으로는 부족하다. 포지션 카드와 중개 판정은 재현성을 위해 온도 0으로 부르므로
(F3-NF-08) **같은 입력을 다시 던지면 같은 답이 온다.** 실제로 Worker 의 lease 재시도 3회가
동일한 위반을 세 번 반복하고 종료하는 것을 확인했다.

여기서는 다음 시도의 **입력을 바꾼다.** 검증이 지적한 내용을 대화에 덧붙여 다시 부른다. 입력이
달라지므로 온도 0에서도 다른 표본이 나오고, 모델은 그제서야 자기가 어긴 규칙을 안다.

이 함수는 어댑터 안이 아니라 **생성기가 부르는 자리**에 있다. 되먹여 고칠 실패가 두 층에 있기
때문이다.

- `responses.parse` 안에서 나는 `ProviderOutputInvalidError`
- 응답을 공개 결과로 조립하고 요청과 대조할 때 나는 `ValidationError` 와 `OutputContractError`

어댑터 안에 두면 아래층을 덮지 못한다. 인용문 위조("quote is not present in interaction 91")가
바로 아래층이며 LLM 의 대표적인 실패다. `core` 는 지금 어느 기능 모듈도 import 하지 않으므로
여기에 둔다. Provider 를 어떻게 부르는지에 대한 코드이고 두 생성기가 이미 이 패키지의 port 를
가져다 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from brokerage_ai.core.errors import (
    OutputContractError,
    ProviderOutputInvalidError,
    describe_validation_error,
)
from brokerage_ai.core.types import (
    ChatMessage,
    MessageRole,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from brokerage_ai.providers.ports import LlmProvider

# 원본 1회 + 되먹임 2회. Worker 의 lease 재시도 3회와 곱해지므로 한 실행 단계의 외부 호출은
# 최대 9회다. 되먹임 한 번으로 안 고쳐지는 경우까지 흡수하되 상한은 눈에 보이게 둔다.
REPAIR_MAX_ATTEMPTS = 3

_REPAIR_TEMPLATE = """직전 응답이 계약 검증에 걸려 폐기됐다.
지적된 곳만 고쳐 같은 요청을 다시 수행한다.

검증 결과: {detail}

- 지적되지 않은 판단은 바꾸지 않는다.
- 규칙을 지키려고 근거를 지어내지 않는다. 근거를 세울 수 없으면 값을 null 또는 UNKNOWN 으로 둔다."""


async def generate_with_repair[OutputT: BaseModel, ResultT](
    *,
    provider: LlmProvider,
    request: StructuredGenerationRequest,
    output_schema: type[OutputT],
    finalize: Callable[[StructuredGenerationResult[OutputT]], ResultT],
    max_attempts: int = REPAIR_MAX_ATTEMPTS,
) -> ResultT:
    """계약을 통과한 결과가 나올 때까지 되먹이며 다시 부른다.

    `finalize` 는 응답을 공개 결과로 조립하고 요청과 대조하는 일 전체를 받는다. 조립과 대조도
    모델 출력이 원인이 될 수 있으므로 같은 되먹임 대상이다.

    되먹일 수 있는 실패만 잡는다. 시간 초과나 rate limit 은 모델에게 알려 줄 것이 없으므로 그대로
    올려보내 Worker 의 lease 재시도에 맡긴다.

    상한을 다 쓰면 **마지막 예외를 그대로 다시 던진다.** 새 타입으로 감싸면 Backend 의 실행
    수명주기 분류가 달라진다. 이 함수는 성공률만 바꾸고 실패의 등급은 바꾸지 않는다.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    attempted = request
    for remaining in range(max_attempts - 1, -1, -1):
        try:
            return finalize(await provider.generate_structured(attempted, output_schema))
        except (ProviderOutputInvalidError, ValidationError, OutputContractError) as error:
            if remaining == 0:
                raise
            # 원본 messages 뒤에 지적 한 건만 붙인다. 직전 되먹임은 버린다. 누적하면 시도마다
            # 대화가 길어지고 이미 고친 지적이 새 답을 흔든다.
            attempted = request.model_copy(
                update={
                    "messages": (
                        *request.messages,
                        ChatMessage(
                            role=MessageRole.USER,
                            content=_REPAIR_TEMPLATE.format(detail=_detail_of(error)),
                        ),
                    )
                }
            )

    raise AssertionError("unreachable: the loop returns or raises on every path")


def _detail_of(error: ProviderOutputInvalidError | ValidationError | OutputContractError) -> str:
    """모델에게 돌려줄 지적 한 줄.

    담기는 것은 셋뿐이다. 필드 경로(`timing`), 우리가 계약에 적어 둔 고정 규칙 문구, 그리고
    식별자(`interaction 91`). 모델이 만든 값과 상담 원문은 담지 않는다. `describe_validation_error`
    는 Pydantic 이 기본 문자열에 싣는 `input` 을 이미 제외한다.
    """
    if isinstance(error, ValidationError):
        return describe_validation_error(error)
    if isinstance(error, ProviderOutputInvalidError):
        return error.detail or "출력이 계약을 어겼다"
    return str(error)
