"""캘린더 화면에서 사용자가 직접 추가하는 일정.

Time Keeper(``domain.time_keeper``)가 장부에서 계산해 읽는 일정과는 저장소가 다르다. 이 도메인은
``calendar_event`` 테이블에 대한 쓰기(생성·수정·소프트 삭제)와 날짜 범위 조회를 소유한다.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import ClassVar

from sqlalchemy import BigInteger, Column, Date, DateTime, Text, Time, func
from sqlmodel import Field, SQLModel


def identity_column() -> Column[int]:
    return Column(BigInteger, primary_key=True, autoincrement=True)


def timestamp_column() -> Column[datetime]:
    return Column(DateTime(timezone=True))


def created_timestamp_column() -> Column[datetime]:
    """서버가 채우는 NOT NULL 시각. DB의 DEFAULT now()가 적용되도록 server_default를 붙인다."""
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CalendarEvent(SQLModel, table=True):
    __tablename__: ClassVar[str] = "calendar_event"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: int | None = Field(default=None, sa_column=identity_column())
    brokerage_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    title: str = Field(max_length=200)
    category: str = Field(default="ETC", max_length=30)
    event_date: date = Field(sa_column=Column(Date, nullable=False))
    start_time: time | None = Field(default=None, sa_column=Column(Time))
    end_time: time | None = Field(default=None, sa_column=Column(Time))
    location: str | None = Field(default=None, max_length=200)
    memo: str | None = Field(default=None, sa_column=Column(Text))
    created_by: int | None = Field(default=None, sa_column=Column(BigInteger))
    row_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    is_deleted: bool = False
    deleted_at: datetime | None = Field(default=None, sa_column=timestamp_column())
    created_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
    updated_at: datetime | None = Field(default=None, sa_column=created_timestamp_column())
