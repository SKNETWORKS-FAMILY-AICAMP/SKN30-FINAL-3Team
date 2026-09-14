---
status: 사용자 개선 요청에 따른 구현 · 팀 검토 대기
updated: 2026-09-10
---

# ADR-0007: 범용 vLLM 스트리밍 수신과 호출 예산

## 맥락

같은 F3 합성 seed를 로컬에서 실행할 때 RunPod Qwen의 카드 생성이 공통 60초 한도를
넘었다. 비스트리밍 한도를 300초로 늘려도 병렬 후보 중 한 요청이 약 126초에 전송 실패했다.
현재 general 서빙 프로필의 `max_num_seqs=1`에서는 HTTP 연결 후 서버에서 대기하는 시간이 길다.

## 결정

- alias가 있는 범용 vLLM은 SDK Chat Completions stream으로 수신하고, 최종 Pydantic 결과만
  반환한다. HTTP/F3 facade 계약, 모델·프롬프트·thinking 비활성화·판정 규칙은 유지한다.
- 완료 신호 없이 끝난 스트림은 결과로 사용하지 않는다. 취소·시간 초과·읽기 오류에서도
  스트림을 닫고 대기 슬롯을 반환한다. SDK 자동 재시도는 계속 0이다.
- `AI_GENERAL_VLLM_MAX_IN_FLIGHT`는 런타임별 동시 생성 수이며 기본 1이다. HTTP 연결 전에
  대기한다. Backend 후보 작업의 병렬 구성과 성공 카드 저장은 유지한다. 이 제한은 여러
  Worker/API 프로세스 또는 다른 사용자 클라이언트를 합친 전역 GPU 용량 제한이 아니다.
- `AI_GENERAL_REQUEST_TIMEOUT_SECONDS`는 범용 생성의 선택적 한도다. 미설정 시 기존
  `AI_REQUEST_TIMEOUT_SECONDS`를 따른다. 범용 vLLM에서는 로컬 대기와 스트리밍 전체를
  포함한 절대 예산으로 적용하며 토큰을 받을 때마다 갱신하지 않는다.
- 300초 설정은 F3 전체 완료나 HTTP 요청 시간의 보장이 아니다. 카드·판정·repair는 각각
  호출 예산을 사용하고, Frontend 300초 polling 중단 뒤에도 Worker는 실행할 수 있다.
- F2 SLLM/STT·embedding은 공통 한도를 유지한다. 기본 vLLM alias 없는 경로의 전송 방식은
  유지한다. 범용 OpenAI·Bedrock·llama.cpp는 기존 SDK 요청 시간 제한에 별도 값을 사용한다.
- client 재사용 키에 timeout과 전송 방식을 포함해 같은 URL·키여도 서로 다른 호출 한도와
  전송을 분리한다.
- 진단 `latency_ms`는 슬롯 획득 후 Provider 전송·생성 시간이다. 호출자 wall time은 로컬
  대기를 포함한다. 병렬 호출 시간 합계를 전체 실행 시간으로 보고하지 않는다.
- 범용 vLLM 스트리밍은 SDK가 지원하는 기존 HTTPX client를 명시 주입한다. 이 환경의 SDK 3.1 /
  HTTPX2 2.10 조합에서는 SSE 종료 뒤 중첩 body generator 정리 오류가 실제 TCP와 RunPod에서
  재현됐다. 다른 Provider와 기본 F2 vLLM의 전송 방식은 유지한다. SDK가 HTTPX client도 닫는다.
- HTTPX/HTTPX2 스트림 읽기 오류를 안전한 Provider 오류로 변환한다. 기존 잠금
  버전을 직접 의존성으로 명시하며 SDK/HTTP 라이브러리 버전은 바꾸지 않는다.

## 결과와 적용

호출 연결 안정성을 개선하는 변경이며 GPU 토큰 생성 속도 개선을 보장하지 않는다.
현재 Pod의 300초 측정·남은 병목은
[검증 보고서](../../../../../docs/validation/f3-runpod-performance-2026-09-10.md)에 기록한다.
공유 환경 적용에는 AI 설정 주입과 애플리케이션 재시작이 필요하다. GPU/Pod 재시작이나
Terraform 자원 변경은 이 구현에 필요하지 않으며 이번 작업에서 수행하지 않는다.
