"""단지 등록과 삭제 경로의 HTTP 계약 검증.

여기서 확인하는 것은 서비스 동작이 아니라 공개 계약이다. 경로, `row_version` 쿼리 입력,
인증·CSRF 적용, 201·204 응답, 그리고 409와 COMPLEX_HAS_UNITS 오류 본문이 대상이다.
서비스 계층 동작은 tests/integration/test_property_ledger_delete.py가 따로 본다.
"""

from __future__ import annotations

from ledger_fixtures import create_complex, create_unit, ledger_client, requires_database
from sqlalchemy import text
from sqlmodel import Session

from core.config import Config

# HTTP 헤더 값은 ASCII만 담는다. 실제 발급 토큰도 ASCII다.
CSRF_TOKEN = "csrf-contract-test-token"
WRONG_CSRF_TOKEN = "csrf-some-other-token"


def consented_party(session: Session, brokerage_id: int, user_id: int, name: str) -> int:
    return session.execute(
        text(
            "INSERT INTO party (brokerage_id, party_type, name, privacy_consent_at,"
            " privacy_consent_by) VALUES (:b, 'PERSON', :n, now(), :u) RETURNING id"
        ),
        {"b": brokerage_id, "n": name, "u": user_id},
    ).scalar_one()


@requires_database
def test_complex_is_created_and_then_deleted_through_http(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        created = client.post("/api/v1/property-complexes", json={"name": "계약검증단지"})

        assert created.status_code == 201, created.text
        body = created.json()
        assert body["name"] == "계약검증단지"
        assert body["property_type"] == "APARTMENT"
        assert body["row_version"] == 1
        complex_id = body["id"]

        listed = client.get("/api/v1/property-complexes").json()
        assert any(item["id"] == complex_id for item in listed["items"])

        deleted = client.delete(
            f"/api/v1/property-complexes/{complex_id}", params={"row_version": 1}
        )

        assert deleted.status_code == 204
        assert deleted.content == b""
        after = client.get("/api/v1/property-complexes").json()
        assert all(item["id"] != complex_id for item in after["items"])


@requires_database
def test_duplicate_complex_name_is_rejected(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        client.post("/api/v1/property-complexes", json={"name": "중복단지"})

        again = client.post("/api/v1/property-complexes", json={"name": "중복단지"})

        assert again.status_code == 422
        assert again.json()["code"] == "VALIDATION_FAILED"


@requires_database
def test_complex_delete_reports_complex_has_units(config: Config) -> None:
    """세대가 남은 단지 삭제는 화면이 사유를 안내할 수 있는 코드로 거절된다."""
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        complex_id = client.post(
            "/api/v1/property-complexes", json={"name": "세대남은단지"}
        ).json()["id"]
        create_unit(client, complex_id, unit_number="101")

        response = client.delete(
            f"/api/v1/property-complexes/{complex_id}", params={"row_version": 1}
        )

        assert response.status_code == 422
        assert response.json()["code"] == "COMPLEX_HAS_UNITS"
        # 거절 뒤에도 단지는 목록에 남아 있어야 한다.
        listed = client.get("/api/v1/property-complexes").json()
        assert any(item["id"] == complex_id for item in listed["items"])


@requires_database
def test_complex_delete_rejects_a_stale_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = client.post("/api/v1/property-complexes", json={"name": "버전단지"}).json()[
            "id"
        ]
        session.execute(
            text("UPDATE property_complex SET row_version = row_version + 1 WHERE id = :c"),
            {"c": complex_id},
        )
        session.commit()

        response = client.delete(
            f"/api/v1/property-complexes/{complex_id}", params={"row_version": 1}
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ROW_VERSION_CONFLICT"


@requires_database
def test_complex_delete_requires_the_row_version_query(config: Config) -> None:
    with ledger_client(config) as (client, _session, _brokerage_id, _user_id):
        complex_id = client.post("/api/v1/property-complexes", json={"name": "쿼리단지"}).json()[
            "id"
        ]

        assert client.delete(f"/api/v1/property-complexes/{complex_id}").status_code == 422
        assert (
            client.delete(
                f"/api/v1/property-complexes/{complex_id}", params={"row_version": 0}
            ).status_code
            == 422
        )


@requires_database
def test_unit_delete_returns_no_content_and_leaves_the_listing(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "세대삭제단지")
        unit = create_unit(client, complex_id, unit_number="101")
        unit_id = unit["unit"]["id"]
        row_version = unit["unit"]["row_version"]

        response = client.delete(
            f"/api/v1/property-units/{unit_id}", params={"row_version": row_version}
        )

        assert response.status_code == 204
        assert client.get("/api/v1/property-units").json()["total"] == 0
        assert client.get(f"/api/v1/property-units/{unit_id}").status_code == 404


@requires_database
def test_listing_under_a_deleted_unit_leaves_every_read_and_write_path(config: Config) -> None:
    """세대가 삭제되면 그 매물 건은 단건 조회 범위에서도 함께 사라진다.

    목록은 세대를 join해서 이미 감췄지만 단건 조회는 매물 행만 봤다. 그래서 화면에 없는
    매물 ID를 직접 넣으면 수정과 상담 로그가 계속 통과했다. 행 자체는 이력으로 남긴다.
    """
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "매물잔존단지")
        unit = create_unit(client, complex_id, unit_number="101")
        listing = client.post(
            f"/api/v1/property-units/{unit['unit']['id']}/listings",
            json={"is_sale_available": True, "sale_price": 2_880_000_000},
        ).json()
        assert (
            client.patch(
                f"/api/v1/property-listings/{listing['id']}",
                json={"row_version": listing["row_version"], "sale_price": 2_700_000_000},
            ).status_code
            == 200
        )

        assert (
            client.delete(
                f"/api/v1/property-units/{unit['unit']['id']}",
                params={"row_version": unit["unit"]["row_version"]},
            ).status_code
            == 204
        )

        patched = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"] + 1, "sale_price": 2_600_000_000},
        )
        assert patched.status_code == 404
        assert patched.json()["code"] == "NOT_FOUND"

        logged = client.post(
            "/api/v1/client-interactions",
            json={"listing_id": listing["id"], "interaction_content": "삭제된 세대 매물 상담"},
        )
        assert logged.status_code == 422
        assert logged.json()["code"] == "VALIDATION_FAILED"

        stored = (
            session.execute(
                text("SELECT is_deleted, sale_price FROM property_listing WHERE id = :i"),
                {"i": listing["id"]},
            )
            .mappings()
            .one()
        )
        assert stored["is_deleted"] is False
        assert stored["sale_price"] == 2_700_000_000


@requires_database
def test_listing_paths_still_work_while_the_unit_is_alive(config: Config) -> None:
    """살아 있는 세대의 매물은 등록·수정·상담 로그가 모두 기존처럼 동작한다."""
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "정상매물단지")
        unit = create_unit(client, complex_id, unit_number="102")
        created = client.post(
            f"/api/v1/property-units/{unit['unit']['id']}/listings",
            json={"is_sale_available": True, "sale_price": 2_880_000_000},
        )
        assert created.status_code == 201, created.text
        listing = created.json()

        patched = client.patch(
            f"/api/v1/property-listings/{listing['id']}",
            json={"row_version": listing["row_version"], "sale_price": 2_700_000_000},
        )
        logged = client.post(
            "/api/v1/client-interactions",
            json={"listing_id": listing["id"], "interaction_content": "정상 매물 상담"},
        )

        assert patched.status_code == 200, patched.text
        assert patched.json()["sale_price"] == 2_700_000_000
        assert logged.status_code == 201, logged.text


