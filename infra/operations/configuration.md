# 설정 관리 위치

로컬 파일 역할·변수별 주석·추가와 제거 절차는 [환경변수 관리](../../docs/development/environment-variables.md)를 따른다.
이 문서는 클라우드 설정·시크릿의 소유권과 반영 경로를 다룬다.

local에서 값을 합치는 우선순위는 `프로세스 환경변수 > 해당 모듈 .env > .env.local > 코드 기본값`이다.
Backend·AI의 dev/test/prod는 dotenv를 읽지 않는다. F3 opt-in도 같은 로더를 사용한다.
과거 불일치와 수정 결과는 [정리 기록](configuration-audit.md)을 따른다.
로컬 launcher가 Backend와 AI 파일을 각각 검증해 프로세스에 주입한다. 개인 파일을 다른 모듈이나
워크트리로 자동 복사하지 않는다. 개발자 PC의 정리는 `just -f infra/justfile env-fix`로 수행한다.

| 설정 | 정본·입력 위치 | 소비자·반영 방법 |
|---|---|---|
| 로컬 공개 기본값 | 모듈별 추적 `.env.local` | 모듈 프로세스 재시작 |
| 로컬 비밀·개인 override | 모듈별 ignored `.env`, 권한 600 | 해당 모듈만 재시작 |
| dev 공개 설정 | `environments/dev/configuration.tf` → SSM | 검토한 Terraform 적용 후 maintenance 환경 재생성; 범용 모델 값은 공유 선택에서 생성 |
| Frontend 공개 배포값 | `environments/dev/delivery.tf` | CodeBuild가 빌드에 주입; `VITE_*`에 비밀 금지 |
| OpenAI·F2 SLLM·STT·general 키 | AWS `ai/provider-api-keys`의 평면 JSON | `secret-rotate` TTY 입력, runtime renderer 주입 |
| F2/general RunPod 키 | RunPod Console Secret | AWS AI Secret과 같은 값을 운영자가 입력; 새 Pod에서 인증 검증 |
| RunPod 운영 API 키 | AWS `runpod/operator-api-key` | 운영 도구만 사용; 앱에 주입하지 않음 |
| GHCR 읽기 credential | AWS `runpod/ghcr-registry`, RunPod Console registry | AWS GPU 호스트와 RunPod가 각자 사용; 앱에 주입하지 않음 |
| DB runtime credential | AWS `backend/runtime-database-url` | 구조화 JSON → API/Worker `DB_URL` |
| DB migration | 개인/Instance Role IAM 인증 | migration 전용 `DB_MIGRATION_URL`; 빈 호환 Secret은 정상 |
| Discord webhook | delivery / observability 전용 AWS Secret | 각각의 Lambda만 사용 |
| F2/general endpoint | 운영자가 갱신하는 SSM endpoint 문서 | API/Worker 환경파일 재생성; Terraform은 값 덮어쓰기 제외 |
| 이미지·Template·registry 등록 | 작업별 SSM control 문서 | 최초 `runpod-register*`; 이후 통합 시작 계획이 기존 Template 차이를 반영·검증·재등록. 기동 성공과 구분 |
| 선택 cloud·GPU·모델·release·이미지 | SSM `serving/SELECTION` v2 | `ai-select` 명시 저장; 선택 ID·변경자·시각, 자동 모델 선택 없음 |
| 마지막 적용 결과·검증 앱 revision | SSM `serving/APPLIED` | 선택 ID·해시·단계·시각·시도 자원, `application_revision`의 CodeDeploy 배포 ID·revision 해시 |
| 지원 조합·검증 근거 | Git `serving/hardware-profiles.json`, `model-profiles.json`, `published-images.json`, `runpod/releases.json` | 공통 enum과 조합 검증. 새 모델/이미지는 검토한 catalog 변경 필요 |
| 중개사·capability별 모델 이력 | Backend DB `ai_model_config` | 시작 중 목록·전후 비교 후 명시 대상만 새 버전 추가 |
| AWS GPU 기반 프로필 | ignored `gpu-profiles.auto.tfvars.json` | 검토한 AMI·EBS·기존 digest; 통합 시작 입력에서 선택 이미지로 정확히 맞춤 |
| 통합 시작용 Terraform 입력·plan | ignored `serving-selection.auto.tfvars.json`, `dev-serving.tfplan`·metadata | 선택 모델·이미지·생성 대상·maintenance를 공통 계획기로 생성·검증 |

## 선택과 실제 상태의 관계

