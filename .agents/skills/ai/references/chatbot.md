---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 내부 실행과 평가

공개 실행 경계와 저장·권한 계약은 [챗봇 실행 구조](../../../../docs/architecture/chatbot/runtime.md)가
정본이다. AI 구현은 `brokerage_ai.chatbot`의 선형 workflow이며 LangGraph·DB·HTTP를 추가하지 않는다.

- 모델은 제한된 의도·원문 조건만 생성하고 Backend가 주입한 read port가 다시 검증한다.
- 질문 하나는 모델 생성 최대 3회와 주 조회 1회, 전체 60초 안에서 처리한다. 전송 오류는 재생성하지
  않으며 계약 오류의 고정 규칙만 되먹인다. 최종 답변은 검증된 Backend 결과 또는 고정 안내다.
- 8K 문맥에서 UTF-8 byte 보수 상한, JSON Schema, 메시지 여유와 출력 1,024 token을 합산한다.
  초과 문맥을 조용히 자르지 않는다. Provider가 보고한 실제 출력·총 토큰도 검사한다.
- 문맥은 현재 조건과 Backend가 선정한 완료 2쌍의 최소 요약이다. 결과 행·대상 ID는 모델에 보내지
  않는다. 직전 명확화에 대한 답변은 해당 질문의 표현을 복원할 수 있다.
- 이전 unsupported 질문과 차단 패턴은 후속 프롬프트에서 제외한다. 연락처·이메일 등 보조 마스킹은
  개인정보 전송 승인을 대신하지 않는다. Backend의 최소 입력 구성과 합성 환경 경계를 유지한다.
- OpenAI Luna에는 미지원 `temperature`를 보내지 않는다. self-hosted에는 0을 사용한다. 모델과
  capability route는 호출자가 명시하며 자동 fallback은 없다.

평가 절차와 실제 실행 근거는 [AI 평가 README](../../../../ai/eval/chatbot/README.md) 및 그 결과 링크를
읽는다. 모델 해석 평가와 DB/API/브라우저 평가의 범위를 섞지 않는다. Qwen은 사용자 지시에 따라
NOT_RUN이며 endpoint 기동이나 GPU 생성은 평가기의 책임이 아니다.
