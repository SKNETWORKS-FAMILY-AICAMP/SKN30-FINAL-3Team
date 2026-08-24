from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from core.errors import (
    NotFoundError,
    PrivacyConsentRequiredError,
    RowVersionConflictError,
    ValidationError,
)
from domain.property_ledger import repository
from domain.property_ledger.models import (
    ClientInteraction,
    PropertyComplex,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
)


def require_property_unit(session: Session, brokerage_id: int, unit_id: int) -> Any:
    found = repository.find_property_unit(session, brokerage_id, unit_id)
    if found is None:
        raise NotFoundError("property unit is not found")
    return found


def require_property_requirement(session: Session, brokerage_id: int, requirement_id: int) -> Any:
    found = repository.find_property_requirement(session, brokerage_id, requirement_id)
    if found is None:
        raise NotFoundError("property requirement is not found")
    return found


def create_property_complex(session: Session, brokerage_id: int, payload: dict[str, Any]) -> int:
    """단지를 만든다. 세대를 등록하려면 단지가 먼저 있어야 한다."""
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValidationError("name must not be empty")
    if repository.find_property_complex_by_name(session, brokerage_id, name) is not None:
        raise ValidationError("complex name already exists in this brokerage")

    complex_row = PropertyComplex(brokerage_id=brokerage_id, **{**payload, "name": name})
    session.add(complex_row)
    session.flush()
    session.commit()
    return complex_row.id or 0


