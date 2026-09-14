---
status: 결정
updated: 2026-09-08
---

# F4 캘린더 HTTP 계약

인증·오류의 공통 규칙은 [API 공통 계약](api-common.md)을 함께 읽는다. 통합 일정 조회를 변경할 때는 [Time Keeper 계약](api-f4-timekeeper.md)도 확인한다.

## F4 캘린더 일정 계약 (제안)

이 절은 `제안`이며 팀 검토 후 승인될 때 표시를 제거한다. 기능 범위와 요구사항 ID의 정본은
[F4 캘린더 요구사항](../../../../../docs/requirements/f4/calendar.md)이고 여기서는 경로와 의미만
고정한다. 사용자가 캘린더 화면에서 직접 만드는 일정의 CRUD다. 저장은 F4가 소유한
`calendar_event` 테이블이며 F1 장부 테이블과 별개다([ADR-0025](../decisions/ADR-0025-calendar-storage-ownership.md)).
장부와의 연결 컬럼은 없다.

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| GET | /api/v1/calendar/events | 세션 | `from_date`~`to_date`(양끝 포함)의 일정 조회 |
| GET | /api/v1/calendar/events/{event_id} | 세션 | 같은 사무소의 삭제되지 않은 일정 단건 조회. 현재 달 밖의 챗봇 결과도 상세 진입 |
| POST | /api/v1/calendar/events | 세션 + CSRF | 일정 생성, 201 |
| PATCH | /api/v1/calendar/events/{event_id} | 세션 + CSRF | 부분 수정. `row_version` 필수 |
| DELETE | /api/v1/calendar/events/{event_id} | 세션 + CSRF | 소프트 삭제, 204. `row_version` 쿼리 파라미터 필수 |

`row_version`이 일치하지 않으면 409 `ROW_VERSION_CONFLICT`다(장부와 같은 낙관적 잠금 계약).
`GET`의 조회 범위는 최대 366일이며 초과하거나 `to_date`가 `from_date`보다 앞이면 422다.

### 응답

```json
{
  "items": [
    {
      "id": 12,
      "title": "행복아파트 임장",
      "category": "임장",
      "event_date": "2026-09-04",
      "start_time": "14:00:00",
      "end_time": "15:00:00",
      "location": "행복아파트 101동",
      "memo": null,
      "created_by": 3,
      "row_version": 1
    }
  ],
  "from_date": "2026-09-01",
  "to_date": "2026-09-30"
}
```

`category`는 Time Keeper와 같은 이유로 고정 열거형이 아니다. 서버 기본값은 `ETC`이며 화면은 이
값을 직접 보내지 않고 임장·계약·잔금·이사·기타 중에서 고르거나 사용자가 정한 문자열을 그대로
보낸다.

### Time Keeper와의 관계

이 테이블의 일정은 `/time-keeper/agenda`([F4 Time Keeper 일정 계약](api-f4-timekeeper.md)) 응답에도 여덟 번째
갈래로 함께 실린다. 캘린더 화면은 자기 일정을 CRUD 상세(메모·시작/종료 시각 포함)까지 필요하므로
`/calendar/events`로 직접 읽고, Time Keeper 응답 중 캘린더 갈래(`event_id`가 있는 행)는 이미
같은 데이터이므로 겹쳐 그리지 않는다.
