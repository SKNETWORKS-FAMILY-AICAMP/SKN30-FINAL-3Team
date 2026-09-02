---
status: 결정
updated: 2026-09-01
---

# ADR-0013: 개발환경 설정과 비밀값 materialization

- 상태: 부분 대체됨
- 결정일: 2026-08-24
- 대체 범위: [ADR-0003](ADR-0003-dev-storage-database-and-configuration.md)의 수동 비밀값 소유 방식과 [ADR-0011](ADR-0011-dev-delivery-implementation.md)의 runtime 설정·Discord 값 주입 방식
- 상위 결정: [프로젝트 ADR-0015](../../../project-wiki/references/decisions/ADR-0015-environment-configuration-ownership.md)
- 대체 범위: `secrets.auto.tfvars`, Terraform Secret version과 version counter 운영은 [ADR-0018](ADR-0018-runpod-bootstrap-secrets-monitoring.md)에서 대체한다.

## 결정

- Backend·AI의 비민감 운영 설정은 Terraform의 모듈별 중첩 map 한 곳에서 정의하고 Parameter Store resource를 동적으로 생성한다.
- Frontend release 공개값은 Terraform `frontend_build_environment` map에서 CodeBuild 환경변수로 동적 전달한다. API base는 CloudFront 동일 origin의 `/api/v1` 상대 경로를 사용한다.
- release manifest schema는 환경 설정 때문에 확장하지 않는다. Parameter prefix, secret ARN, application port, readiness path와 log group 같은 비민감 배포 메타데이터는 기존 `backend-image.env`에 기록한다.
- 사람이 입력하는 AI provider key와 Discord webhook은 Git에서 제외된 `secrets.auto.tfvars`에 둔다. 입력 변수는 `sensitive`·`ephemeral`, Secrets Manager version 값은 `secret_string_wo`를 사용한다.
- AI secret은 `AI_OPENAI_API_KEY`를 필수로 하고 `AI_*_API_KEY` 형식의 vLLM key를 허용한다. 공유 dev F2에는 `AI_VLLM_SLLM_API_KEY`와 `AI_VLLM_STT_API_KEY`도 필요하며 endpoint가 offline인 동안은 주입되더라도 F2 client를 만들지 않는다. Discord secret은 webhook URL 문자열을 저장한다. 값을 바꿀 때 각 독립 version counter도 증가시킨다.
- RDS master secret, Backend runtime DB credential과 migration IAM token의 기존 자동 생성·운영 경계는 유지한다.
- 배포 renderer는 SSM의 `backend/<ENV_NAME>`·`ai/<ENV_NAME>` 구조와 일반 환경변수 이름 규칙을 검사한다. 변수별 allowlist는 만들지 않고 DB URL, AWS 예약 이름과 비밀형 suffix를 공개 설정에서 거부한다.
- renderer는 root 전용 config directory에 API, Worker, Migration 환경파일을 각각 원자적으로 `0600` 생성한다. Compose `v2.35.1`의 `env_file.format=raw`로 읽어 `$`, `#` 등을 재해석하지 않는다. Backend 설정과 비민감 AI Provider endpoint·timeout은 API·Worker 파일에 둔다. F2가 동기 실행되는 API 파일에는 vLLM LLM·STT key만, Worker 파일에는 전체 AI Provider key를 둔다. runtime DB URL은 API·Worker에만, IAM migration URL은 Migration 파일에만 둔다.
- `BeforeInstall`은 분리 이전의 `/opt/brokerage/config/runtime.env` 파일만 제거해 stale DB credential이 host에 남지 않게 한다.
- application port와 readiness path는 Terraform 정본에서 ALB·security group·배포 metadata·admission 및 Frontend deploy 검증으로 전달한다.
- 애플리케이션은 AWS 설정 저장소에 직접 접근하지 않고 전달된 프로세스 환경변수만 읽는다.

## 운영 규칙

- `secrets.example.tfvars`를 `secrets.auto.tfvars`로 복사해 실제 값을 입력한다. 이 파일은 비어 있지 않은 일반 파일이어야 하고 group/other 권한 bit가 모두 꺼져 있어야 하며, plan과 saved-plan apply 양쪽에서 같은 working directory에 있어야 한다.
- Ephemeral 값은 plan에 저장되지 않아 apply 때 다시 읽힌다. 승인된 plan과 apply 사이에는 파일의 비밀값이나 version counter를 변경하지 않는다.
- plan/state와 `terraform show -json`에서 비밀 평문이 없는지 확인하고 사람 승인 전에는 apply하지 않는다.

## 결과

- 공개 설정과 Frontend build 설정은 각각 Terraform map 한 곳만 변경하면 배포 경로에 반영된다.
- 수동 비밀값도 Terraform apply 흐름으로 일관되게 반영되지만 평문은 plan/state에 남지 않는다.
- API·Worker·Migration의 최소 환경변수 집합이 분리되고 환경 설정 전용 JSON 계약은 추가되지 않는다.
