# F3를 RunPod 로컬 모델(vLLM)로 돌리는 절차

F3 앵커 카드 생성과 중개 판정을 OpenAI 대신 RunPod GPU에서 직접 띄운 모델로 돌린다.
합성 데이터만 사용한다. API key, Pod 주소, SSH 개인키는 저장소에 기록하지 않는다.

> **먼저 읽는다 — RunPod은 Pod을 켜 둔 시간만큼 계속 과금된다.**
> 모델을 안 부르고 있어도, 노트북을 닫아도, SSH가 끊겨도 GPU 요금은 계속 나간다.
> 작업이 끝나면 **9단계의 Pod 정지**를 반드시 한다. 이 문서에서 제일 중요한 줄이다.

vLLM·RunPod을 처음 쓴다면 이 문서를 위에서부터 순서대로 따라 하면 된다.

---

## 0. 이게 무슨 구조인가

세 줄이면 끝난다.

1. **RunPod** — 시간당 요금을 내고 GPU가 달린 리눅스 머신(Pod)을 빌리는 서비스다.
2. **vLLM** — 그 GPU 위에서 오픈 모델을 띄우고, **OpenAI와 똑같은 모양의 HTTP API**로
   열어 주는 서버다. `/v1/chat/completions`, `/v1/models` 같은 주소를 그대로 제공한다.
3. **그래서 우리 코드는 안 바뀐다** — `ai/src/brokerage_ai/providers/vllm.py`는 OpenAI
   adapter와 거의 같은 코드다. 바라보는 `base_url`만 다르다.

바꾸는 건 두 개뿐이다. **`.env`의 주소 하나**와 **DB의 provider 한 행**.

```
[내 Mac]                                   [RunPod Pod]
Worker ──> 127.0.0.1:8003 ──SSH 터널──> 127.0.0.1:8003 ──> vLLM ──> GPU
```

SSH 터널을 쓰는 이유는 Pod의 HTTP 포트를 인터넷에 공개하지 않기 위해서다. 공개하면
누구나 우리 모델을 부를 수 있다. 터널은 내 Mac의 8003 포트를 Pod의 8003 포트에
연결해 주며, 내 Mac 입장에서는 그냥 로컬 서버처럼 보인다.

---

## 1. Pod 만들기

RunPod 콘솔에서 Pod을 하나 만든다.

| 항목 | 값 | 이유 |
|---|---|---|
| GPU | 48GB급 1장 (A6000, L40S 등) | 32B 모델을 4bit 양자화로 올리는 최소선 |
| Template | PyTorch / CUDA 기본 이미지 | vLLM은 직접 설치한다 |
| Volume | `/workspace` 영속 볼륨 50GB+ | Pod을 껐다 켜도 받아 둔 모델이 남는다 |
| SSH | 활성화 | 터널에 필요하다 |

**SSH 키** — 내 Mac에서 만든 키의 **공개키(`.pub`)만** 그 Pod의
`/root/.ssh/authorized_keys`에 넣는다. 공용 RunPod 계정의 Settings에는 넣지 않는다.
Pod을 지울 때 키도 같이 폐기된다.

```bash
# Mac에서 키가 없다면
ssh-keygen -t ed25519 -f ~/.ssh/runpod_f3 -C "f3-pod"
cat ~/.ssh/runpod_f3.pub    # 이 출력을 Pod의 authorized_keys에 붙여넣는다
```

Pod이 뜨면 콘솔에서 **Pod IP**와 **SSH 포트**를 적어 둔다. 아래에서 계속 쓴다.

---

## 2. Pod 안 환경 준비 (최초 1회)

RunPod 콘솔의 **Web Terminal**을 열고 실행한다. `/workspace` 아래에 만들어야 Pod을
재시작해도 남는다.

```bash
cd /workspace
uv venv --python 3.12 --seed f3-venv
source /workspace/f3-venv/bin/activate
uv pip install vllm --torch-backend=auto
```

5~10분 걸린다. F2용 `f3-venv`가 이미 있으면 그걸 써도 되지만, F3 작업 중에는 F2 서버를
같이 띄우지 않는다 (7단계 참고).

---

## 3. 모델 띄우기

Web Terminal에서 실행한다. **이 터미널을 닫으면 서버가 죽는다.** `tmux`를 쓰면 안전하다.

