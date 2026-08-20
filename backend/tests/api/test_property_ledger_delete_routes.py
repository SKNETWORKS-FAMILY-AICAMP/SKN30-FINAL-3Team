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
