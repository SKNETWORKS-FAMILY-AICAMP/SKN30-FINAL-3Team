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

    세션 발급 때 HttpOnly 쿠키에 함께 보관한 CSRF 원문을 DB 해시와 대조한 뒤 그대로 싣는다.
    조회 시 서버의 CSRF 상태를 바꾸지 않아 여러 탭이 서로의 토큰을 무효화하지 않는다.
    """

    user: CurrentUserResponse
    csrf_token: str
