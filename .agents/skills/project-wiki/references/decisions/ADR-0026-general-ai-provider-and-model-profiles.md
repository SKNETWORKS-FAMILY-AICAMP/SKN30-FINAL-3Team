---
status: 결정
updated: 2026-09-04
---

# ADR-0026: 범용 AI Provider 정책과 합성 Seed 모델 프로필

- 상태: 부분 대체됨·seed와 Provider runtime 구현, GPU Infra 보류
- 결정일: 2026-09-03
- 부분 대체됨: 환경별 활성 Provider, GPU Infra 우선순위와 IMDSv2 hop limit 조항은
  [ADR-0027](ADR-0027-bedrock-gpt56-luna-dev-poc.md)가 대체
- 부분 대체: [ADR-0008](ADR-0008-dev-demo-runtime-and-delivery.md)의 F3 추론 위치,
  [ADR-0014](ADR-0014-f3-prototype-synthetic-input.md)의 합성 입력 Provider 미승인,
  [ADR-0017](ADR-0017-shared-dev-development-session.md)의 3개 seed 파일·29개 검증 계약
- 관련 계약: [F3 AI 계약](../contracts/f3-ai.md),
  [개인정보 정책](../privacy/policy.md)

## 맥락

F3는 OpenAI API를 사용하지만 향후 기능에서도 공유할 수 있는 범용 생성 모델 실행
경로가 필요하다. F2 dev의 RunPod 커스텀 image와 생명주기는 이미 별도로 구현되어
있으며, F2와 범용 모델을 지금 물리적으로 합치면 다른 배포·장애·VRAM 경계까지 함께
바꾸게 된다.

Qwen 원본 가중치와 Unsloth가 별도로 배포하는 BitsAndBytes·GGUF 양자화본은 같은
모델명으로 묶어서는 안 된다. 재현을 위해 repository·revision·양자화 파일을
별도 provenance로 고정해야 한다.

## 결정

### 환경별 활성 Provider

capability별로 활성 모델은 하나만 선택한다. 자동 fallback과 A/B 트래픽 분배는 사용하지
않는다. 복수 프로필은 비교·재현을 위한 allowlist이며 동시 활성 모델 목록이 아니다.

| 환경 | 활성 경로 | 상태 |
|---|---|---|
| local | OpenAI `gpt-4o-mini` | 현재 개발 기본값 |
| 공유 dev | OpenAI `gpt-4o-mini` | 현재 명시값. GPU endpoint·routing 배포 전 유지 |
| dev GPU POC | llama.cpp + 24GB GPU + Qwen GGUF | 후속 구현의 기본 비교축 |
| dev GPU 비교 | vLLM + 48GB GPU + Qwen BnB 4-bit | 후속 구현의 비교축 |
| prod | 서울 리전 EC2 vLLM | 품질·지연·비용·보안 통과 전 승격 금지 |
| Bedrock | 관리형 범용 Provider | 현재 미구현, 지원 모델·리전 조건 개선 시 재검토 |

Bedrock Custom Model Import는 온디맨드 추론을 제공하지만, 현재 서울 리전을
지원하지 않고 Qwen3.8 아키텍처는 지원 목록에 없다. 따라서 Bedrock IAM 권한과 SDK
runtime은 추가하지 않는다.

F2 dev는 기존 RunPod Pod·Template·release 생명주기를 유지한다. F2와 범용 모델의
GPU EC2 통합 여부는 prod 설계에서만 다시 검토한다.

### 신뢰된 양자화 프로필

합성 seed의 장부·스키마는 공유하고 AI 설정만 다음 정적 프로필로 분리한다.

| 프로필 | Provider | 모델 | endpoint alias |
|---|---|---|---|
| `local-openai` | `openai` | `gpt-4o-mini` | `NULL` |
| `dev-qwen38-vllm-bnb` | `vllm` | `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` | `general-dev-gpu` |
| `dev-qwen38-llamacpp-gguf` | `llama_cpp` | `unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M` | `general-dev-gpu` |

- BnB repository revision은 `8aa5f05d26b7205477066e1449e0af13f762a299`다.
- GGUF repository revision은 `4ca720788d1e01f1bff70c033e0d0028fd02e502`, 선택 파일
  SHA-256은 `322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482`다.
- Qwen 원본은 기반 모델 provenance이고, 실행 artifact는 신뢰하기로 검토한
  Unsloth 양자화 repository·revision·파일이다. 둘을 같은 artifact로 표기하지 않는다.
- 이 artifact는 `신뢰된 제3자 양자화본`으로 분류한다. 이 분류는 원 제작사
  공식 가중치라는 뜻이 아니며, 출처·license·revision·파일 hash를 검토하고 allowlist에
  고정했다는 뜻이다. 품질·안전성 평가 통과를 의미하지 않는다.
- 각 프로필은 `config_key=프로필명`, `config_version=1` 설정을
  `POSITION_CARD`와 `BROKERAGE_JUDGMENT`에 하나씩 만든다.
