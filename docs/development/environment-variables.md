# 환경변수 관리

변수 의미·허용값·기본값은 각 모듈 config와 `.env.local`/`.env.example`의 **변수 바로 위 주석**이 정본이다.
이번 변경은 [ADR-0034](../../.agents/skills/project-wiki/references/decisions/ADR-0034-module-owned-environment.md)를 따른다.
실제 서비스 기동·추론·클라우드 적용은 이 작업에서 수행하지 않았다.

## 소유권과 파일

| 소유 모듈 | 관리하는 입력 |
|---|---|
| Backend | HTTP, DB, 인증, 세션 정책, 업무 요청 제한, 합성 데이터 opt-in |
| AI | 범용 provider/model/연결/키, F2 SLLM·STT 연결, 호출 제한 |
| Frontend | mock/api 데이터 출처, 공개 API 경로, 개발 proxy, 개발 로그인 표시 |
| Infra | AWS/RunPod 자원, 배포, Secret 원본과 실행 역할별 주입 |

| 파일 | 내용 | Git |
|---|---|---|
| 모듈 `.env.local` | 개발자가 선택하는 팀 공통 공개 기본값 | 추적 |
| 모듈 `.env.example` | 개인 비밀 입력은 빈 값, 고급·선택 override는 주석 처리 | 추적 |
| 모듈 `.env` | 개인 비밀값·의도적인 override만; 권한 600 | 제외 |
| `infra/.env` | CLI 대상 계정·profile; 앱 설정이나 자격증명 원문 제외 | 제외 |
| `infra/local/.env` | Docker 로컬 DB 초기 자격증명; Backend 접속 URL과 별개 | 제외 |

이미 있는 `.env`를 예시로 덮어쓰지 않는다. `.env.local` 전체를 개인 파일에 복제하지 않는다.
모드별 `.env.dev`·`.env.prod` 파일은 만들지 않는다. 값 치환·shell 실행 없이 문자 그대로 읽는다.
local 우선순위는 **process env > 모듈 .env > 모듈 .env.local > 코드 기본값**이다.
Backend·AI의 test/dev/prod는 dotenv를 읽지 않고 주입된 환경만 사용한다.

로컬 API·Worker는 `infra/local/run.py`가 Backend와 AI 파일을 각각 읽어 명시적으로 주입한다.
`just local-*`의 `uv run --locked --project backend`가 Backend 의존성과 로컬 경로의 AI 패키지를 함께 준비한다.
launcher의 `backend/src` 경로 설정은 Backend 실행 모듈을 찾는 용도다.
Backend 앱은 AI 개인 파일을 직접 읽지 않는다. `backend/.env*`에 AI 변수가 있거나
`ai/.env*`에 Backend 변수가 있으면 실행 전에 거부한다. AI 단독 `load_ai_config(local)`은 AI 파일만 읽는다.
Worker에는 F2·embedding 연결/키를 주입하지 않는다. 챗봇을 끈 API에는 범용 키를 주입하지 않는다. 공유 배포 migration에는 DB migration URL만 주입한다.

Backend·AI 변경은 프로세스 재시작, Frontend 변경은 개발 서버 재시작 또는 재빌드가 필요하다.
`VITE_*`는 브라우저 공개값이므로 비밀값 금지. boolean은 true/false로 작성한다.
Backend의 1/0·yes/no·on/off는 읽기 호환을 유지한다. provider/model/log 선택값은 대소문자까지 enum과 같아야 한다.

## 범용 모델 선택

AI의 [model_catalog.py](../../ai/src/brokerage_ai/core/model_catalog.py)가 지원 모델과 provider 조합을 제한한다.
임의 모델명을 입력해 우회할 수 없다. 새 모델은 enum·revision·호환성·예시 주석·테스트를 함께 추가한다.
이는 프로젝트 지원 목록이며 외부 제공자의 전체 모델 목록이나 현재 사용 가능 여부를 뜻하지 않는다.

| AI_GENERAL_PROVIDER | AI_GENERAL_MODEL 허용값 | 연결 |
|---|---|---|
| openai | `gpt-5.6-luna` | `AI_GENERAL_API_KEY`; 공식 URL 기본 제공 |
| vllm | `Qwen/Qwen3.8-27B-FP8`, `Qwen/Qwen3-14B-AWQ`, `Qwen/Qwen3-32B-AWQ`, `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` | `AI_GENERAL_BASE_URL` + `AI_GENERAL_API_KEY` |
| llama_cpp | `unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M` | URL + 키; 기존 비교 프로필 보존, 서버 준비 필요 |
| bedrock | `global.openai.gpt-5.6-luna` | `AI_GENERAL_AWS_REGION` + AWS role; URL·키 입력 금지 |

