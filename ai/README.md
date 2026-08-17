# Brokerage AI

Python 3.13과 uv를 사용하는 AI 라이브러리다. 모델 제공자, 구조화 출력, 임베딩과
향후 AI 워크플로를 소유하며 DB, FastAPI와 Backend repository를 알지 않는다.

## 구성

~~~text
ai/
├── src/brokerage_ai/
│   ├── core/          # 설정, 공통 오류와 Provider 중립 DTO
│   ├── providers/     # Provider port, registry, OpenAI·vLLM adapter
│   └── runtime.py     # 설정을 runtime으로 조립하고 client 수명주기 관리
├── tests/
├── .env.example
├── .env.local
├── .env.prod
├── pyproject.toml
└── uv.lock
~~~

src/는 소스 루트이고 brokerage_ai/가 설치·import되는 Python 패키지다. 아직 업무
책임이 없는 workflow, graph, prompt, agent, checkpoint 폴더는 만들지 않는다.

### 폴더와 파일 책임

| 경로 | 책임 |
|---|---|
| `src/brokerage_ai/__init__.py` | Backend가 사용할 안정된 설정·요청·결과·port·runtime factory 공개 |
| `src/brokerage_ai/py.typed` | 설치한 소비자에게 이 패키지가 타입 정보를 제공함을 표시 |
| `src/brokerage_ai/runtime.py` | 검증된 설정으로 adapter와 client를 조립하고 client 재사용·종료 관리 |
| `src/brokerage_ai/core/config.py` | profile dotenv와 프로세스 환경을 DTO에 바인딩하고 URL·timeout·부분 설정 검증 |
| `src/brokerage_ai/core/errors.py` | 설정·timeout·rate limit·일시 장애·거절·응답 오류의 안전한 공통 계층 |
| `src/brokerage_ai/core/types.py` | Provider·route·요청·결과·사용량·진단의 SDK 중립 Pydantic 타입 |
| `src/brokerage_ai/providers/ports.py` | 구조화 생성과 임베딩의 async Protocol |
| `src/brokerage_ai/providers/registry.py` | route의 Provider 종류로 capability adapter 선택 |
| `src/brokerage_ai/providers/openai.py` | OpenAI Responses structured parse와 Embeddings adapter |
| `src/brokerage_ai/providers/vllm.py` | OpenAI-compatible Chat Completions와 독립 embedding endpoint adapter |
| `tests/architecture/` | AI의 Backend·DB 의존 및 Backend의 AI SDK·workflow 의존 차단 |
| `tests/unit/` | 설정, Provider, registry/runtime, LangGraph 최소 compile 검증 |

`src/`만 두고 그 아래에 `config.py` 등을 직접 놓는 구조는 사용하지 않는다. `src/`는
import 패키지가 아니라 소스 탐색 기준이므로, 설치형 library와 충돌 없는 import 이름을 위해
배포 이름 `brokerage-ai`에 대응하는 `brokerage_ai/` 패키지가 필요하다.

## 설치

~~~bash
cd ai
uv sync --frozen
~~~

AI와 Backend는 각각 독립된 pyproject와 lock 파일을 유지한다. Backend는 개발 중
../ai path dependency로 이 패키지를 설치하며, 향후 Backend Worker만 공개 AI feature
facade를 호출한다. Backend API handler는 Provider나 LangGraph를 직접 다루지 않는다.

## 환경 설정

load_ai_config(profile, environ)를 애플리케이션 조립 지점에서 명시적으로 호출한다.
import 시에는 파일이나 프로세스 환경을 읽지 않는다.

설정 우선순위는 다음과 같다.

1. 호출자가 전달한 프로세스 환경변수
2. Git에서 제외된 .env
3. Git에서 관리하는 .env.local 또는 .env.prod

.env.local과 .env.prod에는 endpoint와 timeout 같은 공개 설정만 둔다. API key는
.env.example의 변수 이름을 참고해 로컬 .env 또는 실행 프로세스 환경변수로 주입한다.
구체적인 비밀 저장소와 운영 주입 도구는 Infra 결정이 소유한다.

지원하는 설정은 다음과 같다.

- AI_REQUEST_TIMEOUT_SECONDS
- AI_OPENAI_BASE_URL, AI_OPENAI_API_KEY
- AI_VLLM_LLM_BASE_URL, AI_VLLM_LLM_API_KEY
- AI_VLLM_EMBEDDING_BASE_URL, AI_VLLM_EMBEDDING_API_KEY

OpenAI API key가 없으면 OpenAI adapter는 활성화하지 않는다. vLLM API key는 인증
없는 로컬 endpoint를 위해 선택값이지만, 사용하는 capability의 base URL은 필수다.

## Provider 경계

- OpenAI adapter는 Responses structured parse와 Embeddings API를 사용한다.
- vLLM adapter는 OpenAI-compatible Chat Completions structured parse와 Embeddings API를 사용한다.
- SDK 자동 재시도는 비활성화한다. 향후 Worker 또는 LangGraph가 호출 수와 비용을 추적하며 재시도한다.
- 프롬프트, 응답 원문과 API key는 일반 로그나 예외 메시지에 기록하지 않는다.
- Backend-facing F2/F3 facade와 실제 graph는 첫 workflow 구현에서 추가한다.

## 품질 검사

~~~bash
uv lock --check
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest --cov
uv build
uv run pre-commit run --config .pre-commit-config.yaml --all-files
~~~

자동 테스트는 실제 OpenAI 또는 vLLM endpoint를 호출하지 않으며 API key를 요구하지 않는다.
