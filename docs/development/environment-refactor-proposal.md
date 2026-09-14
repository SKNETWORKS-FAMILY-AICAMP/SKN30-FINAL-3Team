# 모듈 책임에 따른 환경변수 축소안

상태: 사용자 요청으로 구현됨. 최종 범위·이전·검증 절차는 [환경변수 관리](environment-variables.md)가 정본이다.
아래는 검토 당시의 제안 기록이다. 최종 구현은 모델 선택을 명시적으로 DB에 버전 반영하며,
서로 다른 provider의 동시 연결과 인증 기능 조회 API는 추가하지 않았다.

## 삭제 또는 내부화

| 현재 입력 | 현재 소비 | 제안 |
|---|---|---|
| `APP_OPENAPI_ENABLED` | Backend가 docs/OpenAPI route 공개 여부 판단 | 환경변수 제거. APP_ENV의 local/test는 공개, dev/prod는 비공개로 결정해 현재 기본 정책 유지 |
| `WORKER_ENABLED` | false일 때 DB readiness만 확인하는 비활성 Worker 유지 | 변수와 비활성 Worker 실행 경로 제거. Worker를 실행하면 처리하고, 필요 없으면 프로세스/컨테이너를 시작하지 않음 |
| `WORKER_READY_FILE` | Worker 기록과 Compose healthcheck가 같은 경로 참조 | 사용자 환경변수 제거. Backend 내부 health 계약으로 이동하고 Compose도 동일 health 명령을 호출 |
| `WORKER_ID` | 미지정 시 host/PID/UUID로 생성 | 환경변수 제거. 내부 자동 생성만 사용; lease 식별 기능은 보존 |
| `AI_F2_PROVIDER_STATUS` | F2 runtime 구성/미구성 분기, dev SSM 상태 변환 | 사람이 쓰는 환경변수 제거. local은 URL 쌍 미설정이면 미구성, 일부만 있으면 오류. dev는 Infra endpoint 상태에서 내부 DTO 생성 |
| `AI_LLM_ENDPOINTS` | 여러 Provider 연결을 등록하는 JSON 주소록 | 일상 입력에서 제거. 범용 Provider·모델·연결 입력으로 대체하고 내부 registry 구성은 AI가 수행 |

F2의 연결 상태와 offline 503 계약은 유지한다. 주소가 있다고 건강한 서버로 간주하지 않고,
실제 연결 실패를 offline/unavailable로 처리한다. Worker는 합성 데이터 opt-in과 DB·Provider
사전 검증을 계속 수행한다. env 줄만 지우고 기존 코드·healthcheck를 남기는 방식으로 변경하지 않는다.

## 모듈별 단일 소유

| 소유자 | 설정 범위 | 제거할 중복 |
|---|---|---|
| Backend | HTTP·인증·DB·업무 요청 제한 | backend env 파일에서 AI Provider·모델·주소·키 선언 제거 |
| AI | 범용 Provider·모델·인증, F2 SLLM/STT 연결, AI 호출 제한 | AI 설정의 정의·공개 기본값·개인 입력은 ai 파일만 소유 |
| Frontend | API 경로·개발 proxy·화면 mock/api 선택 | Worker·AI 상태를 별도 frontend flag로 복제하지 않음 |
| Infra | AWS/RunPod 자원·배포·전원·Secret 원본과 프로세스 주입 | 앱 동작을 결정하는 사용자용 flag와 인프라 생성 조건을 구분 |

로컬 실행 도구를 `infra/local`에 두어 Backend·AI 파일을 각각 읽고 필요한 프로세스에 주입한다.
각 파일 내부 우선순위는 process env > 개인 .env > 공개 .env.local이며, 다른 모듈 파일에 같은 키를
쓰면 덮어쓰기 대신 충돌로 보고한다. Backend 앱은 형제 모듈의 비밀 파일을 직접 읽지 않는다.
AI의 config binder는 DB·AWS SDK·FastAPI를 모르고 주입된 값만 검증한다.
공유 배포는 기존 Secrets Manager/SSM을 Infra가 읽어 같은 입력 계약으로 주입한다.

이는 ADR-0030의 Backend 개인 파일에 AI 키도 입력하던 local 주입 방식을 대체하는 변경이다.
기존 개인 키를 자동 복사·삭제하지 않고 소유 위치 이전을 안내하며 공유 secret 원본 이름과
프로세스 입력 이름은 필요한 경우 Infra에서 명시적으로 매핑한다.

## 범용 LLM 선택

현재는 DB의 사무소·capability별 활성 `ai_model_config`가 Provider·모델을 결정하고,
`AI_LLM_ENDPOINTS`는 접속 가능한 registry를 구성한다. 직접적인 Provider 타입 변수가 없는 이유다.

제안하는 일반 입력은 다음과 같다.

- `AI_GENERAL_PROVIDER`: 일반 개발 선택 openai 또는 vllm. 현재 구현된 Bedrock/llama.cpp 사용 경로는
  이전 계획 없이 삭제하지 않고 선택 계약에 명시적으로 보존한다.