URL·키가 모두 없는 자체 서버 설정은 미구성이다. 일부만 있으면 오류다. 다른 provider로 자동 우회하지 않는다.
F2는 SLLM/STT URL을 둘 다 설정하거나 둘 다 제거한다. 둘 다 없으면 요청은 503이며,
주소가 설정되어도 서버 정상 기동·인증을 보장하지 않는다. F2 alias는 `sllm`, `stt`, 언어는 `ko`만 허용한다.
새 파인튜닝 모델은 alias를 늘리지 않고 Infra의 별도 release `consultation-v3`으로 구분한다.

모델 환경변수는 **명시 적용할 기본 선택**, DB는 **적용된 capability별 버전과 실행 snapshot**을 소유한다.
파일만 바꿔 기존 DB 모델을 자동 덮어쓰지 않는다. 아래 `local-model` 명령으로 한 capability씩 적용한다.
`POSITION_CARD`, `BROKERAGE_JUDGMENT`, `CHATBOT` 중 하나만 선택하며 다른 capability·기존 실행은 보존한다.
같은 provider에서 capability별로 다른 모델을 적용할 수 있고 DB의 기존 override도 보존된다.
런타임은 선택한 provider 연결만 구성하므로 provider를 바꿀 때는 사용하는 capability의 적용값도 함께 맞춰야 한다.
단일 자체 서버가 여러 모델을 제공하지 않으면 다른 모델을 DB에 선택해도 서빙할 수 없다.

## 개발자가 실행하는 순서

저장소 루트에서 실행한다. 이미 있는 개인 파일은 덮어쓰지 않는다.

```bash
# 최초에만 예시 복사 후 개인 값을 입력한다.
cp backend/.env.example backend/.env
cp ai/.env.example ai/.env
chmod 600 backend/.env ai/.env

# 이름·권한 점검 → 실제 config 타입/enum 점검. DB 접속·모델 호출 없음.
just -f infra/justfile env-doctor
just -f infra/justfile local-config

# 모델 선택 미리보기. 1은 실제 합성 사무소 ID로 바꾼다. DB 접속 없음.
just -f infra/justfile local-model 1 POSITION_CARD

# API/Worker 중지·대기 작업 종료 후, 필요한 capability마다 명시 반영.
just -f infra/justfile local-model 1 POSITION_CARD --apply --workloads-stopped
just -f infra/justfile local-model 1 BROKERAGE_JUDGMENT --apply --workloads-stopped

# 각기 다른 터미널. Worker는 backend/.env의 합성 opt-in true가 필요하다.
just -f infra/justfile local-api
just -f infra/justfile local-worker
```

DB 초기 구성·합성 seed는 [Backend README](../../backend/README.md), Frontend는 `frontend/`에서 `npm run dev`를 따른다.
사용자는 API `/health/ready`, `/docs`와 실제 합성 업무 흐름으로 기동을 확인한다.
공유 dev는 [운영 안내](../../infra/operations/README.md)의 배포/검증 절차를 따른다.
공유 dev 모델 명령은 주입된 환경에서 `python src/model_selection.py`와 `--shared-dev`를 사용한다.
모델 적용은 사무소 잠금·대기/진행 요청 검사 후 새 버전을 추가한다. 운영자가 API/Worker를 중지해야 한다.
기존 실행·카드·장부를 초기화하지 않으며 `--apply`가 없으면 DB에 접속하지 않는다.

## 기존 개인 설정 이전

| 기존 입력 | 처리 |
|---|---|
| APP_OPENAPI_ENABLED | 삭제; APP_ENV local/test만 문서 공개 |
| WORKER_ENABLED | 삭제; Worker 실행 자체가 처리 시작, 중지는 프로세스 종료 |
| WORKER_READY_FILE / WORKER_ID | 삭제; Backend 내부 probe와 자동 ID 사용 |
| AUTH_SESSION_COOKIE_NAME / AUTH_CSRF_COOKIE_NAME | 삭제; 내부 cookie 계약으로 고정 |
| AI_F2_PROVIDER_STATUS | 삭제; URL 쌍 및 Infra endpoint 상태에서 결정 |
| AI_LLM_ENDPOINTS | 삭제; provider/model/base URL/key/region의 명시 입력으로 이전 |
| AI_OPENAI_API_KEY / AI_OPENAI_BASE_URL | 로컬에서 AI_GENERAL_API_KEY / AI_GENERAL_BASE_URL로 변경 |
| backend의 모든 AI_* | ai/.env로 옮기고 backend에서 제거; private 값 자동 복사·삭제 없음 |

