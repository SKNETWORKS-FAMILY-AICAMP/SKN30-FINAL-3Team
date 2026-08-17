from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from sqlalchemy import JSON, BigInteger, Column, DateTime, func
from sqlmodel import Field, SQLModel


class UserRole(StrEnum):
    OWNER = "OWNER"
    STAFF = "STAFF"
    READ_ONLY = "READ_ONLY"


class Brokerage(SQLModel, table=True):
    __tablename__: ClassVar[str] = "brokerage"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    name: str = Field(max_length=120)
    business_registration_number: str | None = Field(default=None, max_length=20)
    settings: dict[str, object] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: str = Field(default="ACTIVE", max_length=20)
    row_version: int = Field(default=1)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class AppUser(SQLModel, table=True):
    __tablename__: ClassVar[str] = "app_user"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    brokerage_id: int = Field(foreign_key="brokerage.id")
    login_id: str = Field(max_length=100)
    password_hash: str
    display_name: str = Field(max_length=80)
    role: str = Field(max_length=20)
    is_active: bool = True
    last_login_at: datetime | None = None
    row_version: int = 1
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class UserSession(SQLModel, table=True):
    __tablename__: ClassVar[str] = "user_session"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    brokerage_id: int
    user_id: int
    session_token_hash: str = Field(max_length=64)
    csrf_token_hash: str = Field(max_length=64)
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = Field(default=None, max_length=80)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    brokerage_id: int
    login_id: str
    display_name: str
    role: UserRole


@dataclass(frozen=True)
class AuthenticationContext:
    user: CurrentUser
    session_id: int
    csrf_token_hash: str
