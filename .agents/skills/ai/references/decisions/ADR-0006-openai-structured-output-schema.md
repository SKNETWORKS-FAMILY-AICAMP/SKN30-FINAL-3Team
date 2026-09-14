---
status: 결정
updated: 2026-09-09
---

# ADR-0006: OpenAI 전송 스키마를 정규화하고 원본 계약으로 재검증한다

- 상태: 사용자 개선 구현 승인·코드 구현·팀 검토 대기, 실제 Provider 재검증 전
- 결정일: 2026-09-09
- 대체 범위: ADR-0001의 OpenAI Responses structured parse 호출 방식만 대체

## 맥락

로컬 기능 점검에서 F3의 판별 유니온 근거가 만드는 `oneOf`를 OpenAI가
`invalid_json_schema`로 거부했다. 단순 출력 DTO와 SDK parse mock은 실제 전송 스키마를
확인하지 않아 이 문제를 검출하지 못했다. 근거의 필수 필드와 교차 검증을 완화할 이유는 없다.

## 결정

- OpenAI adapter는 Responses `create`에 strict JSON Schema를 전달하고 결과를 원본
  Pydantic DTO로 직접 검증한다. 공개 DTO와 다른 Provider의 스키마는 바꾸지 않는다.
- 설치 SDK의 strict required·additionalProperties·ref 변환을 재사용한다. SDK 내부 helper
  의존은 adapter 내부에 두고 lock 갱신 시 실제 F3 DTO의 MockTransport 검증을 실행한다.
- 서로 다른 discriminator 상수로 구분되는 `oneOf`만 의미가 동일한 `anyOf`로 바꾸고
  discriminator 메타데이터와 전송 불필요 default를 제거한다. 임의 유니온을 완화하지 않는다.
- 거부 응답과 불완전 응답을 먼저 구분한다. JSON·DTO 계약 위반은 기존 재생성 가능 오류로
  유지하며 모델 값이 오류 메시지에 섞이지 않도록 기존 검증 오류 정제기를 사용한다.
- 합성 HTTP 검증은 실제 SDK 직렬화·근거 변형·거부·잘림·원본 DTO 재검증을 확인한다.
  실제 모델 성공률과 유료 Provider 통합 실행을 대신하지 않는다.

공식 지원 스키마: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
