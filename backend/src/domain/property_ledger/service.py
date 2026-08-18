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


def create_property_unit(session: Session, brokerage_id: int, payload: dict[str, Any]) -> int:
    complex_id = int(payload["complex_id"])
    if repository.find_property_complex(session, brokerage_id, complex_id) is None:
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


def update_property_listing(
    session: Session, brokerage_id: int, listing_id: int, payload: dict[str, Any]
) -> None:
    expected_row_version = int(payload.pop("row_version"))
    if repository.find_property_listing(session, brokerage_id, listing_id) is None:
        raise NotFoundError("property listing is not found")
    if not payload:
        return

    updated = repository.bump_row_version(
        session, PropertyListing, brokerage_id, listing_id, expected_row_version, payload
    )
    if not updated:
        session.rollback()
        raise RowVersionConflictError()
    session.commit()


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
) -> None:
    expected_row_version = int(payload.pop("row_version"))
    require_property_requirement(session, brokerage_id, requirement_id)

    has_complex_change = "desired_complex_ids" in payload
    desired_complex_ids = payload.pop("desired_complex_ids", None)
    if has_complex_change:
        validate_complex_ids(session, brokerage_id, desired_complex_ids or [])

    if payload:
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

    if has_complex_change:
        repository.replace_requirement_complexes(
            session, brokerage_id, requirement_id, desired_complex_ids or []
        )
    session.commit()


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
