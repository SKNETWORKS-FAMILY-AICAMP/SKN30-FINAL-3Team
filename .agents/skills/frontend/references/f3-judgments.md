---
status: 구현됨
updated: 2026-09-09
---

# F3 저장 판정 조회 화면

기능 범위는 [결과 목록](../../../../docs/requirements/f3/judgment-results-list.md), HTTP 계약은
[확장 설계](../../../../docs/architecture/f3/expansion-contracts.md)를 따른다.

- `features/f3/judgments`가 목록·필터·대상 요약·결과 Drawer·근거 상담 Modal을 소유한다.
  AppShell은 공통 메뉴와 원장 상세 조합만 한다. 새 런타임 코드는 strict TypeScript다.
- PatternFly 6의 DataList, Tabs, Toolbar, Drawer, Modal, FormSelect와 semantic token을 재사용한다.
  단순한 대상별 요약과 가변 후보 내용을 묶는 목록이므로 설치된 core DataList를 사용한다.
  표 라이브러리·테마·라우터·전역 상태 라이브러리는 추가하지 않는다.
- `GET /f3/judgment-results`, `judgment-targets`, 결과 상세만으로 목록과 장부 상세를 연다.
  명시적인 `최신 분석 요청`만 기존 POST를 호출한다. 완료/진행 작업 재사용은 서버가 결정한다.
- 목록은 일괄 GET 10초 간격으로 갱신 가능 여부만 준비하고 `새 목록 적용` 전 행을 재정렬하지 않는다.
  새 revision이 있으면 이전 조회임을 표시한다. 숨김/이탈/원장·근거 모달 중엔 확인을 중단한다. 열린 대상은 최대60초 확인하며 멈춤은 작업 실패·취소가 아니다.
- 탭·필터·페이지·선택은 메모리에 유지한다. URL은 대상 종류·양의 정수 식별자만 담으며
  검색어·표시명·원문은 넣지 않는다. 로그아웃은 URL을 지우고 사용자별 feature key로 이전 상태를 제거한다.
- 원장 이동은 listing ID와 unit ID를 구분한다. API가 제공한 unit과 listing을 함께 확인해
  최신 대표 매물이 다른 경우에도 선택된 매물 건의 상세를 연다. 근거 상담은 현재 원장 범위와
  interaction_id로 정확한 원본만 읽으며 최신 상담으로 대체하지 않는다.
- 미저장 원장 안 결과는 inline이다. 편집 중 다른 장부로 강제 전환하지 않으며 안내 후 목록에서 이동한다.
  원장·근거 Modal을 닫으면 목록 필터와 선택을 복원하고 현재 권한을 다시 확인한다.
- 이전 분석·생성 중·실패·공개 불가를 구분하고 미판정 후보를 기각으로 바꾸지 않는다.
  카드는 기본 접힘이며 기존 피드백은 영구 제외/처리 완료가 아님을 설명한다.
- 만료된 목록/후보 cursor는 같은 값으로 재시도하지 않는다. 첫 페이지로 복귀하고 필터·선택을 유지하며 변경을 안내한다.
- polling 종료 상태는 기존 `isTerminal`을 재사용해 `FAILED_TERMINAL`을 진행 중으로 덮지 않는다.
- API DTO는 런타임 decode한다. 401/403/404에서 해당 결과를 제거하며 HTTP 실패와 Worker 실패는 구분한다.
- `VITE_F3_SOURCE=mock`은 고정 합성 저장 결과를 읽는다. GET은 mock 실행도 생성하지 않는다.

검증 명령과 브라우저 회귀 범위는 [Frontend TESTING](../../../../frontend/TESTING.md)에 기록한다.

실제 API·DB 통합과 모바일 Drawer는 [검증 기록](../../../../docs/architecture/f3/implementation-and-validation.md)을 따른다. F3는 셸의 전체 본문 영역을 사용하며 767px 이하에서는 기존 48px masthead 아래에 결과 패널을 표시한다. 닫기 버튼을 스크롤 중에도 유지하고 React 19의 `inert`에는 boolean을 전달한다.

시드가 사전 적재한 결정적 예시 결과는 Backend의 `is_synthetic_fixture` boolean으로 구분한다.
목록·장부 요약·결과 상세에 `시드 예시 결과`, `실제 모델 추론 결과가 아닙니다.`를 표시하고
해당 건수는 `예시 판정`으로 읽는다. 표시는 이름이나 등급에서 추론하지 않는다. 이전 API의 필드 누락은
false로 호환하며 문자열·숫자·null은 계약 오류로 거절한다. 기존 mock transport의 기본값은 false다.
