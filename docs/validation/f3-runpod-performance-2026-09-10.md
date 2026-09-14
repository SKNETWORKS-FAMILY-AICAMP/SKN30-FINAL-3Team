# F3 RunPod 로컬 시드 실측과 호출 안정성 개선

**재개 상태:** 사용자 요청에 따라 미커밋 작업을 다시 점검했다. 전용 loopback PostgreSQL에
빈 migration을 적용하고 F3 lease·선점·카드·판정 회귀를 다시 실행했다. 공유 RunPod 및 dev에는
적용하지 않았고, 이 작업의 새 PR도 생성하지 않았다.

실제 실행 중인 RunPod `g0n8ikzxy0p42g`에 로컬 Worker 코드로 호출했다. 시드 L1은 기존
60초 한도에서 실패했고, 300초 비스트리밍도 후보 전송 중 실패했다. 스트리밍·로컬 대기·300초
호출 예산을 함께 적용한 뒤 L1 전체 판정은 431.22초에 완료됐다. 연결 안정성은 확인했지만
GPU 생성 속도 또는 5초 최종 완료 목표를 달성한 결과는 아니다.

## 범위와 환경

| 항목 | 내용 |
|---|---|
| 기준 | 원격 dev `589b1b4`, 별도 `fix/f3-runpod-performance` 워크트리 |
| RunPod 모델 | `Qwen/Qwen3.8-27B-FP8`, revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a` |
| 런타임 | vLLM 0.28.0, max_model_len 8192, max_num_seqs 1, enforce-eager |
| 확인한 장치 상태 | GPU 1개, 총 46068 MiB / 사용 39099 MiB; 등록 프로필 L40S 48GB |
| 비교 모델 | 개인 OpenAI 연결의 `gpt-5.6-luna` |
| 입력 | `docs/db/seed/002_F3_SYNTHETIC_SEED.sql`의 L1(매물, 후보 3), R1(구입장, 후보 2) |
| DB | loopback 55449의 전용 PostgreSQL 15.18/pgvector 0.8.6, tmpfs 데이터 디렉터리 |
| 실행 | 실제 intake → claim → Worker 단계 → DB 저장 → 결과 조립; HTTP 브라우저 표시 시간 제외 |
| 표본 | 각 모델·앵커·캐시 조건별 1회. p50/p95나 통계적 속도 개선율을 주장하지 않음 |

등록된 general endpoint와 API key는 기존 Infra의 AWS 역할·Parameter Store·Secret 조회
경로를 통해 메모리로 주입했다. URL·인증 헤더·키·상담/모델 원문은 산출물에 없다.
개인 설정 파일을 복사하지 않았다. 서비스 Pod 설정, Worker 수, 모델/프롬프트/repair 횟수,
상위 후보 수와 판정 알고리즘은 바꾸지 않았다. 시드 적용 때마다 정본의 30개 검사를 통과했다.
시드 이후 공개 모델 선택 유스케이스로 두 capability를 실제 연결 모델에 맞췄다.
시드 파일 SHA-256은 `d73625222977feb5fe721f46a082f4cb02dba3fec784118a3df8080afddaf5e9`다.

서빙 이미지는 등록과 `/ops/status`에서 다음 digest를 확인했다.
`ghcr.io/sknetworks-family-aicamp/skn30-final-3team/general-serving@sha256:7d9598e8b8263fd5b43adb19cb778832c8f5189d8c6a2b4ba81eac3a06ceeb08`.

## 실측

| 연결·처리 방식 | 매물 cold | 매물 warm | 구입장 cold | 구입장 warm |
|---|---:|---:|---:|---:|
| Luna, 기존 호출 | 52.70초 완료 | 17.57초 완료 | 43.77초 완료 | 13.81초 완료 |
| RunPod, 기존 60초 | 61.04초에 RETRY | 미측정 | 미측정 | 미측정 |
| RunPod, 비스트리밍 300초 | 214.40초에 RETRY | 미측정 | 미측정 | 미측정 |
| RunPod, 스트리밍·대기 300초 | 431.22초 완료 | 150.85초 완료 | 273.05초 완료 | 78.23초 완료 |

`cold`는 기존 카드 캐시를 무효화하고 시작한다. `warm`은 같은 카드 캐시를 사용하되 새 판정을
명시 실행한다. 완료 결과 재사용은 도입하지 않았다. 날짜 기준 시각과 모델 생성 내용은 실행마다
달라질 수 있다. 같은 seed와 코드 계약을 사용하지만 결과 토큰 수가 고정된 벤치마크는 아니다.

RunPod 60초에서는 앵커 호출이 60.92초에 timeout이었다. 비스트리밍 300초에서는 앵커 88.43초,
병렬 후보 53.98초·112.91초 성공 후 남은 후보가 125.61초에 `ProviderUnavailableError`였다.
성공한 두 카드는 보존됐고 실행은 `CANDIDATES_READY`에서 재시도 대기했다. 이 측정의 원래 오류
HTTP status는 수집되지 않아 **524로 확정하지 않는다**.

이 양상은 HTTP proxy의 응답 대기 제한과 일치한다. RunPod 문서는 100초를, 현재 Cloudflare
문서는 기본 125초 Proxy Read Timeout을 설명한다. 두 문서의 숫자가 달라 프록시 실패 원인을
시간만으로 단정할 수 없다. [RunPod HTTP proxy](https://docs.runpod.io/pods/configuration/expose-ports),
[Cloudflare 524](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/).

직접 스트리밍 진단에서는 같은 L1 프롬프트의 첫 본문 토큰이 2.28초, 정상 JSON 완료가
69.93초였다. 입력 1805/출력 997 tokens, 완료 신호 stop, 로컬 schema 검증 통과, 뒤쪽 공백 0.
첫 토큰 이후 생성 속도는 약 14.7 tokens/s다. 무한 공백 출력이 관측된 사례는 아니다.
이 진단은 카드 schema만 검증했으며 전체 F3 교차 검증·저장 결과를 대신하지 않는다.

### 스트림 종료 재검증

위 4조건은 SDK 기본 HTTPX2 전송으로 수집한 생성·저장 완료 시간이다. 마지막 loop 종료에서
비동기 body iterator 정리 경고가 발견됐다. Worker에 `shutdown_asyncgens()`를 추가한 R1 warm
재검증은 79.02초에 완료했으나 HTTPX2의 중첩 generator 종료 오류가 추가로 드러났다.
따라서 이 4조건 표만으로 최종 종료 처리까지 검증됐다고 보지 않는다.

외부 모델을 쓰지 않는 실제 loopback TCP SSE로 재현한 결과 SDK 기본 HTTPX2는 loop 종료 오류가
발생했고, SDK의 기존 HTTPX 전송은 오류가 없었다. 범용 vLLM에만 HTTPX를 명시 주입하고 실제
TCP 회귀 테스트를 추가했다. 최종 HTTPX 전송의 실제 RunPod R1 warm 재확인은 **78.65초**에
완료됐고 프로세스 종료 경고·오류 없이 종료 코드 0을 확인했다. 최종 전송으로 cold와 매물
전체 조합을 반복 측정하지 않았으므로 위 표의 표본과 구분한다. 원자료를 별도 보존했다.
모델·프롬프트·대기 슬롯·호출 예산은 이 종료 보완 과정에서 바꾸지 않았다.

### 개선 후 L1 cold 단계

| 단계 | 실제 경과 시간 |
|---|---:|
| 접수 / Worker 선점까지 | 0.048초 / 0.074초 |
| 앵커 생성·저장 | 111.48초 |
| 후보 선택 | 0.032초 |
| 후보 카드 3건 | 172.68초 |
| 최종 판정·저장 | 146.92초 |
| 전체 | 431.22초 |

후보의 Provider 생성 시간은 54.27 / 64.53 / 53.47초다. 대기를 포함한 호출 wall time은
54.27 / 118.80 / 172.27초다. 병렬 호출 wall time 합계를 전체 경과 시간으로 계산하지 않는다.
최종 판정 단일 스트림은 146.79초에 정상 끝나 125초를 넘는 수신을 실제 확인했다.

## 구현과 영향 모듈

- **AI:** 범용 vLLM의 내부 스트리밍·최종 schema/완료 검증, 런타임별 동시 요청 제한,
  절대 예산, 취소/읽기 오류 정리. SDK가 지원하는 기존 HTTPX 전송을 범용 vLLM에만 사용한다. 범용 호출 한도와 공통 한도를 분리하고 client 재사용 키에
  한도를 포함한다. F4의 범용 vLLM도 같은 전송을 사용한다. F2·embedding 전송은 유지한다.
- **Backend:** 벤치마크가 현재 설정의 provider/route를 사용하도록 수정하고 조건별 횟수·필터,
  안전한 사용량/오류/HTTP status 측정을 지원한다. AI 직접 의존성의 lock 메타데이터를 동기화한다.
  Worker 종료 시 SDK client 종료 뒤 비동기 generator를 정리하고 loop를 닫는다.
  업무 상태 처리·HTTP 응답·DB 스키마는 변경하지 않는다.
- **문서/위키:** AI ADR-0007, F3 진단 계약, 환경 입력 안내와 이 보고서.
- **Frontend/data/infra 코드:** 변경 없음. 이번 RunPod 작업에는 화면 변경이나 새 브라우저 검증이 없다.

OpenAI SDK가 이미 사용하는 HTTPX2 2.10.0을 AI 직접 의존성으로 명시했다. 라이브러리 버전이나
새 패키지 설치 목록은 바뀌지 않았다. SDK 자동 재시도는 0이며 기존 repair/Worker 정책을 유지한다.

## 300초 적용 및 인프라 필요 사항

이번 실제 RunPod 개선 측정 프로세스에는 아래 값을 주입했다. **공유 dev 설정은 적용하지 않았다.**

```dotenv
AI_REQUEST_TIMEOUT_SECONDS=60
AI_GENERAL_REQUEST_TIMEOUT_SECONDS=300
AI_GENERAL_VLLM_MAX_IN_FLIGHT=1
```

새 범용 한도 미설정 시 기존 공통 한도를 따른다. 범용 vLLM에서는 로컬 슬롯 대기와 스트리밍
전체가 300초 예산에 포함된다. 토큰이 계속 와도 무한 연장되지 않는다. F3 전체에는 카드·판정·
repair 여러 호출이 있으므로 300초를 넘을 수 있다. UI polling의 300초와 별개이며, 조회 재개는
기존 실행의 GET을 사용해야 한다. Worker의 30초 heartbeat/300초 lease는 그대로 사용한다.

공유 적용에는 다음이 필요하다.

1. 애플리케이션에 스트리밍 구현을 배포한다.
2. `infra/environments/dev/configuration.tf`의 공개 AI map에 범용 300초·vLLM 단일 슬롯을 반영했다.
   검토한 Terraform apply와 기존 배포 경로의 주입이 필요하며, 임시 수동 값이 Terraform에 덮이지
   않게 한다.
3. Worker 및 범용 모델을 사용하는 API를 정상 종료·재시작한다.

이 변경을 위해 **GPU/Pod 재시작·GPU 증설·새 DB·ALB idle timeout 변경은 필요하지 않다.**
F3 접수/조회 API는 장시간 모델 호출을 직접 기다리지 않는다. RunPod 프록시 제한은 애플리케이션
설정만으로 해제할 수 없어 스트리밍 구현도 필요하다. 슬롯은 런타임별이므로 F4/API·다른
클라이언트의 GPU 경합까지 제어하지 않는다.

현재 토큰 생성 자체는 여전히 느리다. 후속 성능 실험은 동일 이미지/모델을 유지한 별도 검증
환경에서 `max_num_seqs` 확대와 CUDA graph 사용을 검토할 수 있다. 현재 `--enforce-eager`는
시작 시간과 정상 상태 처리량을 맞바꾸는 설정이다. 변경에는 VRAM/KV cache·지연·동시성 검증과
서빙 프로세스 재시작이 필요하며 **이번 작업에서 변경하거나 효과를 측정하지 않았다**.
[vLLM 0.28 최적화 문서](https://docs.vllm.ai/en/v0.28.0/configuration/optimization/).

## 재접근 진단과 원인 판정

2026-09-10에 기존 공유 자원을 변경하지 않고 AWS 역할·SSM·Secrets Manager 운영 경로로 다시
확인했다. general Pod와 모델은 `RUNNING`·`model_ready=true`였고, 이미지 digest·모델·revision은
이 보고서의 값과 모두 일치했다. 로컬에서 RunPod로 직접 보낸 최소 구조화 합성 호출은 2.758초에
성공했다. 그 호출 전후의 관측 GPU 최고 사용량은 39101/46068 MiB였으며, 같은 검증 명령의 배포
애플리케이션 경유 포지션 카드 2건+판정 smoke도 통과했다. 최소 호출은 연결·인증·model readiness
확인이지 F3 성능 표본은 아니다.

300초 초과의 원인은 다음처럼 구분한다.

1. **431.22초는 단일 Provider 호출이 아니다.** 300초는 로컬 슬롯 대기와 한 번의 스트림 생성을
   합친 호출별 절대 예산이다. L1 cold 전체는 앵커 111.48초, 후보 카드 172.68초, 최종 판정
   146.92초가 이어진 다중 호출 파이프라인이라 전체가 300초를 넘는다.
2. **후보의 코드상 병렬성과 실제 GPU 병렬성이 다르다.** 후보 세 호출의 순수 Provider 시간은
   54.27/64.53/53.47초지만 `max_num_seqs=1`과 프로세스 로컬 슬롯 1 때문에 호출 wall time은
   54.27/118.80/172.27초였다. 두 번째와 세 번째가 각각 약 54.27초와 118.80초를 기다렸다.
3. **주요 계산 병목은 출력 decode다.** L1 cold는 5회 호출에서 입력 11722, 출력 5390 tokens를
   사용했다. 카드 호출은 약 14.2~14.4 output tokens/s였고, 입력 5101/output 1326인 최종 판정은
   약 9.0 output tokens/s로 146.79초 걸렸다. 같은 카드 직접 진단의 첫 토큰은 2.28초였으므로
   그 표본에서는 연결·prefill보다 긴 구조화 출력 생성이 지연의 대부분이다.
4. **비스트리밍 실패는 별도 전송 문제다.** RunPod HTTP proxy는 100초 제한을 문서화한다.
   비스트리밍은 완료 전 응답 body가 없어 이 경로에 취약했고, 스트리밍은 실제로 146.79초
   판정을 끝까지 받았다. 스트리밍은 생성 속도를 높이지 않고 연결 실패면만 줄인다.
5. **공유 GPU 전체 대기는 아직 통제되지 않는다.** 현재 슬롯은 Python runtime별이라 별도
   API·Worker 프로세스와 다른 클라이언트가 각자 요청을 열 수 있다. F3와 F4가 general Pod를
   공유할 때 서버 앞 대기·우선순위·p95는 이번 단일 Worker 표본으로 검증되지 않았다.

후보 세 건이 서로의 처리량을 떨어뜨리지 않고 완전히 병렬화된다고 낙관해도 L1 전체 cold의
하한 추정은 `111.48 + max(54.27, 64.53, 53.47) + 146.92 = 322.93초`다. 동시성만 올려서는
완전 cold 300초를 보장하지 못한다. 반면 승인된 저장 흐름은 앵커 카드를 먼저 생성하므로 정상적인
첫 사용자 판정 경로에서 앵커가 준비돼 있다면 같은 낙관 추정은 약 211.45초다. 이는 예측일 뿐이며
동시 생성 시 tokens/s 저하, KV cache 압력과 다른 클라이언트 경합을 포함하지 않는다.

## 개선 제안

### 1. 현재 브랜치의 연결 안정화부터 배포

- 스트리밍·최종 schema 검증·300초 호출별 절대 예산을 먼저 적용한다. 전체 F3 timeout을
  300초로 오해해 Worker를 취소하지 않고 기존 영속 상태·lease heartbeat·GET 재개를 유지한다.
- 이 단계는 비스트리밍 proxy 실패를 해결하지만 성능 합격은 아니다. Terraform apply와
  애플리케이션 배포 전후의 동일 smoke가 별도로 필요하다.

### 2. 서버 튜닝은 별도 Pod에서 순차 실험

- 현재 프로필을 기준으로 `(max_num_seqs 1/2/3) × (eager/CUDA graph)`를 비교한다. 앱 슬롯도
  서버가 검증한 동시성까지만 맞추며, 공유 Pod를 바로 변경하지 않는다. vLLM에서
  `max_num_seqs`는 iteration당 처리할 최대 sequence 수이고, `--enforce-eager`는
  torch.compile과 CUDA graph를 끈다. [vLLM engine arguments](https://docs.vllm.ai/en/v0.28.0/configuration/engine_args/),
  [vLLM config](https://docs.vllm.ai/en/v0.28.0/api/vllm/config/vllm/).
- 현재 0.85 설정에서 39101/46068 MiB가 관측됐으므로 메모리 비율을 근거 없이 올리지 않는다.
  각 조합에서 L1/R1 cold·warm 3회 이상, 후보 5건, F4 동시 요청, OOM/재시작, TTFT·decode·queue와
  결과 계약 회귀를 함께 본다.
- 공통 system prompt를 재사용하는 prefix caching은 후보가 있지만 우선순위는 낮다. 공식 문서상
  shared prefix의 prefill 계산을 줄이는 기능이고, 현재 표본은 첫 토큰 2.28초 이후 decode가
  약 67.65초였기 때문이다. [vLLM prefix caching](https://docs.vllm.ai/en/v0.28.0/cli/serve/#--enable-prefix-caching).

### 3. 출력 계약과 토큰 예산 축소

- F3 두 생성기는 현재 `max_output_tokens`를 지정하지 않는다. 카드와 판정별 출력 토큰 상한을
  실측 분포+p99 여유로 정하고, 잘림은 성공으로 저장하지 않는 기존 계약을 유지한다.
- 최종 판정이 카드의 긴 근거 문구를 다시 복제하지 않고 검증 가능한 카드 evidence index를
  반환하도록 내부 schema를 압축하는 안을 평가한다. 비교 설명·걸림돌·양보·행동 문구도 제품에
  필요한 길이로 좁힌다. 이 변경은 prompt/workflow 또는 공개 계약 버전, cache invalidation과
  F3 품질 회귀 평가를 동반해야 하며 단순 문자열 절단으로 구현하지 않는다.

### 4. 프로세스 전역 admission과 우선순위

- API와 Worker가 RunPod proxy 연결을 열기 전에 공유 슬롯을 얻도록 PostgreSQL lease 기반
  admission 또는 단일 inference gateway를 둔다. F4 interactive 요청과 사용자 F3 요청을
  낮은 우선순위 batch보다 앞세우고, 대기 시간과 취소를 별도로 기록한다.
- 애플리케이션 `wall_ms`를 `admission_wait_ms`, `server_queue_ms`, `TTFT`, `decode_ms`,
  `output_tokens`, `total_ms`로 분해한다. vLLM은 request queue·TTFT·generation·inter-token
  측정을 제공하므로 인증된 내부 수집 후 CloudWatch에 안전한 집계만 보낸다. 공개 proxy에
  원시 `/metrics`를 노출하지 않는다. [vLLM per-request timing](https://docs.vllm.ai/en/v0.28.0/api/vllm/entrypoints/generate/base/serving/).
- 이 결정은 미해결 `OQ-F3-04`의 Worker 독립 배포·GPU 전체 동시성과 함께 확정해야 한다.
  RDS polling 자체를 SQS로 바꾸는 것은 GPU decode 병목을 줄이지 않으므로 선행 조건이 아니다.

### 5. 지연 목표가 엄격하면 capability 또는 endpoint를 분리

- `POSITION_CARD`와 `BROKERAGE_JUDGMENT`는 이미 별도 모델 설정이다. 합성 dev에서는 F3 전용
  품질 평가를 통과한 뒤 느린 capability만 Luna/Bedrock으로 라우팅하는 비교가 가장 작은
  아키텍처 변경이다. 기존 Luna 표본의 전체 cold는 43.77~52.70초였지만 1회 표본이며 prod
  선택·개인정보 처리 위치의 승인 근거는 아니다.
- 실제 데이터에서 서울 자체 호스팅 Qwen을 유지해야 하고 F3/F4 경합이 측정되면 interactive
  F4와 batch F3를 별도 general endpoint로 분리한다. 지연 격리는 명확하지만 GPU 비용·배포·
  모델 일관성 부담이 늘어난다.
- 저장 시 후보 카드와 전체 판정까지 자동 선계산하는 방식은 현재 승인된 ADR-0018을 바꾸고
  ADR-0037에서 폐기한 범위를 되살린다. 별도 제품 승인 없이는 성능 해법으로 적용하지 않는다.

자동 선계산 자체는 기존 화면과 HTTP 응답 형태를 바꾸지 않고 구현할 수 있다. 현재 화면은 처음
패널을 열 때 POST로 실행 ID를 확보한 뒤 같은 ID의 status/result를 조회하므로, Backend POST가
최신성이 확인된 기존 실행 ID를 반환하면 표시 흐름은 그대로다. 그러나 현재 Backend는 활성 실행만
재사용하고 완료 실행은 재사용하지 않는다. 따라서 단순 운영 flag가 아니라 다음 Backend 계약 중
하나가 필요하다.

- 후보 카드까지 선계산해 별도 주차한 뒤 사용자 POST가 같은 활성 실행을 이어받아 판정만 실행한다.
  새 후보 유입과 후보 데이터 변경을 놓치지 않을 freshness identity와 주차/재선점 규칙이 필요하다.
- 최종 판정까지 선계산하고 사용자 POST가 입력·후보·모델·prompt/workflow identity가 같은 완료
  실행을 반환한다. 사용자 체감은 가장 빠르지만 완료 결과 최신성·무효화·재판정 의미가 필요하다.

둘 다 Frontend 코드 변경은 필수가 아니지만, 버튼을 누르기 전 결과를 화면에 자동 노출하거나
`갱신 중`·`이전 결과`를 동시에 보여주려면 화면 상태와 조회 진입점 변경이 필요하다.

### 현 정책을 유지하는 실행 권고안

이번 후속 검토의 선택안은 자동 선계산을 도입하지 않고 ADR-0018의
`LEDGER_SAVE → ANCHOR_READY 주차 → 사용자 요청 시 후속 판정`을 유지하는 것이다. 최초 권고 뒤
사용자 요청에 따라 출력 축소를 먼저 검증하고, 전체 목표가 남을 때만 서버 동시성을 진행한다.

| 순서 | 변경 | 기대 효과와 검증 기준 |
|---|---|---|
| 1. 출력량 | 판정 출력이 카드 근거 원문을 복제하는 대신 검증 가능한 evidence reference를 반환하도록 내부 schema를 줄이고 reason code·120자 detail·근거 1~3개로 제한한다. 파일럿 뒤 `max_output_tokens=2048`을 tail guard로 적용한다. | 구현 실측에서 L1 판정 출력 1326→868 tokens, 판정 146.92→61.84초, warm 전체 150.85→61.10초였다. 공개 계약·저장·화면 정책은 유지한다. |
| 2. 서버 동시성 | 출력 축소 뒤에도 합의한 전체 목표가 남을 때 별도 Pod에서 `max_num_seqs=2`부터 시작해 안정 시 3, `--enforce-eager` 제거/CUDA graph 사용을 각각 비교한다. | 새 판정 61.84초를 대입한 앵커 준비 L1 낙관 추정은 seq=2 약 179.8초, seq=3 약 126.4초다. 실제 p50/p95, tokens/s, TTFT, queue, KV cache, OOM·재시작, F4 동시 지연으로 채택한다. |
| 3. 전역 admission | Backend 소유 PostgreSQL lease 슬롯 또는 단일 inference gateway로 API·Worker 합계 동시성을 서버 슬롯 수 이하로 제한한다. 우선순위는 F4 interactive → 사용자 F3 → `LEDGER_SAVE` 앵커 카드다. | RunPod HTTP 연결을 열기 전에 대기해 proxy의 첫 응답 전 timeout을 피하고 F3 fan-out이 F4를 고갈시키지 않게 한다. DB 방식을 쓰면 모델 호출 동안 DB connection/transaction을 보유하지 않고 만료 lease와 heartbeat로 복구한다. |
| 4. capability 라우팅 | 앞 단계로 목표를 못 맞출 때만 `BROKERAGE_JUDGMENT`를 F3 평가를 통과한 더 빠른 Provider로 분리한다. `POSITION_CARD`와 `CHATBOT`은 별도 판단한다. | Luna의 1회 기준선은 전체 cold 43.77~52.70초지만 F3 품질·p95·개인정보 승격 근거가 아니다. 외부 Provider가 불가하면 F3/F4 self-hosted endpoint 분리를 비교한다. |

출력 축소 후 서버 seq=2의 179.8초 추정은 후보 세 호출을 두 묶음으로 처리해
`max(54.27,64.53)+53.47+61.84`로 계산한 값이다. seq=3의 126.4초는
`max(54.27,64.53,53.47)+61.84`다. 앵커까지 새로 만드는 완전 cold 낙관 추정은 각각 약
291.3초와 237.9초다. 동시 decode에서 각 요청이 느려질 수 있으므로 목표값이 아니며 실측 전에는
공유 설정을 올리지 않는다. L1과 후보 5건이 우선 성능 gate다.

출력 축소는 공개 F3 응답을 없애는 변경이 아니다. 내부 모델 출력에서는 카드에 이미 있는 근거를
짧은 reference로 선택하게 하고 AI 조립 단계가 요청의 원본 근거를 결정적으로 복원하면, 현재
공개 DTO·DB 근거와 위조 방지 검증을 유지하면서 decode만 줄일 수 있다. 카드·판정 생성기는 현재
`max_output_tokens`를 지정하지 않으므로, 축소 schema를 먼저 검증한 뒤 상한을 tail guard로 둔다.

전역 admission의 총 슬롯은 채택한 `max_num_seqs`와 같게 시작한다. seq=3이면 F4용 1슬롯을
논리적으로 예약하고 F3가 최대 2슬롯을 사용하되, F4 대기가 없을 때만 유휴 슬롯 차용을 허용한다.
진행 중인 모델 호출을 강제 선점하지 않고 **대기 요청**의 순서만 제어한다. 기존 300초 호출 예산에는
전역 admission 대기와 스트림 완료를 모두 포함해 timeout 의미를 유지한다.

라우팅은 자동 fallback이 아니라 capability별 명시 설정으로 한다. 가장 느린 단일 단계인
`BROKERAGE_JUDGMENT`부터 A/B하고, 고정 F3 합성셋의 계약·근거·등급 안정성과 3회 이상 지연을
통과해야 한다. prod Provider는 OQ-014와 개인정보 처리 위치가 결정되기 전까지 확정하지 않는다.

사용자 후속 결정에 따른 개선 순서는 **출력량 → 필요 시 서버 동시성 → 전역 admission → capability
라우팅**이다. 계측 분해는 별도 개선 단계가 아니라 각 단계의 채택 조건으로 병행한다. 앞의 세
단계로 합의한 p95를 못 맞출 때만 capability 라우팅 또는 F3/F4 endpoint 분리를 선택한다.

### 출력 축소 구현과 재측정

사용자 후속 요청으로 동시성 변경보다 출력 축소를 먼저 구현했다. 공개
`brokerage-judgment:v1`과 DB/Frontend 계약은 유지하고 모델 전용 판정 출력만 다음처럼 바꿨다.

- 카드에서 중복되던 근거를 요청별 `evidence_catalog`에 한 번만 싣고, 모델은 후보별 정수
  `evidence_refs` 1~3개만 반환한다. AI 조립 단계가 원본 근거·side·field를 복원한다.
- 비교·장애물·양보·기각은 내부 reason code와 120자 이하 후보별 detail로 생성한다. 공개 결과는
  고정 한국어 문구와 detail을 조립한다.
- 최대 후보 5건 파일럿 3회는 출력 1451/1468/1468 tokens, 100.73/100.36/103.15초였다.
  관측 최대에 약 40% 여유를 둔 2048 tokens를 판정 tail guard로 적용했다. 3회는 정식 p99가
  아니므로 배포 후보의 고정 평가셋 30회 이상에서 재산정해야 한다.

같은 loopback Docker 합성 DB와 같은 RunPod FP8 모델로 L1을 다시 실행한 결과는 다음과 같다.

| 지표 | 기존 L1 | 출력 축소 후 L1 | 변화 |
|---|---:|---:|---:|
| 3후보 판정 입력 | 5101 tokens | 4557 tokens | -10.7% |
| 3후보 판정 출력 | 1326 tokens | 868 tokens | -34.5% |
| 3후보 판정 시간 | 146.92초 | 61.84초 | -57.9% |
| L1 warm 전체 | 150.85초 | 61.10초 | -59.5% |

새 cold 전체는 407.91초였다. 앵커 110.34초 뒤 후보 카드 셋 중 마지막 카드가 기존 계약 위반으로
한 번 repair되어 후보 단계가 235.39초가 된 영향이 포함됐다. 따라서 이 cold 총합을 출력 축소의
순수 비교값으로 쓰지 않고, 판정 단계와 모든 카드가 재사용된 warm 전체를 주 비교값으로 쓴다.
새 판정은 cold/warm 모두 첫 Provider 시도에서 공개 계약·저장·결과 조회까지 완료됐다.

현재 앵커와 후보 카드 생성은 여전히 긴 근거를 최초 생성하므로 이번 reference 범위 밖이다.
판정 단축 뒤 남은 주 병목은 cold 카드 생성 및 repair와 후보 카드의 단일 슬롯 직렬 처리다.
따라서 추가 품질 반복에서 판정 회귀가 없고 전체 목표가 여전히 미달할 때만 서버 동시성을
다음 단계로 진행한다.

## 재현 절차

1. 별도 dev 기반 워크트리와 폐기 가능한 loopback PostgreSQL DB를 준비한다. 기존 DB·Worker와
   분리하고 정본 migration을 적용한다.
2. `backend/src/manage.py seed-f3-synthetic --confirm-reset --model-profile local-openai`로
   시드를 적용하고 30개 검사를 확인한다. 출력된 사무소 ID를 사용한다.
3. [환경 입력 절차](../development/environment-variables.md)에 따라 실제 연결을 메모리/기존
   비밀 주입 경로로 설정한다. Pod/model 등록 상태를 확인하고 해당 사무소의 POSITION_CARD와
   BROKERAGE_JUDGMENT 모델을 공개 모델 선택 명령으로 명시 반영한다. 다른 Worker는 실행하지 않는다.
4. 저장소 루트에서 다음을 실행한다. 출력에는 원문·키 대신 시간·건수·토큰 사용량만 남는다.

```bash
PYTHONPATH=backend/src uv run --locked --project backend python \
  backend/tests/integration/benchmark_f3_real.py \
  --confirm-isolated --label runpod-stream-300 \
  --output /tmp/f3-runpod-measurement.json --repetitions 1
