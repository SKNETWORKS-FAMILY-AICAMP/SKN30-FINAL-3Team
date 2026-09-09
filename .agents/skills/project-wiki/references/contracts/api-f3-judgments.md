---
status: 구현됨
updated: 2026-09-09
---

# F3 저장 결과 조회 계약

[실행·피드백 API](api-f3.md)와 [API 공통](api-common.md)을 함께 적용한다.
이 구현은 사용자 1차 확장 요청에 따른 작업 브랜치 기준이며 공유 dev 배포 완료를 뜻하지 않는다.

| Method | `/api/v1/f3` 아래 경로 | 의미 |
|---|---|---|
| GET | `/judgment-results` | 사무소의 앵커별 최신 성공과 현재 생성 상태, 서버 페이지·건수·담당자 옵션 |
| GET | `/judgment-targets/{anchor_type}/{anchor_id}` | 유효 대상의 현재성·적격성·결과/실행 참조. 미생성도200 |
| GET | `/judgment-results/{result_id}` | 완료된 match_evaluation.id의 과거 snapshot·후보·선택 후보 카드/근거/기록 |

모든 조회는 세션 필수·CSRF 불필요·`Cache-Control: no-store`다. 모델 호출·작업 생성·projection 갱신을 하지 않는다.
다른 사무소·삭제 대상·존재하지 않는 결과는404. 형식·범위·만료 cursor는422. 인증없음401.

## 목록

필수 `anchor_type=LISTING|REQUIREMENT`, 선택 `filter`, `trade_type`, `complex_id`, `assignee_id`, `q`, `cursor`, `limit`.
`limit` 기본20/최대100, `q` 최대100자, cursor 최대512자다. 담당자 필터는 기준 대상 담당자다.
이름/단지 검색은 권한 범위의 구조화 표기에 한하며 상담 본문 검색이 아니다.

- `HAS_MATCH`: CURRENT 강함/약함, 기본값.
- `HAS_STRONG`: CURRENT 강함.
- `HAS_UNJUDGED`: 저장된 조건 후보 중 미판정 있음. 최신성은 별도 표시.
- `NEEDS_ATTENTION`: 이전/미생성/비공개/실패/조건 미충족.
- `ALL`: 현재 권한으로 볼 수 있는 대상 전부.

응답은 items·상태필터 전 counts·next_cursor·checked_at·revision·활성 사무소 assignees다.
대상별로 anchor, result_id/run_id, eligibility/reason, content_availability, freshness, generation,
generated_at/meaningful_changed_at, summary, 대표 후보 최대3건을 반환한다.
`is_synthetic_fixture`는 해당 결과가 결정적 시드 예시인지 나타내는 boolean(기본 false)이다.
true이면 화면에 시드 예시·실제 모델 추론 아님을 표시한다. 내부 provenance snapshot은 노출하지 않는다. 전체 DTO 필드는
[공개 schema](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/blob/e785db47492b1680d7cbf0c76bfe3eca45c5c73b/backend/src/api/schemas/f3_judgments.py)가 정의한다.
원장 상세/상담 전문을 목록으로 전수 전달하지 않는다. 이름·단지·현재 조건·담당자는 묶어서 조회한다.

CURRENT/STALE/NONE과 IDLE/QUEUED/RUNNING/FAILED는 독립 축이다. 이전 강함은 최신 추천 건수에서 제외한다.
공개 불가 또는 미생성은 summary=null이며 정상 후보0건으로 집계하지 않는다. 미판정은 기각과 구분한다.
정렬은 의미 있는 결과 변경 시각·앵커 ID 내림차순이다. 결과 내용이 같은 재검증은 시각을 유지한다.
cursor는 필터와 revision에 결합된다. 목록이 변경된 뒤 이전 cursor를 사용하면 `F3_CURSOR_INVALID`이며 첫 페이지를 다시 조회한다.

## 상세·선택 후보·근거

선택 `cursor`, `limit`과 `candidate_id`를 받는다. candidate_id는 해당 결과의 반대편 장부 ID다.
`selected_candidate`를 페이지와 독립 반환하며 미판정의 판정/미생성 카드는 null이다.
result_id는 과거 완료 snapshot, current_result_id는 대상 최신 포인터다. 과거 결과를 최신으로 승격하지 않는다.

본문은 기존 합성 공개 조건과 유효 앵커 카드 검사를 공유한다. 후보도 현재 존재·권한·유효 카드와 로그 측면을 확인한다.
카드·근거에 prompt·진단·모델 원문을 포함하지 않는다. 무효/범위 밖 상담 참조는 근거에서 제거한다.
선택 후보에 일반 상담과 해당 매물/손님 쌍의 기존 피드백을 구분해 읽기 제공한다.
기록 없음은 미연락, ALREADY_CONTACTED는 거래 거절·영구 숨김을 의미하지 않는다.

원본 상담 이동은 기존 `GET /client-interactions`에 `interaction_id` 선택 필터를 추가해 정확히 조회한다.
기존 unit_id/requirement_id/party_id 중 대상 범위를 반드시 함께 지정하며 tenant·무효화 조건과 연결된 부모의 현재 존재·미삭제를 재검사한다.
기존 POST /feedback만 쓰며 새 CRM·연락 완료 API를 만들지 않는다.
