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
| dev 공개 설정 | `environments/dev/configuration.tf` → SSM | 검토한 Terraform 적용 후 앱 재배포 |
| Frontend 공개 배포값 | `environments/dev/delivery.tf` | CodeBuild가 빌드에 주입; `VITE_*`에 비밀 금지 |
| OpenAI·F2 SLLM·STT·general 키 | AWS `ai/provider-api-keys`의 평면 JSON | `secret-rotate` TTY 입력, runtime renderer 주입 |
| F2/general RunPod 키 | RunPod Console Secret | AWS AI Secret과 같은 값을 운영자가 입력; 새 Pod에서 인증 검증 |
| RunPod 운영 API 키 | AWS `runpod/operator-api-key` | 운영 도구만 사용; 앱에 주입하지 않음 |
| GHCR 읽기 credential | AWS `runpod/ghcr-registry`, RunPod Console registry | AWS GPU 호스트와 RunPod가 각자 사용; 앱에 주입하지 않음 |
| DB runtime credential | AWS `backend/runtime-database-url` | 구조화 JSON → API/Worker `DB_URL` |
| DB migration | 개인/Instance Role IAM 인증 | migration 전용 `DB_MIGRATION_URL`; 빈 호환 Secret은 정상 |
| Discord webhook | delivery / observability 전용 AWS Secret | 각각의 Lambda만 사용 |
| F2/general endpoint | 운영자가 갱신하는 SSM endpoint 문서 | API/Worker 환경파일 재생성; Terraform은 값 덮어쓰기 제외 |
| 이미지·Template·registry 등록 | 작업별 SSM control 문서 | `runpod-register*`; 기동 성공을 뜻하지 않음 |
| 선택 cloud·모델·release | SSM `serving/SELECTION` | `ai-configure` 명시 저장, 자동 모델 선택 없음 |
| AWS GPU 프로필 | ignored `gpu-profiles.auto.tfvars.json` | AMI·digest·EBS만; 기동 대상은 별도 capacity 파일 |

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


## F3 자동 판정 배포 설정

공개 dev 설정은 `infra/environments/dev/configuration.tf`의 Backend 환경에서 관리한다.
`F3_AUTO_JUDGMENT_ENABLED=false`, `F3_AUTO_DEBOUNCE_SECONDS=3`,
`F3_AUTO_BATCH_SIZE=20`을 주입하며 자동 판정 활성화는 migration021과 통합 검증 후
검토된 Terraform 변경·앱 재시작으로 반영한다. 이 브랜치의 구현·로컬 검증은 공유 dev
활성화나 배포를 의미하지 않는다. 비활성 Worker 모드는 없으며 Worker 실행 자체가
수동 접수된 작업의 처리를 시작한다.

API·Worker는 같은 image의 별도 컨테이너다. 자동 이벤트 소비와 lease heartbeat는 Worker
컨테이너 내부의 별도 스레드·DB 세션이다. 기존 RDS와 general GPU를 사용하고 SQS나
새 서버를 필수 자원으로 추가하지 않는다. 상시 GPU 전제에서 자동 판정 검토 기준은
추가 임대 시간보다 공유 모델 요청 상한·대기 시간·완료율이다.

F3 DB 전역 실행 슬롯 1개와 후보 생성 최대 5개, 현재 단일 API의 챗봇 제한 1건으로
애플리케이션 general 요청 상한은 6건이다. Worker 서버가 추가되어도 F3 상한은 유지되지만
API를 여러 프로세스·호스트로 늘리면 챗봇 제한도 공유 저장소로 옮겨야 한다. 독립 Worker
배포·SG/IAM·drain·health·부하 검증은 별도 운영 작업이며 현재 함께 배포하는 EC2 구성을
독립 자동 확장이 완료된 구조로 해석하지 않는다.


### 자동 판정 설정의 역할

| 변수 | 기본값·허용 범위 | 의미 |
|---|---|---|
| `F3_AUTO_JUDGMENT_ENABLED` | false; true/false | Worker의 변경 이벤트 소비와 자동 접수만 활성화 |
| `F3_AUTO_DEBOUNCE_SECONDS` | 3초; 0~60 | 사무소의 마지막 변경부터 기다려 연속 수정을 병합 |
| `F3_AUTO_BATCH_SIZE` | 20; 1~100 | 이벤트 확장·재검증 예약·대상 접수의 각 단계 처리 상한 |

ENABLED는 유지한다. 수동 판정 검증 중이거나 자동 접수만 중단해야 할 때 Worker를 계속
가동할 수 있다. `F3_ALLOW_SYNTHETIC_PROTOTYPE`는 Worker의 합성 데이터 실행 허용 조건으로,
자동 접수 여부와 다른 책임이다. 상시 GPU 비용을 절감하기 위한 스위치는 아니다.
false여도 DB trigger는 변경 이벤트를 보존하고 이미 접수된 실행은 계속 처리한다.
설정은 Worker 시작 시 읽으므로 변경 후 Worker를 재시작해야 하며, 실행 중 모델 호출을
즉시 취소하는 스위치는 아니다. BATCH_SIZE는 모델 병렬도나 상위 5개 후보 정책을 바꾸지 않는다.
