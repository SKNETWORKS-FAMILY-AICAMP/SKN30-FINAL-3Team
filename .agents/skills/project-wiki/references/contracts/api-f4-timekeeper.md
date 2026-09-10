---
status: 결정
updated: 2026-09-08
---

# F4 Time Keeper HTTP 계약

인증·오류의 공통 규칙은 [API 공통 계약](api-common.md)을 함께 읽는다.

> **[폐기 · 2026-09-08]** 캘린더 통합(여덟 번째 갈래, `event_id`·`title`·`location`)은 캘린더
> 기능 전체 폐기([ADR-0038](../decisions/ADR-0038-remove-calendar-feature.md))로 되돌렸다. 과거
> 계약은 [F4 캘린더 계약](api-f4-calendar.md)에 보존한다.

## F4 Time Keeper 일정 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. 기능 범위와 요구사항 ID의 정본은
[F4 Time Keeper 요구사항](../../../../../docs/requirements/f4/time-keeper.md)이고 여기서는 경로와
의미만 고정한다. Time Keeper는 F1 장부에 이미 있는 날짜 컬럼에서 "언제까지 무엇을 해야 하는가"를 뽑아 한 목록으로 돌려주는 **읽기 전용** 조회다. 새 테이블을
만들지 않고, 장부를 바꾸지 않으며, 모델을 호출하지 않는다. 날짜 계산은 SQL과 순수 함수가 한다
(F3 17장 "만기 보드 → F1", "날짜 계산 → 코드").

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/time-keeper/agenda | 세션 | 기한이 다가온 일정과 할 일을 종류별로 조회 |

상태를 바꾸지 않으므로 CSRF 토큰을 요구하지 않는다. `brokerage_id`는 세션에서만 도출한다.

### 조회 조건

| 질의 변수 | 기본값 | 범위 | 의미 |
|---|---|---|---|
| `within_days` | 90 | 1~730 | 앞으로 며칠까지 볼지. F1-AL-01의 "기본 3개월"을 일수로 옮긴 값 |
| `overdue_days` | 7 | 0~365 | 이미 지난 기한을 며칠까지 함께 볼지. **장부에 날짜가 적힌 종류에만 적용한다** |
| `revalidation_days` | 30 | 1~365 | 매물 접수 후 며칠이면 조건 재확인 대상으로 볼지 |
| `per_category_limit` | 3 | 1~100 | 한 종류에서 실을 최대 건수 |
| `limit` | 50 | 1~500 | 페이지 크기 |
| `offset` | 0 | 0 이상 | 페이지 시작 위치 |

`revalidation_days`·`per_category_limit`의 기본값은 MVP 조정값이며 승인된 요구사항 수치가
아니다. 사무소별 설정 위치는 [미해결 질문](../open-questions.md)에 남긴다.

> **[2026-09-08]** `recontact_days`와 `LISTING_RECONTACT`·`CLIENT_RECONTACT` 종류(F4-TK-04)는
> 사용자 요청으로 계약에서 뺐다. 사유는 별도로 확인되지 않았다.

### 종류 어휘

`category`는 **고정 열거형이 아니다.** 계약과 일정 테이블이 생기면 값이 늘어나므로 클라이언트는
모르는 값을 오류로 다루지 않고 코드를 그대로 표시한다. 장부에서 계산하는 갈래는 다음 다섯 가지다.

| category | 원천 | 성격 |
|---|---|---|
| `TENANCY_EXPIRY` | `property_unit.tenancy_expiry_date` | 저장된 날짜 |
| `CLIENT_TENANCY_EXPIRY` | `property_requirement.current_tenancy_expiry_date` | 저장된 날짜 |
| `REQUEST_EXPIRY` | `property_requirement.request_expiry_date` | 저장된 날짜 |
| `MOVE_IN` | `property_requirement.desired_move_in_date` | 저장된 날짜 |
| `LISTING_REVALIDATION` | `property_listing.received_at` + `revalidation_days` | 주기 규칙 |

주기 규칙으로 만드는 종류에는 `overdue_days` 를 적용하지 않는다. 밀린 확인은 시간이 지난다고
사라지지 않고 오히려 급해지므로 아래쪽 경계를 두지 않는다. 1년 전에 접수한 매물도 목록에 남으며
기한 이른 순 정렬이라 가장 오래 방치된 쪽이 위에 온다. 분량은 `per_category_limit` 이 잡고, 밀린
전체 건수는 `categories` 의 총계가 알린다.

