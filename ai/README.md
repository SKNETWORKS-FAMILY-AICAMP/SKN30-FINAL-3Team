# Brokerage AI

Backend와 Worker에서 사용하는 Python 3.13 기반의 프레임워크 중립 AI 라이브러리입니다.
독립된 서버가 아닌 라이브러리 패키지로 동작하며, FastAPI나 DB에 직접 의존하지 않고 주입된 인터페이스(Facade & Capability)를 통해 통신합니다.

---

## 핵심 기능 및 아키텍처

```text
ai/src/brokerage_ai/
├── core/             # 모델 카탈로그, 설정 로더, 공통 예외
├── providers/        # LLM 및 STT 프로바이더 어댑터 (OpenAI, vLLM, Bedrock, faster-whisper)
├── f2/               # F2 음성메모 파이프라인 (전사, 상담 유형 분류, 필드 추출, 근거 검증)
├── f3/               # F3 멀티 에이전트 시스템 (포지션 카드 빌더, LangGraph 협상 그래프, 중개 판정)
└── chatbot/          # 업무 어시스턴트 챗봇 (자연어 질의 파싱, 조건 추출, DTO 변환)
```

### 1. F2 음성 상담 파이프라인 (`brokerage_ai.f2`)

음성 메모 파일로부터 텍스트를 추출하고, 상담 내용을 구조화된 장부 필드 초안으로 변환합니다.

```text
음성 파일 → FasterWhisperTranscriber (STT) → 전사 텍스트
  → ConsultationAnalyzer (LLM) → 상담 유형 분류 & 계약/희망 필드 추출
  → Evidence(원문 근거) 검증 및 Diff 생성 → 중개사 검토용 제안 생성
```

- **Transcriber**: `faster-whisper` 기반 로컬/원격 STT. GPU 서버(RunPod) 또는 로컬 환경 지원.
- **Analyzer**: OpenAI 호환 Provider 또는 파인튜닝된 Qwen 모델(vLLM)을 통해 Pydantic 스키마 기반 구조화 출력 추출.
- **안전성**: AI가 직접 DB를 수정하지 않으며, 추출 근거 문장과 신/구 데이터 Diff를 함께 제공하여 사용자가 승인하도록 설계.

### 2. F3 멀티 에이전트 중개 판단 시스템 (`brokerage_ai.f3`)

양측의 원장 데이터와 상담 로그를 분석하여, 양측의 입장을 대리하는 에이전트 간 협상을 시뮬레이션하고 최선의 중개 판정을 도출합니다.

```text
원장 & 상담 로그 → PositionCardBuilder (양측 포지션 카드 생성)
  → DeterministicCandidateFilter (비즈니스 규칙 1차 필터링)
  → LangGraph Multi-Agent Orchestrator
      ├── Seller Agent (매도인 대리: 가격 방어, 매도 일정, 수리/부속 조건 조율)
      └── Buyer Agent (매수인 대리: 예산 한도, 입주 일정, 대출/수리 요구 조율)
  → Brokerage Arbiter (중개인 판정: 성사 가능성, 전략적 타협안, 리스크 평가)
```

- **포지션 카드 (Position Card)**: 단순 수치 조건 외에 상담 로그에만 존재하는 "유연성", "절대 불가 조건", "숨은 의향"을 구조화.
- **LangGraph 기반 협상 그래프**: 매물 대리인과 매수인 대리인이 상호 요구사항을 교환하고 타협 가능한 범위를 탐색.
- **최종 중개 판정서**: 성사 가능성(`HIGH`, `MEDIUM`, `LOW`), 권장 타협 가격/일정, 주의해야 할 거래 리스크를 도출.

### 3. 업무 어시스턴트 챗봇 (`brokerage_ai.chatbot`)

자연어 질문을 분석하여 장부 조회 조건으로 변환하고 일관된 DTO를 생성합니다.

- 자연어 매물 검색 ("역삼동 30평대 15억 이하 아파트 찾아줘")
- 구입 희망 조건 검색 및 상담 로그 기반 필터링
- Server-Sent Events (SSE)와 연계된 사고 과정 및 스트리밍 지원

---

## 설치

[uv](https://docs.astral.sh/uv/)를 준비한 뒤 의존성을 설치합니다.

```bash
cd ai
uv sync --frozen
```

---

## 환경 설정

AI 설정은 `ai/.env.local`(공개 기본값), `ai/.env.example`(예시), `ai/.env`(개인 API 키 및 override)가 소유합니다.

```bash
cd ai
cp .env.example .env
chmod 600 .env
```

`ai/.env` 주요 설정:

```dotenv
# 범용 LLM 프로바이더 선택 (openai, vllm, bedrock 등)
AI_GENERAL_PROVIDER=openai
AI_GENERAL_MODEL=gpt-5.6-luna
AI_GENERAL_API_KEY=your-api-key-here

# vLLM 또는 RunPod GPU 서빙 환경 사용 시
# AI_GENERAL_PROVIDER=vllm
# AI_GENERAL_BASE_URL=https://your-runpod-endpoint/v1

# F2 Whisper/SLLM 엔드포인트 (선택)
# AI_F2_STT_URL=...
# AI_F2_SLLM_URL=...
```

허용 모델 및 프로바이더 조합은 `src/brokerage_ai/core/model_catalog.py`의 enum을 따릅니다.

---

## 코드 품질 검증 및 테스트

```bash
# 코드 린트 및 자동 포맷팅
uv run --locked --project ai ruff check --fix ai
uv run --locked --project ai ruff format ai

# 정적 타입 검사
uv run --locked --project ai pyright

# 단위 테스트 실행 (Fake Provider를 사용하므로 실제 모델 다운로드 없이 즉시 검증 가능)
uv run --locked --project ai pytest
```
