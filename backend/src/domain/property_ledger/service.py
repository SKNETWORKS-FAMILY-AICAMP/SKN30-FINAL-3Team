from __future__ import annotations

import re
from datetime import UTC, date, datetime
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
    Party,
    PartyContact,
    PropertyComplex,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
    PropertyUnitPartyRelation,
)

#: 매물장 그리드가 만드는 인물은 모두 자연인이다. 법인 임대인은 상세에서 따로 다룬다.
DEFAULT_PARTY_TYPE = "PERSON"
#: 그리드의 전화 칸은 휴대전화 한 개만 받는다.
DEFAULT_CONTACT_METHOD = "PHONE"


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


def normalize_contact_value(value: str) -> str:
    """연락처 비교용 정규화 값.

    `party_contact`는 사용자 입력 원문(`contact_value`)과 정규화 값을 함께 둔다. 원문은
    `010-1234-5678`처럼 사람이 읽는 형태로 남기고, 중복 판정과 검색은 정규화 값으로 한다.
    """
    return re.sub(r"[^0-9a-zA-Z@.]", "", value)


def upsert_primary_contact(
    session: Session, brokerage_id: int, party_id: int, phone: str | None
) -> bool:
    """인물의 대표 연락처를 그리드가 입력한 값으로 맞춘다. 실제로 바꿨으면 True.

    전화 칸을 비운 것은 "연락처를 지운다"는 뜻이므로 기존 대표 연락처를 소프트 삭제한다.
    연락처 이력은 다른 화면이 참조할 수 있어 행을 실제로 지우지 않는다.

    같은 값을 다시 보낸 것은 변경이 아니다. 호출자가 이 값을 모아 세대 `row_version`을
    올릴지 정하므로, 바뀌지 않은 저장이 버전을 올려 다른 화면을 헛되이 충돌시키지 않게 한다.
    """
    contacts = [
        contact
        for contact in repository.list_party_contacts(session, brokerage_id, [party_id])
        if contact.contact_method == DEFAULT_CONTACT_METHOD
    ]
    primary = next((contact for contact in contacts if contact.is_primary), None)

    cleaned = (phone or "").strip()
    if cleaned == "":
        if primary is None:
            return False
        primary.is_deleted = True
        primary.deleted_at = datetime.now(UTC)
        session.add(primary)
        return True

    if primary is not None:
        if primary.contact_value == cleaned:
            return False
        primary.contact_value = cleaned
        primary.normalized_contact_value = normalize_contact_value(cleaned)
        session.add(primary)
        return True

    session.add(
        PartyContact(
            brokerage_id=brokerage_id,
            party_id=party_id,
            contact_method=DEFAULT_CONTACT_METHOD,
            contact_value=cleaned,
            normalized_contact_value=normalize_contact_value(cleaned),
            is_primary=True,
        )
    )
    return True