```bash
source /workspace/f3-venv/bin/activate
vllm serve Qwen/Qwen3-32B-AWQ \
  --host 127.0.0.1 \
  --port 8003 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

옵션이 각각 무슨 뜻인지:

| 옵션 | 뜻 | 왜 이 값인가 |
|---|---|---|
| `Qwen/Qwen3-32B-AWQ` | HuggingFace 모델 ID. 처음 실행할 때 자동으로 내려받는다 | 시작점 제안이다. 확정값이 아니며 8단계에서 후보를 비교해 정한다 |
| `--host 127.0.0.1` | Pod 내부에서만 접속 허용 | 인터넷에 열지 않는다. 우리는 SSH 터널로만 들어간다 |
| `--port 8003` | 서비스 포트 | F2가 8001(sLLM)·8002(STT)를 쓰므로 겹치지 않게 8003을 쓴다 |
| `--max-model-len 32768` | 한 요청에 담을 수 있는 최대 토큰 | 판정 프롬프트는 앵커 카드 1장 + 후보 카드 전량이라 길다. 8단계에서 실측해 조정한다 |
| `--gpu-memory-utilization 0.90` | VRAM 사용 비율 | 이 서버 하나만 쓸 때 값이다. 다른 모델과 같이 띄우면 낮춘다 |
| `--default-chat-template-kwargs` | Qwen3의 thinking 모드를 끈다 | 우리는 구조화된 JSON만 받는다. 사고 과정 출력은 파싱을 깨고 토큰만 쓴다 |

`Application startup complete` 또는 `Uvicorn running on http://127.0.0.1:8003`이 나오면 성공이다.
모델을 처음 받을 때는 수십 GB를 내려받으므로 10~30분 걸릴 수 있다.

---

## 4. SSH 터널 열기

**내 Mac의 새 터미널**에서 실행한다. 이 터미널도 계속 열어 둔다.

```bash
ssh -N -o IdentitiesOnly=yes \
  -i ~/.ssh/runpod_f3 \
  -L 8003:127.0.0.1:8003 \
  root@POD_IP -p POD_SSH_PORT
```

`POD_IP`와 `POD_SSH_PORT`는 1단계에서 적어 둔 값이다.

- `-N` — 명령을 실행하지 않고 터널만 연다. 그래서 **아무 출력도 없는 게 정상**이다.
  프롬프트가 안 돌아오면 잘 연결된 것이다.
- `-L 8003:127.0.0.1:8003` — 내 Mac의 8003을 Pod의 8003으로 연결한다.

터널이 끊기면 아무 경고 없이 조용히 죽는다. F3 실행이 갑자기
`ProviderUnavailableError`로 실패하면 이 터미널부터 확인한다.

---

## 5. 붙었는지 확인

또 다른 Mac 터미널에서:

```bash
curl http://127.0.0.1:8003/v1/models --fail
```

JSON이 나오고 그 안의 `"id"` 값이 보이면 성공이다. **이 `id` 문자열을 그대로 복사해 둔다.**
6단계와 7단계에서 글자 하나 안 틀리게 똑같이 써야 한다.

---

## 6. 애플리케이션 연결 + 구조화 출력 확인

`ai/.env` 파일에 두 줄을 넣는다. 이 파일은 커밋되지 않는다.

```dotenv
AI_F2_PROVIDER_STATUS=offline
AI_VLLM_F3_BASE_URL=http://127.0.0.1:8003/v1
AI_REQUEST_TIMEOUT_SECONDS=300
```

`AI_REQUEST_TIMEOUT_SECONDS`를 반드시 올린다. 팀 기본값 60초는 OpenAI 기준이다. 로컬 32B
모델은 초당 약 30토큰이라 **중개 판정 한 번이 40~70초** 걸린다(후보 3장 41초, 5장 67초 실측).
60초로 두면 판정 단계가 경계에 걸려 **어떤 실행은 되고 어떤 실행은 `ProviderTimeoutError`로
죽는다.** 타임아웃은 재시도 대상이라 60초를 두 번 태우고 `EXECUTION_FAILED`로 끝난다.

`AI_F2_PROVIDER_STATUS=offline`이 왜 필요한가 — 팀 공용 기본값인 `ai/.env.local`이
F2용 vLLM 주소(`AI_VLLM_SLLM_BASE_URL`)를 켜 두고 있다. vLLM 서버 하나는 모델 하나만
서빙하고 우리 코드는 vLLM adapter를 하나만 등록하므로, F2용과 F3용 주소를 동시에 켜면
구성 오류로 막힌다. `ai/.env`가 `.env.local`보다 우선하므로 여기서 F2를 끈다.

`AI_OPENAI_API_KEY`는 **지우지 않는다.** 비교 기준선과 폴백에 쓴다.

