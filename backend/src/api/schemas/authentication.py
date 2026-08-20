from pydantic import BaseModel

from domain.authentication.models import CurrentUser


class CurrentUserResponse(BaseModel):
    id: int
    brokerage_id: int
    login_id: str
    display_name: str
    role: str

    @classmethod
    def from_domain(cls, user: CurrentUser) -> "CurrentUserResponse":
        return cls(
            id=user.id,
            brokerage_id=user.brokerage_id,
            login_id=user.login_id,
            display_name=user.display_name,
            role=user.role.value,
        )


class DevelopmentSessionResponse(BaseModel):
    user: CurrentUserResponse
    csrf_token: str


class SessionUserResponse(BaseModel):
    """세션 확인 응답.

    CSRF 토큰을 함께 싣는다. 토큰은 발급 응답에만 있었기 때문에, 새로고침으로 화면 메모리가
    비면 세션은 살아 있는데 쓰기만 403이 되는 구멍이 있었다.
    """

    user: CurrentUserResponse
    csrf_token: str