def delete_property_complex(
    session: Session, brokerage_id: int, complex_id: int, expected_row_version: int
) -> None:
    """단지를 소프트 삭제한다.

    세대가 남아 있으면 거절한다. 세대는 단지를 필수로 참조하므로 단지를 먼저 감추면
    그 세대들이 이름 없는 상태가 된다. 지우려면 세대를 먼저 정리해야 한다.

    세대 수를 세기 전에 단지 행을 배타로 잠근다. 세대 등록은 같은 행의 공유 잠금을 거치므로,
    "세대가 없음"을 확인한 시점과 커밋 사이에 새 세대가 끼어들 수 없다.
    """
    if repository.lock_property_complex(session, brokerage_id, complex_id, exclusive=True) is None:
        raise NotFoundError("property complex is not found")

    remaining = repository.count_units_in_complex(session, brokerage_id, complex_id)
    if remaining > 0:
        # 거절하고 나가는 길이므로 잠금을 바로 놓는다. 안 그러면 세대 등록이 세션이
        # 닫힐 때까지 기다린다.
        session.rollback()
        # 화면이 사유를 그대로 안내할 수 있도록 코드를 준다.
        raise ValidationError(
            f"this complex still has {remaining} unit(s)", code="COMPLEX_HAS_UNITS"
        )

    updated = repository.bump_row_version(
        session,
        PropertyComplex,
        brokerage_id,
        complex_id,
        expected_row_version,
        {"is_deleted": True, "deleted_at": datetime.now(UTC)},
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()


def create_property_unit(session: Session, brokerage_id: int, payload: dict[str, Any]) -> int:
    """세대를 만든다.

    단지 행을 공유 잠금으로 확인한다. 단지 삭제는 같은 행의 배타 잠금을 거치므로, 확인 시점과
    커밋 사이에 단지가 사라질 수 없다. 삭제가 먼저 커밋됐다면 잠근 뒤 읽을 때 이미 감춰져 있어
    여기서 거절된다. 공유 잠금이므로 다른 세대 등록과는 서로 기다리지 않는다.
    """
    complex_id = int(payload["complex_id"])
    if repository.lock_property_complex(session, brokerage_id, complex_id, exclusive=False) is None:
        raise ValidationError("complex_id does not belong to this brokerage")

    unit = PropertyUnit(brokerage_id=brokerage_id, **payload)
    session.add(unit)
    session.flush()
    session.commit()
    return unit.id or 0


def update_property_unit(
    session: Session, brokerage_id: int, unit_id: int, payload: dict[str, Any]
) -> None:
    expected_row_version = int(payload.pop("row_version"))
    require_property_unit(session, brokerage_id, unit_id)
    if not payload:
        return

    updated = repository.bump_row_version(
        session, PropertyUnit, brokerage_id, unit_id, expected_row_version, payload
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()


def delete_property_unit(
    session: Session, brokerage_id: int, unit_id: int, expected_row_version: int
) -> None:
    """세대를 소프트 삭제한다.

    행을 실제로 지우지 않는다. 상담 로그와 매물 이력이 세대를 참조하고 있어 물리 삭제는
    이력을 함께 잃는다. 목록 조회는 이미 `is_deleted = false`만 본다.

    딸린 매물 건은 건드리지 않는다. 매물 건은 자신의 `row_version`을 따로 갖고 있어,
    한 요청에서 함께 수정하면 그 낙관적 잠금 경계를 우회한다. 매물 조회는 세대를 join하므로
    세대가 감춰지면 매물도 목록에 나타나지 않는다.
    """
    require_property_unit(session, brokerage_id, unit_id)
    deleted_at = datetime.now(UTC)
    updated = repository.bump_row_version(
        session,
        PropertyUnit,
        brokerage_id,
        unit_id,
        expected_row_version,
        {"is_deleted": True, "deleted_at": deleted_at},
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()


def delete_property_requirement(
    session: Session, brokerage_id: int, requirement_id: int, expected_row_version: int
) -> None:
    """구입장 행을 소프트 삭제한다. 상담 로그는 남긴다."""
    require_property_requirement(session, brokerage_id, requirement_id)
    updated = repository.bump_row_version(
        session,
        PropertyRequirement,
        brokerage_id,
        requirement_id,
        expected_row_version,
        {"is_deleted": True, "deleted_at": datetime.now(UTC)},
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()


def create_property_listing(
    session: Session, brokerage_id: int, unit_id: int, payload: dict[str, Any]
) -> int:
    require_property_unit(session, brokerage_id, unit_id)
    if payload.get("client_party_id") is not None:
        client_party_id = int(payload["client_party_id"])
        if repository.find_party(session, brokerage_id, client_party_id) is None:
            raise ValidationError("client_party_id does not belong to this brokerage")

    listing = PropertyListing(brokerage_id=brokerage_id, unit_id=unit_id, **payload)
    session.add(listing)
    session.flush()
    session.commit()
    return listing.id or 0


def changed_columns(current: Any, payload: dict[str, Any]) -> set[str]:
    """실제로 값이 달라지는 컬럼만 고른다.

    같은 값을 다시 보낸 저장은 변경이 아니다. 호출자가 저장 뒤에 후속 동작을 걸 때 이
    구분이 필요하다. 비교는 저장 직전의 행 값으로 한다.
    """
    return {key for key, value in payload.items() if getattr(current, key, None) != value}


def update_property_listing(
    session: Session, brokerage_id: int, listing_id: int, payload: dict[str, Any]
) -> frozenset[str]:
    """매물 건을 부분 수정하고 **실제로 바뀐 필드 집합**을 돌려준다.

    같은 값을 다시 보낸 저장은 쓰기가 아니므로 `row_version`도 올리지 않는다. 단, 요청의
    버전이 이미 낡았다면 값이 같더라도 낙관적 잠금 계약대로 충돌을 돌려준다.
    """
    expected_row_version = int(payload.pop("row_version"))
    current = repository.find_property_listing(session, brokerage_id, listing_id)
    if current is None:
        raise NotFoundError("property listing is not found")

    changed = changed_columns(current, payload)
    if current.row_version != expected_row_version:
        session.rollback()
        raise RowVersionConflictError()
    if not changed:
        session.commit()
        return frozenset()

    updated = repository.bump_row_version(
        session, PropertyListing, brokerage_id, listing_id, expected_row_version, payload
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()
    return frozenset(changed)


def require_privacy_consent(session: Session, brokerage_id: int, party_id: int) -> None:
    """구입장 저장 전 인물의 개인정보 활용 동의를 확인한다 (F1-DM-16)."""
    party = repository.find_party(session, brokerage_id, party_id)
    if party is None:
        raise ValidationError("party_id does not belong to this brokerage")
    if party.privacy_consent_at is None:
        raise PrivacyConsentRequiredError()


def create_property_requirement(
    session: Session, brokerage_id: int, payload: dict[str, Any]
) -> int:
    party_id = int(payload["party_id"])
    require_privacy_consent(session, brokerage_id, party_id)

    desired_complex_ids = payload.pop("desired_complex_ids", []) or []
    validate_complex_ids(session, brokerage_id, desired_complex_ids)
    if payload.get("co_broker_party_id") is not None:
        co_broker_party_id = int(payload["co_broker_party_id"])
        if repository.find_party(session, brokerage_id, co_broker_party_id) is None:
            raise ValidationError("co_broker_party_id does not belong to this brokerage")

    requirement = PropertyRequirement(brokerage_id=brokerage_id, **payload)
    session.add(requirement)
    session.flush()
    repository.replace_requirement_complexes(
        session, brokerage_id, requirement.id or 0, desired_complex_ids
    )
    session.commit()
    return requirement.id or 0


def update_property_requirement(
    session: Session, brokerage_id: int, requirement_id: int, payload: dict[str, Any]
) -> frozenset[str]:
    """구입장을 부분 수정하고 **실제로 바뀐 필드 집합**을 돌려준다.

    희망 단지는 **집합으로** 비교한다. 순서만 다르고 같은 단지를 다시 보낸 저장은 변경이
    아니므로 자식 테이블과 `row_version`도 건드리지 않는다. 실제 변경이 없어도 요청 버전이
    낡았다면 낙관적 잠금 계약대로 충돌을 돌려준다.
    """
    expected_row_version = int(payload.pop("row_version"))
    # 장부 단건 조회는 인물을 함께 돌려준다. 비교 대상은 구입장 행이다.
    current, _party = require_property_requirement(session, brokerage_id, requirement_id)

    has_complex_change = "desired_complex_ids" in payload
    desired_complex_ids = payload.pop("desired_complex_ids", None)
    changed = changed_columns(current, payload)
    if has_complex_change:
        validate_complex_ids(session, brokerage_id, desired_complex_ids or [])
        stored = {
            link.complex_id
            for link, _ in repository.list_requirement_complexes(
                session, brokerage_id, requirement_id
            )
        }
        if stored != set(desired_complex_ids or []):
            changed.add("desired_complex_ids")

    if current.row_version != expected_row_version:
        session.rollback()
        raise RowVersionConflictError()
    if not changed:
        session.commit()
        return frozenset()

    # 희망 단지가 실제로 바뀌었으면 스칼라 필드가 없어도 버전을 올린다.
    #
    # 희망 단지는 자식 테이블에 있어 구입장 행을 건드리지 않는다. 그대로 두면 단지만 바꾼
    # 저장이 `row_version` 을 올리지 않아, 클라이언트의 낡은 상세 화면이 충돌로 잡히지 않고
    # 같은 버전을 키로 쓰는 F3 실행 재사용도 바뀐 조건을 보지 못한다.
    updated = repository.bump_row_version(
        session,
        PropertyRequirement,
        brokerage_id,
        requirement_id,
        expected_row_version,
        payload,
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()

    if "desired_complex_ids" in changed:
        repository.replace_requirement_complexes(
            session, brokerage_id, requirement_id, desired_complex_ids or []
        )
    session.commit()
    return frozenset(changed)


def validate_complex_ids(session: Session, brokerage_id: int, complex_ids: list[int]) -> None:
    for complex_id in complex_ids:
        if repository.find_property_complex(session, brokerage_id, complex_id) is None:
            raise ValidationError("desired_complex_ids contains an unknown complex")


def create_client_interaction(
    session: Session, brokerage_id: int, user_id: int, payload: dict[str, Any]
) -> int:
    """상담 로그를 추가하고 대상 원장의 최종접촉일을 갱신한다."""
    unit_id = payload.get("unit_id")
    requirement_id = payload.get("requirement_id")
    party_id = payload.get("party_id")
    listing_id = payload.get("listing_id")
    if unit_id is None and requirement_id is None and party_id is None and listing_id is None:
        raise ValidationError("one of unit_id, listing_id, requirement_id or party_id is required")

    if unit_id is not None:
        require_property_unit(session, brokerage_id, int(unit_id))
    if requirement_id is not None:
        require_property_requirement(session, brokerage_id, int(requirement_id))
    if party_id is not None and repository.find_party(session, brokerage_id, int(party_id)) is None:
        raise ValidationError("party_id does not belong to this brokerage")
    if (
        listing_id is not None
        and repository.find_property_listing(session, brokerage_id, int(listing_id)) is None
    ):
        raise ValidationError("listing_id does not belong to this brokerage")

    interaction_at = payload.get("interaction_at") or datetime.now(UTC)
    payload["interaction_at"] = interaction_at

    interaction = ClientInteraction(brokerage_id=brokerage_id, created_by=user_id, **payload)
    session.add(interaction)
    session.flush()
    repository.touch_last_contact(
        session,
        brokerage_id,
        int(unit_id) if unit_id is not None else None,
        int(requirement_id) if requirement_id is not None else None,
        interaction_at,
    )
    session.commit()
    return interaction.id or 0