이제 **다른 걸 하기 전에 이것부터** 돌린다:

```bash
uv run --project ai python ai/eval/f3/smoke.py <5단계에서 복사한 모델 id>
```

이 스크립트는 합성 사례 1건으로 포지션 카드를 실제로 한 장 만든다. DB도 Worker도 필요 없고
2분 안에 끝난다. `OK model=... latency=...`와 카드 JSON이 나오면 **vLLM 연결과 구조화 출력이
둘 다 된다**는 뜻이고, 나머지는 설정 문제로 좁혀진다.

여기서 실패하면 아래 **오류 표**를 본다. 특히 `ProviderOutputInvalidError`는 모델이 우리
JSON 스키마를 못 지킨 것이라 설정으로 못 고친다.

---

## 7. F3를 vLLM으로 전환

DB의 활성 모델 설정을 바꾼다. Worker는 모델을 하드코딩하지 않고 이 표를 읽는다.

```sql
UPDATE ai_model_config
SET provider = 'vllm', model_name = '<5단계에서 복사한 모델 id>'
WHERE config_key = 'f3-synthetic'
  AND capability IN ('POSITION_CARD', 'BROKERAGE_JUDGMENT')
  AND brokerage_id = (SELECT id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소');
```

Worker를 재시작한다 (`WORKER_ENABLED=true`, `F3_ALLOW_SYNTHETIC_PROTOTYPE=true`).

합성 seed를 다시 적재하면 이 값이 `openai` / `gpt-4o-mini`로 되돌아간다. 적재 후에는
위 UPDATE를 다시 실행한다.

```bash
cd backend && uv run python src/manage.py seed-f3-synthetic --confirm-reset
```

---

## 8. 모델 고르기

3단계의 `Qwen/Qwen3-32B-AWQ`는 **시작점 제안이지 결정이 아니다.** F3 프롬프트는 로컬
모델에 까다롭다. 이유는 셋이다.

1. 규칙이 한국어이고 현업 표기(경신·월환·명도)를 그대로 쓴다.
2. 상담 로그에서 **그대로 잘라낸 문자열**을 인용으로 요구하고, `f3/validation.py`가 실제로
   원문과 대조해 위조를 거절한다. 요약·의역하는 모델은 여기서 계속 떨어진다.
3. JSON 스키마로 표현할 수 없는 교차 규칙이 있다("근거 없으면 마감일은 반드시 null",
   "rank는 1부터 빠짐없이 연속"). 어기면 `providers/repair.py`가 지적을 되먹여 최대
   3회 다시 부른다. 약한 모델은 이 루프를 매번 돌아 지연이 3배가 되고, 3회로도 못 고치면
   실행이 실패한다.

그래서 "붙었다"는 합격 기준이 아니다. 후보를 이렇게 비교한다.

**먼저 기준선을 뜬다.** 후보를 붙이기 전에 `provider='openai'` 상태로 케이스 A~I를 한 번
돌려 결과를 저장한다. 비교 대상이 없으면 로컬 모델이 나쁜지 판단할 수 없다.

후보마다 반복: 3단계 모델 교체 → 6단계 smoke 통과 → 7단계 UPDATE의 `model_name` 교체 →
Worker 재시작 → `F3_합성데이터_케이스별_교차판정_가이드.md`의 케이스 A~I 실행.

| 지표 | 어디서 보나 | 합격선 |
|---|---|---|
| 실행 성공률 | run status가 실패로 끝나지 않는가 | A~I 전부 성공 |
| repair 재시도 | Worker 로그에서 되먹임 횟수 | 대부분 0회, 최대 1회 |
| 인용 위조 | quote 대조가 거절한 건수 | 0건 |
| 판정 일치도 | 케이스 가이드의 기대 등급·순위·기각 사유와 대조 | 기준선과 동등 이상 |

후보 순서 제안: `Qwen/Qwen3-32B-AWQ` → `Qwen/Qwen3-14B` → 한국어 특화 모델.
`Qwen/Qwen3-4B`는 2번 인용 정확도에서 떨어질 가능성이 높지만, 하한이 어디인지 재는
용도로는 값이 있다.

**`--max-model-len`은 실측해서 정한다.** 판정 프롬프트는 앵커 카드 1장 + 후보 카드 전량이라
대량 케이스(F~I)가 상한을 만든다. 넘기면 vLLM이 400을 돌려주고 이건 되먹임으로 못 고치는
실행 실패다. 가장 큰 케이스의 토큰 수를 재고 여유 2배를 잡는다. F3는 출력 토큰 상한을
따로 두지 않으므로 남은 컨텍스트가 전부 출력 예산이 된다.