계약 체결일, 계약금·중도금·잔금 지급일, 신고·서류 제출 기한과 명도일은 **대응 데이터가 없어 이
계약에 없다.** 앞의 셋은 계약 테이블(F1-CT-01~03)이 미구현이기 때문이고, 명도일은
`handover_condition`이 "만기후" 같은 자유 문구이지 날짜가 아니기 때문이다. 해당 테이블이 생기면
이 표에 종류를 더한다.

종료된 구입 의뢰(`status <> 'ACTIVE'`)와 내려간 매물(`status <> 'RECEIVED'`)은 제외한다. F1이 상태
값 목록을 확정하지 않았으므로 서버가 신규 저장에 쓰는 기본값만 진행 중으로 본다. F3 후보 추출과
같은 판단이며 값이 확정되면 두 곳을 함께 고친다.

### 응답

```json
{
  "items": [
    {
      "category": "TENANCY_EXPIRY",
      "due_date": "2026-08-31",
      "days_until_due": -3,
      "unit_id": 1,
      "listing_id": null,
      "complex_name": "연희 캐슬",
      "building_number": "101",
      "unit_number": "1",
      "tenancy_status": null,
      "requirement_id": null,
      "demand_type": null,
      "requirement_status": null,
      "assigned_user_id": null,
      "last_contact_at": "2026-08-31T02:27:17.135229Z",
      "contacts": [
        {
          "role": "LANDLORD",
          "is_primary": true,
          "party": {
            "id": 7,
            "party_type": "PERSON",
            "name": "김임대",
            "alternate_name": null,
            "privacy_consent_at": "2026-01-01T00:00:00Z",
            "contacts": [
              {
                "id": 11,
                "contact_method": "PHONE",
                "contact_value": "010-1234-5678",
                "contact_label": null,
                "is_primary": true,
                "contactability_status": "UNKNOWN"
              }
            ]
          }
        }
      ]
    }
  ],
  "categories": [
    { "category": "TENANCY_EXPIRY", "total": 2 }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0,
  "as_of": "2026-09-03",
  "within_days": 90,
  "overdue_days": 7,
  "per_category_limit": 3
}
```

`categories`에는 **창 안에 실제로 있는 종류만** 실린다. 0건인 종류는 행 자체가 없으므로 화면이
해당되는 것만 그린다. `total`과 `categories[].total`은 `per_category_limit`을 적용하기 **전** 건수라
`items`에 실린 수보다 클 수 있고, 그 차이가 곧 화면의 "외 N건"이다.

세대에서 온 행은 구입장 필드가, 구입장에서 온 행은 세대 필드가 null이다. 어느 쪽인지는 `category`가
아니라 `unit_id`·`requirement_id` 중 어느 쪽이 채워졌는지로 정한다. 표시 문자열은 서버가 만들지
않고 장부의 원본 값을 싣는다.

인물 요약은 구입장 목록과 같은 범위다. 목록에서 곧바로 연락으로 넘어가는 화면이 인물마다 상세를
다시 부르지 않게 하려는 것이며, 개인정보 노출 범위는 세션과 중개사무소 경계로 지킨다. 세대 행은
현재 유효한 인물 관계를, 구입장 행은 의뢰 인물 본인을 싣는다.

### 기준일

`as_of`는 서버가 D-day를 계산한 업무일이며 중개사무소 시간대(UTC+09:00)로 정한다. UTC 날짜를 쓰면
한국 시각 오전 9시 이전에 하루가 밀려 `days_until_due`가 전부 어긋난다. 주기 규칙으로 만드는 종류의
`timestamptz` → 날짜 변환도 PostgreSQL에서 같은 시간대로 맞춘다. 브라우저는 자기 시계로 다시 계산하지
않고 서버가 준 `days_until_due`를 그대로 쓴다.

정렬은 `due_date` 오름차순이며 같은 날짜에서는 `category`와 식별자로 안정화한다. 정렬이 흔들리면
페이지를 넘길 때 같은 행이 다시 나오거나 건너뛴다.