def _replace_unit_parties(
    session: Session, brokerage_id: int, unit_id: int, entries: list[dict[str, Any]]
) -> bool:
    """세대의 인물 관계를 요청이 보낸 집합으로 맞춘다. 실제로 바꿨으면 True.

    커밋과 롤백은 호출자가 한다. 호출자는 반환값으로 세대 `row_version`을 올릴지 정한다.
    인물은 별도 테이블이지만 화면에서는 세대 행의 칸이므로, 인물만 바뀐 저장도 세대의
    동시 편집으로 감지되어야 한다.

    인물만 단독으로 저장하는 경로는 두지 않는다. 그리드가 인물을 세대 행의 칸으로 다루므로
    저장은 언제나 `save_property_unit`을 거친 세대 저장의 일부다.

    그리드는 임대인·임차인을 각각 한 칸에 접어 보여주므로 부분 수정이라는 개념이 없다.
    보낸 목록이 곧 그 세대의 현재 인물 전체이고, 빠진 자리는 관계가 끝난 것으로 본다.

    관계를 끝낼 때 인물 자체는 지우지 않는다. 같은 인물이 다른 세대나 구입장에 걸려 있을 수
    있고, 상담 로그도 인물을 참조한다. `valid_to`를 채워 현재 관계에서만 빼면
    `uq_unit_party_relation_current_role`(valid_to IS NULL 부분 유니크)도 그대로 지켜진다.
    """
    require_property_unit(session, brokerage_id, unit_id)

    changed = False
    existing = {
        (relation.role, relation.role_index): (relation, party)
        for relation, party in repository.list_unit_party_relations(session, brokerage_id, unit_id)
    }
    wanted: set[tuple[str, int]] = set()

    for entry in entries:
        role = str(entry["role"]).strip().upper()
        role_index = int(entry.get("role_index") or 1)
        name = str(entry["name"]).strip()
        if role == "" or name == "":
            raise ValidationError("party role and name are required")
        key = (role, role_index)
        if key in wanted:
            raise ValidationError(f"duplicate party slot: {role}#{role_index}")
        wanted.add(key)

        found = existing.get(key)
        if found is None:
            party = Party(brokerage_id=brokerage_id, party_type=DEFAULT_PARTY_TYPE, name=name)
            session.add(party)
            session.flush()
            session.add(
                PropertyUnitPartyRelation(
                    brokerage_id=brokerage_id,
                    unit_id=unit_id,
                    party_id=party.id or 0,
                    role=role,
                    role_index=role_index,
                    is_primary=role_index == 1,
                    is_co_owner=bool(entry.get("is_co_owner")),
                    valid_from=date.today(),
                )
            )
            changed = True
        else:
            relation, party = found
            is_co_owner = bool(entry.get("is_co_owner"))
            if party.name != name:
                party.name = name
                session.add(party)
                changed = True
            if relation.is_co_owner != is_co_owner:
                relation.is_co_owner = is_co_owner
                session.add(relation)
                changed = True

        session.flush()
        if upsert_primary_contact(session, brokerage_id, party.id or 0, entry.get("phone")):
            changed = True

    ended_at = date.today()
    for key, (relation, _party) in existing.items():
        if key in wanted:
            continue
        relation.valid_to = ended_at
        session.add(relation)
        changed = True

    return changed


def _create_property_unit(session: Session, brokerage_id: int, payload: dict[str, Any]) -> int:
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
    return unit.id or 0


def create_property_unit(session: Session, brokerage_id: int, payload: dict[str, Any]) -> int:
    """세대만 따로 만든다."""
    try:
        unit_id = _create_property_unit(session, brokerage_id, payload)
    except Exception:
        session.rollback()
        raise
    session.commit()
    return unit_id


def _require_row_version(
    session: Session, brokerage_id: int, unit_id: int, expected_row_version: int
) -> None:
    """PATCH 시작에서 세대를 읽고 버전을 확인한다.

    아무 필드도 바뀌지 않는 요청에서도 낡은 버전은 거절해야 한다. 뒤따르는 조건부 UPDATE가
    실제 직렬화를 맡지만, 쓸 것이 하나도 없으면 그 UPDATE가 실행되지 않아 낡은 버전이
    조용히 통과한다.
    """
    current, _complex_row = require_property_unit(session, brokerage_id, unit_id)
    if current.row_version != expected_row_version:
        raise RowVersionConflictError()


def _update_property_unit(
    session: Session,
    brokerage_id: int,
    unit_id: int,
    expected_row_version: int,
    payload: dict[str, Any],
) -> bool:
    """세대 필드를 고친다. 실제로 썼으면 True. 커밋과 롤백은 호출자가 한다."""
    if not payload:
        return False

    updated = repository.bump_row_version(
        session, PropertyUnit, brokerage_id, unit_id, expected_row_version, payload
    )
    if not updated:
        raise RowVersionConflictError()
    return True


def update_property_unit(
    session: Session, brokerage_id: int, unit_id: int, payload: dict[str, Any]
) -> None:
    """세대 필드만 따로 고친다."""
    expected_row_version = int(payload.pop("row_version"))
    try:
        _require_row_version(session, brokerage_id, unit_id, expected_row_version)
        _update_property_unit(session, brokerage_id, unit_id, expected_row_version, payload)
    except Exception:
        session.rollback()
        raise
    session.commit()