- `AI_GENERAL_MODEL`: 선택한 Provider의 모델 식별자. F2 LoRA release와 별개다.
- `AI_GENERAL_BASE_URL`: vllm/llama.cpp에 필요한 연결 주소. OpenAI 공식 주소는 내부 기본값을 사용하며
  Bedrock은 AWS 리전으로 결정한다.
- `AI_GENERAL_API_KEY`: 선택한 연결의 비밀값. Bedrock에서는 Instance Role을 사용한다.

이 값들을 DB의 기존 활성 설정과 병렬로 추가하면 선택 정본이 둘이 된다. 함께 바꿔야 한다.
권장 방향은 **AI 설정을 신규 실행의 기본 선택 정본**, DB를 적용된 설정 버전·실행별 snapshot의
저장소로 두는 것이다. 기존 실행·카드·평가 이력을 보존하고 진행 중인 실행의 모델을 바꾸지 않는다.
기능별 다른 모델을 허용하는 F3-NF-10을 보존하기 위해 AI 소유 설정의 capability override를 유지하며,
필요 없는 override를 개발자 env 템플릿에 미리 늘어놓지 않는다. 사무소별 기존 active 설정을 자동으로
덮어쓰지 않고 명시적 이전과 충돌 검증을 거친다. env 이름 변경만으로 끝나는 작업이 아니다.

## 추가 축소 기준

- session cookie 이름, Worker polling 간격, 내부 경로처럼 운영자가 변경할 이유가 없는 값은 코드로 이동한다.
- DB pool·timeout·요청 크기처럼 실제 운영 조절점은 Backend/AI 소유를 유지하되 일반 입력과 고급 설정을 구분한다.
- `DB_TARGET` 같은 보호 목적 값은 단순 중복으로 삭제하지 않는다. 제거하려면 개발/테스트/운영 DB 혼용 방지 대체 검증이 먼저 필요하다.
- `F3_ALLOW_SYNTHETIC_PROTOTYPE`는 단순 기능 on/off가 아닌 별도 데이터 사용 허용이므로 보존한다.
- `CHATBOT_ENABLED`는 일반 기능 토글로 필요한지 재검토한다. 현재 prod 금지·모델 미설정 시 F1 장애 격리 역할이 있으므로,
  제거할 때는 내부 가용성 판단·기존 대화 조회·명확한 unavailable 응답으로 대체한다.
- 인증 서버/UI 설정은 공개 기능 조회로 UI를 결정하면 중복 flag를 줄일 수 있다. 이는 HTTP/Frontend 변경도 포함한다.

## 파일과 주석

`.env.local`에는 해당 모듈 개발자가 실제로 선택할 공개 기본값만 둔다. 코드 내부 기본값 전체를 복제하지 않는다.
`.env.example`에는 개인 비밀 입력과 필요한 선택 override만 둔다. 실제 `.env`는 비밀값·의도적인 override만 소유한다.

모든 변수 바로 위에 **목적, 허용값/단위, 기본값, 필요한 조건, 반영 시점**을 개별 주석으로 쓴다.
여러 변수 위에 묶음 설명만 달고 끝내지 않는다. 예시:

```dotenv
# 범용 생성 Provider. openai 또는 vllm을 선택한다(추가 Provider는 연결 안내 참조).
# 기본 openai. F3·챗봇 신규 실행의 기본 선택이며 변경 후 API/Worker 재시작이 필요하다.
AI_GENERAL_PROVIDER=openai

# 선택한 Provider에서 제공하는 범용 모델 ID. F2 LoRA 모델과 무관하다.
# 기본 개발 모델이며 변경 후 API/Worker 재시작과 신규 실행 설정 반영이 필요하다.
AI_GENERAL_MODEL=gpt-5.6-luna
```

## 구현 순서와 검증

1. Worker/OpenAPI/health/ID의 사용자 조절 항목을 제거하고 실행·배포 계약을 함께 수정한다.
2. AI 입력 소유권을 AI로 모으고 local launcher·공유 renderer의 주입을 통일한다.
3. 범용 Provider 선택과 DB 설정 이전 계약을 구현한다. 기존 실행의 재현성과 capability 구분을 검증한다.
4. F2 사람이 입력하는 상태와 범용 JSON 주소록을 내부 구성으로 바꾼다.
5. 각 모듈 env 파일의 개별 주석·README·공통 정책·doctor·제거 변수 검사를 함께 수정한다.

예시 파일 복사뿐 아니라 process env 우선순위, 모듈 중복 금지, Provider별 필수값, 선택 충돌,
API/Worker별 최소 Secret 주입, Worker health, F2 offline, 진행 실행 모델 고정까지 오프라인 검증한다.
실제 기동·추론은 사용자가 수행한다.

근거: [Backend config](../../backend/src/core/config.py), [Worker](../../backend/src/worker.py),
[모델 선택](../../backend/src/domain/agent_execution/repository/model_configs.py),
[AI registry 조립](../../ai/src/brokerage_ai/runtime.py), [Compose health](../../infra/deploy/compose.dev.yml),
[F3 비기능 요구사항](../requirements/f3/trust-nfr-privacy.md).
