---
status: 구현됨
updated: 2026-09-08
---

# ADR-0030: local·dev를 구분한 F2·범용 GPU 운영

> 2026-09-09 부분 대체: 공유 선택·실행 중 GPU 전환·기동 DB 연계는 [ADR-0036](ADR-0036-shared-dev-serving-selection.md)를 따른다. local 경계와 기존 후보 검증 기록은 보존한다.

> 환경변수 입력·주입 계약은 [ADR-0034](ADR-0034-module-owned-environment.md)에서 부분 대체한다.

> 2026-09-08 범용 단일 모델 선택 부분은 [ADR-0032](ADR-0032-general-model-comparison-profiles.md)가 부분 대체한다.


- 상태: 사용자 구현·기반 적용 승인·AWS/RunPod 후보 합성 검증 완료·팀 병합 검토 대기·정식 배포/왕복 검증 미완료
- 승인 경계: 사용자 작업 승인과 작성자 외 팀원의 PR 병합 승인은 별개다. 이 문서는 팀 승인 완료를 주장하지 않는다.
- 부분 대체: ADR-0026·0027의 GPU Infra 보류와 dev 모델 전환 절차,
  ADR-0031의 GPU 한 대 배치. 기존 Provider·모델 provenance·개인정보 계약은 유지한다.
- 대상: 약 10명 부트캠프 팀프로젝트와 취업 포트폴리오. prod 승인이 아니다.

## 환경과 모델

local 범용 모델 기본값은 개인 OpenAI key와 기존 모델이다. Backend는 자신의
`.env.local`·개인 `.env`만 읽고 AI 공개 바인더에 값을 전달한다. AI 단독 실행은 자신의
파일만 읽는다. 우선순위는 `process env > 개인 .env > .env.local > 코드 기본값`이다.
다른 모듈의 개인 파일을 암묵적으로 읽지 않는다.

공유 dev는 `f2`, `general`의 장소를 각각 AWS·RunPod 중 명시 선택한다.
F2는 기존 SLLM release·Whisper 조합을 유지한다. general은 F3의 두 capability와 향후
AI 기능이 공유하는 범용 모델이며 F2와 별도 GPU를 사용한다. Qwen BnB revision은
[ADR-0026](ADR-0026-general-ai-provider-and-model-profiles.md)의 값을 유지한다.
텍스트·구조화 출력, 8K context, 동시 처리 1건부터 검증한다.
실제 검증 전에는 기존 dev DB 활성 모델을 자동으로 변경하지 않는다.

## 연결과 전환

- 앱은 AWS GPU의 VPC 사설 주소 또는 RunPod의 인증된 HTTPS proxy로 접속한다.
- local은 개인 설정으로만 공유 GPU를 선택한다. AWS는 고정 포트 SSM 터널,
  RunPod는 해당 Pod proxy를 사용한다. 연결 도구에는 전원·배포·DB 변경 동작이 없다.
- `general-dev-gpu` alias는 장소 전환 후에도 유지한다. F2의 SLLM·STT 주소는 한 문서로 전환한다.
- F2 endpoint schema v2가 AWS instance identity를 표현하며 기존 RunPod 문서를 읽기 호환한다.
  RunPod 삭제·reconcile은 AWS 소유 endpoint를 변경할 수 없다.
- 대상 GPU 준비·추론 검증 후 앱 정상 종료와 Worker 작업 종료를 확인하고 연결을 바꾼다.
  앱 재시작·합성 smoke 성공 뒤 이전 GPU를 종료한다.
- drain 제한 시간 초과 시 연결 변경과 GPU 삭제를 중단한다. 연결 변경 이후 실패하면
  점검 상태를 유지하고 운영자가 `ai-switch` 또는 `dev-start`로 명시 복구한다.
- 최초 Qwen 활성화는 사무소별 `ai_model_config`만 갱신한다. 장부·실행 이력과 기존 모델
  프로필을 보존하며 전체 seed를 재실행하지 않는다. 대기·진행 작업이 있으면 거부한다.

전체 서비스 점검 시간을 허용한다. 자동 fallback, 상시 예비 GPU, 자체 감시 Lambda와
클라우드 관리 프레임워크를 추가하지 않는다. local과 dev가 GPU 용량을 공유하므로
시연 중 개인 검증 시간은 운영자가 조정한다. GPU가 꺼져도 OpenAI로 자동 우회하지 않는다.

## 적용 조건

[Infra ADR-0022](../../../infra/references/decisions/ADR-0022-dual-cloud-gpu-lifecycle.md)가
전원·캐시·권한을 소유한다. [운영 절차](../../../../../infra/serving/README.md)에서
등록·전환·복구를 수행한다. local 기본 OpenAI, local→AWS/RunPod, 혼합 배치, 양방향 전환과
일반·deep 재시작 검증 전에는 운영 완료로 표시하지 않는다. 합성·비식별 dev 정책을 유지한다.