def save_property_unit(
    session: Session,
    brokerage_id: int,
    payload: dict[str, Any],
    unit_id: int | None = None,
) -> int:
    """세대와 인물 관계를 한 트랜잭션에 저장한다. `unit_id`가 없으면 만들고, 있으면 고친다.

    인물은 `property_unit` 열이 아니라 별도 테이블이지만 화면에서는 한 번의 저장이다.
    따로 커밋하면 인물 검증이 실패했을 때 세대만 남는다. 인물 없는 세대 자체는 정상이므로
    데이터가 깨지지는 않지만, 화면은 한 번의 요청이 전부 아니면 전무라고 보고 성공했을 때만
    서버 id와 새 `row_version`을 기록한다. 그래서 세대만 커밋되면 화면은 그 사실을 모른 채
    PATCH는 낡은 버전으로 409를 받고 POST는 같은 세대를 다시 만든다.

    인물만 바뀐 저장도 세대 `row_version`을 올린다. 인물은 별도 테이블이지만 화면에서는
    세대 행의 칸이므로, 올리지 않으면 두 사람이 같은 세대의 임대인을 동시에 고쳐도 충돌이
    잡히지 않고 나중 저장이 앞 변경을 조용히 덮어쓴다. 실제로 바뀐 것이 없으면 올리지 않아
    같은 값을 다시 저장한 화면이 남을 헛되이 충돌시키지 않는다.
    """
    parties = payload.pop("parties", None)
    try:
        if unit_id is None:
            unit_id = _create_property_unit(session, brokerage_id, payload)
            if parties is not None:
                _replace_unit_parties(session, brokerage_id, unit_id, parties)
        else:
            expected_row_version = int(payload.pop("row_version"))
            _require_row_version(session, brokerage_id, unit_id, expected_row_version)
            wrote_unit = _update_property_unit(
                session, brokerage_id, unit_id, expected_row_version, payload
            )
            wrote_parties = (
                _replace_unit_parties(session, brokerage_id, unit_id, parties)
                if parties is not None
                else False
            )
            if wrote_parties and not wrote_unit:
                # 세대 필드가 그대로여서 아직 버전을 올리지 않았다. 조건부 UPDATE로 올리면
                # 같은 세대의 동시 인물 편집이 직렬화되어 나중 저장이 409로 거절된다.
                bumped = repository.bump_row_version(
                    session, PropertyUnit, brokerage_id, unit_id, expected_row_version, {}
                )
                if not bumped:
                    raise RowVersionConflictError()
    except Exception:
        session.rollback()
        raise
    session.commit()
    return unit_id


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
    """부분 수정 요청 중 저장된 값과 실제로 다른 컬럼 이름만 돌려준다."""
    return {key for key, value in payload.items() if getattr(current, key) != value}


def update_property_listing(
    session: Session, brokerage_id: int, listing_id: int, payload: dict[str, Any]
) -> frozenset[str]:
    """매물을 수정하고 실제 변경 필드를 반환한다.

    같은 값을 다시 저장하면 쓰기와 ``row_version`` 증가를 생략한다. 값이 같더라도 요청
    버전이 낡았으면 낙관적 잠금 계약에 따라 충돌로 처리한다.
    """
    expected_row_version = int(payload.pop("row_version"))
    current = repository.find_property_listing(session, brokerage_id, listing_id)
    if current is None:
        raise NotFoundError("property listing is not found")
    if current.row_version != expected_row_version:
        session.rollback()
        raise RowVersionConflictError()

    changed = changed_columns(current, payload)
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
    """구입장을 수정하고 실제 변경 필드를 반환한다.

    희망 단지는 순서가 아닌 집합으로 비교한다. 단지 집합만 바뀌어도 구입장
    ``row_version``을 올려 낙관적 잠금과 F3 입력 버전을 함께 갱신한다.
    """
    expected_row_version = int(payload.pop("row_version"))
    current, _party = require_property_requirement(session, brokerage_id, requirement_id)
    if current.row_version != expected_row_version:
        session.rollback()
        raise RowVersionConflictError()

    has_complex_change = "desired_complex_ids" in payload
    desired_complex_ids = payload.pop("desired_complex_ids", None)
    changed = changed_columns(current, payload)
    if has_complex_change:
        validate_complex_ids(session, brokerage_id, desired_complex_ids or [])
        stored_complex_ids = {
            link.complex_id
            for link, _ in repository.list_requirement_complexes(
                session, brokerage_id, requirement_id
            )
        }
        if stored_complex_ids != set(desired_complex_ids or []):
            changed.add("desired_complex_ids")

    if not changed:
        session.commit()
        return frozenset()

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