모든 SSM 경로는 `/skn30-final-3team-dev/` 아래다. `SELECTION`은 희망 구성이고
`APPLIED`는 마지막 실행 결과다. 실제 주소·준비 여부는 기존 endpoint 문서를 읽는다.
선택 성공만으로 endpoint가 준비되거나 DB 모델이 바뀌지 않는다. `dev-status`가 이 상태를 구분한다.
SSM은 최근 parameter 변경 이력을 제공하며 새 장기 감사 저장소·상시 제어 서비스는 추가하지 않는다.

`application_revision`은 `dev-start`의 앱 합성 검증이 통과한 실제 호스트에 성공적으로 설치된
CodeDeploy S3 revision의 근거다. 배포 ID와 version/eTag를 포함한 revision의 해시를 기록하고,
다음 적용 중·실패 기록에도 이전 검증 근거를 보존한다. 새 호스트 복구는 이 근거의 정확한
revision만 사용하며 최신 성공 Pipeline으로 자동 대체하지 않는다. 근거가 없으면 최초 앱 배포가 필요하다.

기존 문서는 읽을 때 정확한 cloud·RunPod GPU ID·release·모델을 보존해 v2로 해석하고,
다음 명시 저장 시 선택 ID·변경자·UTC 시각과 함께 기록한다. 알려지지 않은 GPU·모델을
다른 값으로 대체하지 않는다. AWS의 과거 미사용 RunPod GPU ID는 AWS 하드웨어 profile로 정규화한다.
일반·deep 종료는 선택을 지우지 않는다. 새 운영자 PC도 SSM을 읽고 같은 선택으로 복원한다.

앱의 `general_model_selection`과 AWS GPU의 이미지·생성 대상은 이 선택으로부터 생성한다.
같은 값을 `dev.tfvars`, `TF_VAR_*`, 과거 validation/capacity auto 입력에 다시 지정하지 않는다.
시작 계획이 실제 Terraform 해석값과 선택값을 대조하며 다르면 적용을 막는다.
AWS-only 작업에는 RunPod Template 등록을 요구하지 않는다.

검토한 로컬 계획에는 선택 ID·내용 해시·이미지와 등록 상태를 묶는다. 저장 파일·SSM 선택·
Template이 변경되거나 24시간이 지나면 재계획한다. 한 운영자만 명령을 순차 실행하며
배포·모델 변경·전원 명령을 동시에 실행하지 않는다. `APPLIED` 컨테이너는 Terraform 소유이고,
운영 도구는 그 값만 기록한다. 이 문서는 공유 환경에 해당 Terraform 변경이 적용됐다는 뜻이 아니다.

## 자주 틀리는 이름

| 옛 이름 | 현재 이름 |
|---|---|
| `AI_VLLM_LLM_API_KEY` | `AI_VLLM_SLLM_API_KEY` |
| `AI_VLLM_LLM_BASE_URL` | `AI_VLLM_SLLM_BASE_URL` |
| `VITE_BACKEND_ORIGIN` | `FRONTEND_BACKEND_ORIGIN` |

개인 입력 목록은 각 모듈의 `.env.example`, 공개값 목록은 `.env.local`을 사용한다.
`AI_GENERAL_API_KEY`는 선택 Provider의 키로 `ai/.env`에만 입력한다. 키 하나가 있다는 이유로
endpoint나 DB 활성 모델이 자동 선택되지는 않는다.

## Secret 준비 상태

`AWSCURRENT 존재`는 저장 완료만 의미한다. JSON 필수 필드, RunPod Secret 참조, 등록 digest,
배포 revision, 실제 인증은 별도로 확인한다. `doctor`는 저장·구조·등록을 확인하고,
기동 후 운영자가 `dev-verify`로 실제 합성 요청을 검증한다. 비밀값·접속 URL·키 hash는 결과에 남기지 않는다.

일반 Secret은 수동 회전이며 자동 회전 완료로 표시하지 않는다. F2/general 회전은 공유 Pod가 없는
offline 상태에서 Console과 AWS를 함께 갱신한다. OpenAI 회전은 앱 refresh가 필요하므로 앱 중지 중에는
저장 성공 뒤 refresh 실패가 날 수 있다. 이 경우 값을 다시 회전하지 말고 재배포 후 검증한다.


## 새 입력 계약 배포

구체적 삭제·이전 목록과 enum은 [환경변수 관리](../../docs/development/environment-variables.md)를 따른다.
API/Worker를 중지한 상태에서 새 Terraform 공개 입력과 앱 버전을 함께 배포한다.
기존 AWS AI Secret의 OpenAI/GPU 필드 이름은 유지한다. renderer가 선택 provider에 맞는 키 하나를
앱의 `AI_GENERAL_API_KEY`로 매핑한다. Bedrock은 키를 주입하지 않고 Worker에는 F2/embedding 키를 주입하지 않는다.
이 변경의 Terraform 적용·앱 기동·실제 인증은 아직 수행하지 않았다.