삭제된 입력은 config가 오류로 알려 준다. **새 코드가 해당 checkout에 반영된 뒤** `env-doctor`로
이전안을 확인하고 `env-fix`를 실행한다. 원본 checkout에 예전 코드가 남아 있으면 변수명은 먼저 바꾸지 않는다.
`env-fix`는 검증된 옛 이름 변경과 AI·Backend·Frontend·Infra·로컬 DB 개인 파일의 권한 600을 처리한다.
OpenAI 이름은 AI 파일의 `AI_GENERAL_PROVIDER` 선택이 `openai`일 때만 GENERAL 이름으로 이전한다.
이전의 기준은 `.env > .env.local > openai`이며 일시적인 shell provider override를 개인 파일에 반영하지 않는다.
기존 GENERAL 입력과 값이 동일하면 하나로 합치고, **서로 다르면 빈 값이어도 해당 파일을 수정하지 않는다.**
기존 GENERAL 키가 GPU용이라면 OpenAI 키로 추정해서 덮어쓰거나 OpenAI 키를 삭제하면 안 된다.
사용할 Provider를 먼저 정하고 나머지 키는 별도 비밀 저장소에 보존한 뒤 활성 `.env`를 직접 정리한다.
다른 Provider를 선택한 파일에 남은 OpenAI 입력도 자동 삭제하지 않으며, 충돌 안내에는 이름만 표시한다.
로컬은 OpenAI, 공유 dev는 vLLM을 사용한다. 새 코드 반영 후 로컬의 OpenAI/GPU 키 충돌은
`just env-fix --local-provider openai`로 명시 이전할 수 있다(허용값 `openai`만, 내부 `--fix` 필수).
이 옵션은 AI 개인 파일 원본 전체를 같은 디렉터리의 `.env.migration-backup-*`에 권한 600으로
먼저 보존하고, Git ignored 검사를 통과한 경우에만 활성 파일을 원자적으로 교체한다.
기존 GPU 키·주소는 백업에 남기고 `AI_OPENAI_API_KEY`와 선택적인 `AI_OPENAI_BASE_URL`을
GENERAL 이름으로 이전하며 `AI_GENERAL_PROVIDER=openai`를 명시한다. 옛 OpenAI 주소가 없으면
기존 GPU 주소를 제거하여 코드의 OpenAI 기본 주소를 사용한다. OpenAI 키가 없는 경우에는
GPU 키를 추정해서 사용하지 않는다. 중복 선언·여러 줄 값은 먼저 직접 정리해야 한다.
백업은 자동 로딩하지 않으며 별도 비밀 저장소로 옮긴 뒤 필요에 따라 직접 삭제한다.
명령을 다시 실행해도 완료된 이전을 반복하거나 기존 백업을 덮어쓰지 않는다.
모듈 사이 비밀값 이전이나 JSON 의미 변환은 자동 수행하지 않는다. `env-doctor`는 이름·권한 검사이고,
전체 타입·조합은 `local-config`로 확인한다. 어느 명령도 비밀값을 출력하지 않는다.

`CHATBOT_ENABLED`와 개발 인증 flag는 prod 금지·미구성 기능 격리 역할이 있어 유지한다.
`F3_ALLOW_SYNTHETIC_PROTOTYPE`와 `DB_TARGET`은 데이터 사용/DB 혼용 방지 조건이므로 유지한다.
Frontend 인증 표시와 Backend 허용은 서로 다른 소비자이며, 서버 기능 조회 API 추가 없이 통합하지 않는다.

공유 dev 전환은 기존 앱을 중지하고 Terraform 공개 입력 변경과 새 앱 배포를 함께 진행한다.
옛 공개 SSM 이름은 Terraform에서 제거되며, 구버전 앱과 신버전 입력을 혼합하지 않는다.
**현재 AWS Secret 필드는 변경하지 않는다.** renderer가 선택 provider에 따라 OpenAI 저장 키
`AI_OPENAI_API_KEY` 또는 GPU 저장 키 `AI_GENERAL_API_KEY`를 앱의 `AI_GENERAL_API_KEY`로 매핑한다.
Bedrock에는 둘 다 주입하지 않는다. Secret 이름·provider 혼동 시 fallback하지 않는다.