```

`APP_ENV=local`, 전용 `DB_URL`, `F3_ALLOW_SYNTHETIC_PROTOTYPE=true`와 위 AI 환경이 필요하다.
`--anchor-type LISTING|REQUIREMENT`, `--cache cold|warm`으로 범위를 제한할 수 있다.
불완료 실행은 기록 후 중단하므로 같은 DB에서 미완료 실행을 남기고 다음 측정을 접수하지 않는다.
비교 모델로 전환할 때도 해당 전용 시드와 모델 선택만 재설정한다.

## 검증과 한계

- AI 전체 테스트 506건, Pyright 통과. 실제 SDK 모의 스트림으로 정상 schema/usage, 불완전 종료,
  잘못된 schema, 무한 heartbeat의 절대 timeout, 활성/대기 요청 취소, 읽기 실패와 자원 정리를 검증했다.
- Backend 단위/계약 339건, 별도 회귀 DB의 F3 API/lease/선점/카드/판정 통합 177건 통과.
- AI·Backend 필수 Ruff check/format, Pyright 통과. 문서 링크 검사 통과.
- L1 스트리밍 실측은 300초를 넘는 실제 Worker 실행과 lease 갱신을 포함한다.
- 실제 모델은 각 조건 1회로 분산·p95를 평가할 수 없다. 브라우저 표시 시간, 대량 후보, 여러
  외부 클라이언트의 경합, 서버 배치 설정 변경, 5초 목표 달성은 검증하지 못했다.
- 본 작업의 전용 DB 2개를 포함한 tmpfs 컨테이너, 측정 스크립트·임시 JSON·PR 초안 파일,
  워크트리의 가상환경과 생성 캐시는 원자료 보존 후 제거했다. 공유 Pod와 기존 DB는 유지했다.


## 측정 원자료

- [최종 HTTPX 전송·종료 재확인](f3-runpod-performance-2026-09-10/runpod-httpx-shutdown-check.json)
- [종료 보완 중간 확인](f3-runpod-performance-2026-09-10/runpod-shutdown-check.json)
- [RunPod 개선 후 4조건](f3-runpod-performance-2026-09-10/runpod-after.json)
- [Luna 기준선](f3-runpod-performance-2026-09-10/luna-baseline.json)
- [RunPod 기존 60초](f3-runpod-performance-2026-09-10/runpod-before-60.json)
- [RunPod 비스트리밍 300초](f3-runpod-performance-2026-09-10/runpod-nonstream-300.json)
- [단일 L1 스트리밍 진단](f3-runpod-performance-2026-09-10/runpod-stream-diagnostic.json)
- [판정 출력 축소 비교](f3-runpod-performance-2026-09-10/judgment-output-compaction.json)


## 인계 상태와 남은 작업

- 작업 공간: `/tmp/SKN30-FINAL-3Team-f3-runpod`, 브랜치 `fix/f3-runpod-performance`.
  코드·테스트·원자료·문서는 보존하며, 사용자 종료 요청 시점의 미커밋 변경이다.
- 새 RunPod PR 생성·커밋·공유 dev Terraform apply·배포는 수행하지 않았다.
- 범용 300초 옵션과 vLLM 단일 슬롯은 구현하고, 다음 검토·적용을 위한 공유 dev Terraform 공개
  설정에 반영했다. 기본 공통 60초는 바꾸지 않았다.
- 생성/저장 안정성은 확인했으나 Luna 대비 속도 병목과 5초 목표 미달은 남아 있다.
- 최종 HTTPX 전송은 실제 R1 warm 1회 및 TCP 회귀로 확인했다. 최종 전송의 전체 cold/warm
  조합 반복·조건별 3회 표본·대량 후보·다중 클라이언트 경합과 서버 처리량 튜닝은 미완료다.
- 원래 저장소의 사용자 변경, 기존 DB와 공유 RunPod는 유지한다.

정리 완료: 전용 컨테이너 `f3-runpod-benchmark-db`와 `f3bench`/`f3regression` DB, 이번 측정용
임시 스크립트·JSON·가상환경·캐시를 제거했다. 후속 작업은 모듈별 `uv sync --locked` 후 재개한다.