- 관리 명령은 `--model-profile` allowlist만 받고 임의 SQL 경로·provider·model을
  받지 않는다. 공유 dev wrapper는 `local-openai`를 명시한다.

### AI runtime 계약

- `ProviderKind` 추가 값은 `llama_cpp`다. OpenAI 호환 client를 재사용해도
  `ProviderDiagnostics.provider`는 실제 runtime 종류를 보존한다.
- DB의 provider·model·`endpoint_alias`를 기준으로 endpoint registry에 routing한다.
- llama.cpp에 JSON Schema 제약 출력을 요청하고 반환값을 Pydantic으로 재검증한다.
  계약 위반은 기존 제한 재시도를 거쳐 fail closed 처리한다.
- GPU endpoint와 routing 배포 전에는 두 Qwen 프로필을 공유 dev 활성 설정으로 쓰지 않는다.
- dev POC에는 품질 승격 임계값을 두지 않는다. 다만 API 호환성, JSON Schema·Pydantic
  구조화 출력, OOM, 기동·warm-up 및 비용 smoke test는 완료해야 한다.

### 후속 GPU Infra 계약

- app EC2와 분리된 전용 GPU EC2를 둔다.
- 기본 POC는 `llama.cpp + gpu24`(`g6.2xlarge` 급), context 8K, 동시성 1이다.
- 비교 POC는 `vLLM BnB + gpu48`(`g6e.2xlarge` 급)이다.
  `vLLM BnB + gpu24` 조합은 구성 validation으로 거절한다.
- 모델은 암호화 EBS에 보존하고 컨테이너에 읽기 전용으로 mount한다. 최초 download
  후 start·stop은 같은 cache를 재사용한다.
- host만 AWS role을 사용한다. 컨테이너에 Instance Role을 노출하지 않고 IMDSv2
  hop limit 1을 유지한다.
- GPU EC2는 후속 구현에서 기존 `dev-start` / `dev-stop`에 포함한다.

### prod 승격·생명주기·개인정보 gate

향후 명령 계약은 다음과 같다. 이 ADR은 prod Terraform root나 명령을 아직 구현하지
않는다.

| 명령 | 계약 |
|---|---|
| `prod-apply` | Terraform 전체 apply |
| `prod-start` / `prod-stop` | 중지 가능한 비용 자원의 시작·정지 |
| `prod-destroy` | snapshot 없이 Terraform 전체 destroy |

`prod-destroy` 표기를 사용하며 `prod-destory`는 별칭으로 추가하지 않는다. 실제
데이터가 있는 환경은 보존 의무가 없다는 정책 승인 전에 `prod-destroy`를 실행하지 않는다.

dev는 계속 합성·비식별 데이터만 사용한다. prod의 실제 개인정보는 서울 리전 vLLM
선택만으로 허용되지 않으며 다음이 모두 승인되어야 한다.

- 실제 사용자 인증과 접근 통제
- 브라우저에서 추론 endpoint까지 종단 간 TLS
- 전송·저장 암호화와 최소 권한
- 상담 원문·전체 prompt·모델 원문 응답 비로깅
- 데이터·백업·로그 보존 및 삭제 정책
- 품질·지연·오류·OOM·비용 평가의 prod 통과

prod 보존 기간과 모델 평가 통과 기준은 차단형 미해결 질문으로 남긴다.

## 구현 범위

반영한다.

- 이 ADR·계약·개인정보·운영·미해결 질문 문서
- 합성 장부 seed와 모델 프로필 SQL 분리
- 세 프로필 allowlist, CLI 필수 인자, 30개 검증
- 공유 dev wrapper의 `local-openai` 명시
- `ProviderKind`, AI runtime과 Worker의 provider·`endpoint_alias` exact routing
- llama.cpp JSON Schema 요청·Pydantic 재검증과 실제 Provider diagnostics

반영하지 않는다.

- OpenAI key 강제 renderer 제거와 범용 endpoint 배포 설정 주입
- GPU EC2·EBS·시작·정지 Terraform
- Bedrock IAM·SDK·IMDSv2 hop limit 2
- prod Terraform root와 prod 생명주기 명령

## 근거

- [Unsloth BnB 4-bit](https://huggingface.co/unsloth/Qwen3.8-27B-unsloth-bnb-4bit)
- [Unsloth GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [Amazon Bedrock Custom Model Import](https://docs.aws.amazon.com/bedrock/latest/userguide/model-customization-import-model.html)

## 결과

장부 fixture를 복제하지 않고 세 Provider 구성을 재현할 수 있고 임의 SQL·모델 주입을
막는다. llama.cpp의 OpenAI 호환 API와 JSON Schema 제약을 활용하면 기존 AI 계약을
유지할 수 있지만, runtime·GPU·평가·보안은 seed 프로필 구현만으로 완료된 것이
아니다. Provider runtime과 Worker routing은 구현됐지만 실제 llama.cpp·vLLM GPU endpoint는
아직 배포되지 않았다.
