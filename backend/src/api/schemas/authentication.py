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