@requires_database
def test_unit_delete_rejects_a_stale_row_version(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "세대버전단지")
        unit = create_unit(client, complex_id, unit_number="101")
        unit_id = unit["unit"]["id"]
        client.patch(
            f"/api/v1/property-units/{unit_id}",
            json={"row_version": unit["unit"]["row_version"], "memo": "다른 사람이 먼저 고침"},
        )

        response = client.delete(
            f"/api/v1/property-units/{unit_id}",
            params={"row_version": unit["unit"]["row_version"]},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ROW_VERSION_CONFLICT"
        assert client.get(f"/api/v1/property-units/{unit_id}").status_code == 200


@requires_database
def test_requirement_delete_returns_no_content(config: Config) -> None:
    with ledger_client(config) as (client, session, brokerage_id, user_id):
        party_id = consented_party(session, brokerage_id, user_id, "삭제 계약 손님")
        created = client.post(
            "/api/v1/property-requirements",
            json={"party_id": party_id, "demand_type": "매수"},
        ).json()["requirement"]

        response = client.delete(
            f"/api/v1/property-requirements/{created['id']}",
            params={"row_version": created["row_version"]},
        )

        assert response.status_code == 204
        assert client.get("/api/v1/property-requirements").json()["total"] == 0

        stale = client.delete(
            f"/api/v1/property-requirements/{created['id']}",
            params={"row_version": created["row_version"]},
        )
        # 이미 감춰진 행은 조회되지 않으므로 404다. 삭제가 두 번 성공하지 않는다.
        assert stale.status_code == 404


@requires_database
def test_delete_routes_reject_an_unauthenticated_caller(config: Config) -> None:
    with ledger_client(config, authenticate=False) as (client, _session, _brokerage_id, _user_id):
        for path in (
            "/api/v1/property-complexes/1",
            "/api/v1/property-units/1",
            "/api/v1/property-requirements/1",
        ):
            response = client.delete(path, params={"row_version": 1})

            assert response.status_code == 401, path
            assert response.json()["code"] == "UNAUTHENTICATED"


@requires_database
def test_write_routes_require_a_matching_csrf_token(config: Config) -> None:
    with ledger_client(config, csrf_token=CSRF_TOKEN) as (client, session, brokerage_id, _user_id):
        complex_id = create_complex(client, session, brokerage_id, "CSRF단지")
        session.commit()

        missing = client.delete(
            f"/api/v1/property-complexes/{complex_id}", params={"row_version": 1}
        )
        assert missing.status_code == 403
        assert missing.json()["code"] == "INVALID_CSRF_TOKEN"

        wrong = client.delete(
            f"/api/v1/property-complexes/{complex_id}",
            params={"row_version": 1},
            headers={"X-CSRF-Token": WRONG_CSRF_TOKEN},
        )
        assert wrong.status_code == 403

        accepted = client.delete(
            f"/api/v1/property-complexes/{complex_id}",
            params={"row_version": 1},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert accepted.status_code == 204


@requires_database
def test_complex_creation_requires_a_matching_csrf_token(config: Config) -> None:
    with ledger_client(config, csrf_token=CSRF_TOKEN) as (client, _session, _brokerage_id, _user):
        missing = client.post("/api/v1/property-complexes", json={"name": "CSRF등록단지"})
        assert missing.status_code == 403
        assert missing.json()["code"] == "INVALID_CSRF_TOKEN"

        accepted = client.post(
            "/api/v1/property-complexes",
            json={"name": "CSRF등록단지"},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert accepted.status_code == 201


@requires_database
def test_deleting_another_brokerage_complex_is_reported_as_not_found(config: Config) -> None:
    with ledger_client(config) as (client, session, _brokerage_id, _user_id):
        other_brokerage_id = session.execute(
            text("INSERT INTO brokerage (name) VALUES ('남의 사무소') RETURNING id")
        ).scalar_one()
        other_complex_id = create_complex(client, session, other_brokerage_id, "남의단지")

        response = client.delete(
            f"/api/v1/property-complexes/{other_complex_id}", params={"row_version": 1}
        )

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