---

## 9. 끝났으면 Pod을 정지한다

**작업이 끝나면 RunPod 콘솔에서 Pod을 Stop 또는 Terminate 한다.**

- **Stop** — GPU 요금은 멈추고 `/workspace` 볼륨 요금만 남는다. 내일 또 쓸 거면 이것.
- **Terminate** — 전부 삭제된다. 받아 둔 모델도 사라진다. 당분간 안 쓸 거면 이것.

터미널을 닫는 것, SSH 터널을 끊는 것, 노트북을 덮는 것은 **Pod을 끄지 않는다.**
콘솔에서 직접 꺼야 한다. 이걸 잊는 게 이 작업에서 가장 흔하고 가장 비싼 실수다.

OpenAI로 되돌리려면 7단계 UPDATE를 `'openai'`, `'gpt-4o-mini'`로 다시 실행하고 Worker를
재시작한다. `ai/.env`의 `AI_VLLM_F3_BASE_URL` 줄은 지우거나 주석 처리한다.

---

## 자주 나는 오류

| 증상 | 원인 | 조치 |
|---|---|---|
| `curl`이 `Connection refused` | 터널이 안 열렸거나 vLLM이 아직 로딩 중 | 4단계 터미널 확인, Pod 터미널에서 `Application startup complete` 확인 |
| smoke가 `ProviderConfigurationError: ...cannot both be configured` | F2용과 F3용 vLLM 주소가 동시에 켜짐 | `ai/.env`에 `AI_F2_PROVIDER_STATUS=offline` 추가 |
| smoke가 `ProviderConfigurationError: vllm LLM endpoint is not configured` | `AI_VLLM_F3_BASE_URL` 없음 | 6단계 `.env` 확인 |
| smoke가 `ProviderUnavailableError` | 터널이 죽었거나 vLLM이 안 떠 있음 | 4단계 터미널이 살아 있는지, 5단계 `curl`이 되는지 |
| smoke가 `NotFoundError` / `model not found` | `model_name`이 `/v1/models`의 `id`와 다름 | 5단계 출력을 그대로 복사 |
| smoke가 `ProviderOutputInvalidError` | 모델이 우리 JSON 스키마를 못 지킴 | 아래 **구조화 출력** 항목 |
| Worker가 `the configured AI provider is not available` | DB `provider` 값 오타이거나 `.env` 누락 | `provider`가 정확히 `vllm`인지, 6단계 `.env`가 맞는지 |
| Worker가 `WORKER_ENABLED=true requires at least one configured LLM provider` | vLLM 주소도 OpenAI key도 없음 | 6단계 `.env` 확인 |
| vLLM이 `No available memory for the cache blocks` | VRAM 부족 | `--gpu-memory-utilization`을 낮추거나 `--max-model-len`을 줄이거나 더 큰 GPU |
| 실행이 400 / `maximum context length` | 프롬프트가 `--max-model-len` 초과 | 8단계의 실측대로 값을 올린다 |
| **중개 판정에서 오래 걸리다 `EXECUTION_FAILED`** | **`AI_REQUEST_TIMEOUT_SECONDS=60`이 판정 생성 시간보다 짧다** | **`ai/.env`에 `AI_REQUEST_TIMEOUT_SECONDS=300`** |
| 어떤 실행은 되고 어떤 실행은 실패 | 후보 수에 따라 판정 시간이 60초 경계를 오간다 | 위와 같다 |

### 구조화 출력이 안 될 때

우리는 pydantic 스키마를 그대로 `chat.completions.parse`에 넘기고, SDK가 이를 strict JSON
schema로 바꿔 vLLM에 보낸다. F3 스키마는 중첩 `$ref`, 배열, `null` 허용 필드, enum을 전부
쓴다. vLLM의 기본 구조화 출력 백엔드(xgrammar)가 이런 스키마를 거절하는 경우가 있다.

백엔드를 바꿔 다시 띄운다. vLLM 버전에 따라 옵션 이름이 다르므로
`vllm serve --help | grep -i structur` 로 확인한다.

```bash
# 최신 vLLM
vllm serve <모델> ... --structured-outputs-config '{"backend":"guidance"}'

# 구버전 vLLM
vllm serve <모델> ... --guided-decoding-backend outlines
```

그래도 안 되면 그 모델은 후보에서 뺀다. 프롬프트로 고칠 수 있는 실패가 아니다.
통과한 조합을 찾으면 이 문서에 적어 둔다.
