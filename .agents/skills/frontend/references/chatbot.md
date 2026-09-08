---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 화면 상태

기능 정본은 [챗봇 요구사항](../../../../docs/requirements/chatbot/overview-and-scope.md), 화면 정본은 [챗봇 화면](../../../../docs/screen/chatbot.md)이다. 기능은 서버의 `GET /api/v1/chatbot/conversation` 응답 `enabled`로 탐색하며 기본 비활성화 배포를 지원한다.

- 공개 진입점은 `frontend/src/features/chatbot/index.ts`의 `Chatbot`이다. 공통 셸은 `userKey`, `onAction`, `onSessionExpired`, `suspended`로 사용자와 기존 화면 이동·모달 우선순위를 연결한다.
- 사용자별로 controller와 React 화면을 새로 생성한다. 대화·입력 초안·결과·선택은 메모리에만 두며 브라우저 영속 저장소에 기록하지 않는다.
- JSON은 공통 HTTP·CSRF 경계를, 진행 상태는 별도 native EventSource를 사용한다. 재접속·폴링·패널 열기는 GET만 호출하며 질문을 자동으로 재전송하지 않는다.
- 완료·실패·중단 복원에는 대화의 활성 요청 또는 최신 메시지의 요청 상태를 조회한다. revision이 작거나 완료 이후 실행 상태로 돌아가는 이벤트는 버린다.
- 삭제·계정 전환·unmount는 generation과 AbortController로 이전 읽기·SSE 응답을 무효화한다. 삭제 실패 시 이력을 유지하고 관찰을 재개한다.
- 결과 페이지 이동은 서버에서 재조회한다. 순번 참조는 최근 완료 2쌍의 저장된 원래 첫 페이지에서만 선택한다. 재조회된 페이지는 첫 페이지로 돌아와도 개별 상세 버튼만 제공하며, 대화 교체·최근 문맥 만료·페이지 이동 시 참조 선택을 해제한다.
- 패널은 모바일에서도 비차단 영역이다. Escape로 접고 열기 버튼으로 초점을 복원하며 기존 Modal이 열리면 패널을 접는다. 전체 삭제 확인은 PatternFly Modal을 사용한다.

검증: `npm run test:chatbot`, `npm run test:chatbot:browser`, `npm run typecheck`, `npm run build`. 브라우저 검증은 합성 HTTP 서버와 실제 SSE를 사용하고 기존 DB·모델에 접근하지 않는다.
