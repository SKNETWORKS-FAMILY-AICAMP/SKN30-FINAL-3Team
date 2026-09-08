# F4 챗봇 합성 평가

`cases.json`은 합성 질문 60개(기본 30, 단위 10, 멀티턴 10, 모호·미지원 10)와
공격 질문 20개다. 기준일은 2026-09-08이며 실제 고객·업무 데이터는 사용하지 않는다.

```bash
uv run --locked --project ai python ai/eval/chatbot/evaluate.py \
  --provider openai --model gpt-5.6-luna --rounds 3 \
  --output ai/eval/chatbot/results/luna.json
```

기존 AI 설정 로더가 `ai/.env.local`, 비추적 `ai/.env`, 환경변수를 읽는다. 키를 명령행에 넣지
않는다. OpenAI Luna가 지원하지 않는 `temperature`는 챗봇 요청에서 생략한다. 모델을 자동으로
다른 Provider로 전환하지 않는다.

평가는 실제 Provider를 사용하지만 조회 capability는 호출을 기록하는 fake다. 따라서 **의도·조건
추출과 워크플로의 차단 동작**을 검증한다. DB 권한·숫자·정확한 총계·실제 조회·브라우저 SSE
시간은 Backend 통합 평가에서 별도로 확인해야 한다. 특히 구입장 DB의 면적 기준은 전용/공급으로
구분되지 않으므로, 면적 표현을 추출한 평가 성공을 실제 구입장 면적 조회 지원으로 해석하지 않는다.

표시된 금액·면적 표현은 질문 원문을 복사한다. 평가는 누락뿐 아니라 불필요하게 추가한 조건도
오답으로 처리하며, refine에서는 이전 조건을 합친 결과를 비교한다. 공백과 진행 상태의
동의어만 정규화한다. `chatbot-intent-scorer:v2`는 `recent`도 명시 조건으로 비교하므로
누락·불필요한 추가를 오답 처리한다. 기존 원본·요약은 당시 판정으로 보존하며 수정 후 모델
평가를 대신하지 않는다. 명확화 응답에는 이전 질문의 표현을 사용하되 직전 답변이 명확화일 때만
복원한다. DB 이력 전체를 문맥으로 제공하지 않는다.

첫 warm-up은 별도로 기록하고 각 모델은 동시 1건으로 반복한다. 결과에는 전체·반복별 정확도,
멀티턴 정확도, 공격 실패 수, 모델 해석 시간 p95, 첫 workflow callback 시간 p95, 모델·프롬프트·
평가셋 hash를 기록한다. callback 시간은 HTTP/SSE 전달 시간이 아니다. 20개 공격 사례는 현재
요청 차단기에서 모델 호출 전에 종료하므로, 모델 자체의 공격 저항성을 증명하지 않는다.

부분 실행은 `--rounds 1 --case-ids basic-01,multi-10`으로 진단한다. 부분 실행 결과를 전체 합격으로
사용하지 않는다. 각 사례 뒤 checkpoint를 저장하며 완료 상태가 `COMPLETED`인 보고서만 최종
평가로 사용한다. 생성 보고서는 `results/`에서 비추적 상태로 보관한다.

## Qwen 재개

사용자가 3모델 비교를 재개했고 기존 비교 결과를 보존했다. 아래 명령은 별도 새 평가를 위한 절차다. `qwen3-14b-awq`, `qwen3-32b-awq`, `qwen38-27b-fp8`를
같은 80개 사례·3회, 동시 추론 1건으로 각각 실행한다. GPU 시작·종료는 Infra 운영자가 수행하며,
세 번째 모델은 사용자 최종 선택인 공식 Qwen FP8이며 BnB는 기동 이력만 보존한다.
이 평가기는 이미 준비된 endpoint만 사용한다. 실제 완료 보고서가 없으면 합격으로 표시하지 않는다.

```bash
uv run --locked --project ai python ai/eval/chatbot/evaluate.py \
  --environment local --profiles-file infra/serving/model-profiles.json \
  --model-profile qwen3-14b-awq --endpoint-alias general-dev-gpu \
  --artifact-sha256 '<실제 다운로드 파일 검증 manifest의 SHA-256>' \
  --deployment-image '<실제 실행 general-serving 이미지@sha256:digest>' \
  --rounds 3 --output ai/eval/chatbot/results/qwen3-14b-awq.json
```

모델·revision·vLLM 버전·이미지 digest·기동 설정은 명시적으로 전달한 JSON 프로필에서 읽는다.
`--artifact-sha256`는 운영자가 실제 다운로드 파일을 검증한 manifest hash다.
프로필의 예상 가중치 목록 hash인 `expected_weights_manifest_sha256`와 구분한다.
`--deployment-image`에는 실제 실행한 general-serving wrapper 이미지 digest를 별도로 기록한다.
프로필의 `runtime_image`는 vLLM 기반 이미지이며 wrapper와 동일한 이미지라고 간주하지 않는다.
실제 hash는 프로필 가중치 목록의 canonical JSON hash와 일치해야 한다. 평가 전·후 인증된
`/ops/status`를 조회하여 모델·revision·가중치 hash·runtime 버전·기반 이미지·프로필을 대조한다.
평가기 자체가 원격 파일을 다시 해시하거나 컨테이너 이미지를 독립 검증하지는 않는다. Infra의
실제 파일 검증 기록과 Pod API 이미지 digest 대조 기록을 함께 보존한다. endpoint 주소나 비밀키는
보고서에 기록하지 않는다. 프로필을 쓰지 않는 self-hosted
실행도 `--runtime-label`, `--runtime-image`(digest), `--artifact-revision`(commit),
`--artifact-sha256`, `--deployment-image`를 요구한다. 모델을 자동으로 다른 Provider로 전환하지 않는다.

초기화 전에 `RUNNING` 보고서를 원자적으로 저장한다. 초기화·warm-up 실패도 `FAILED`와 실패
단계·예외 종류만 남기며 민감할 수 있는 예외 메시지는 저장하지 않는다. 정상 취소는 `INTERRUPTED`로
남긴다. 강제 프로세스 종료는 마지막 checkpoint만 남을 수 있다. 미완료 보고서를 성공으로 집계하지
않는다. 사례별 실패는 전체 실행을 계속하여 실패율과 모델별 차이를 보존한다.

HTTP/SSE 성능은 로컬 격리 PostgreSQL과 실제 모델을 함께 사용하는 아래 평가기로 별도 확인한다.
`TEST_DB_URL`은 loopback PostgreSQL의 CREATE DATABASE 가능한 계정을 가리켜야 한다. 실행마다
임시 DB를 생성·마이그레이션·합성 seed하고 종료 시 그 DB만 삭제한다. Backend가 읽는 환경에
`AI_LLM_ENDPOINTS`와 해당 API key를 명시적으로 주입한다. AI 개인 `.env`를 암묵적으로 읽지 않는다.

```bash
uv run --locked --project backend python backend/eval/chatbot_http.py \
  --profiles-file infra/serving/model-profiles.json --model-profile qwen3-14b-awq \
  --deployment-image '<실제 실행 general-serving 이미지@sha256:digest>' \
  --artifact-sha256 '<실제 다운로드 파일 검증 manifest의 SHA-256>' \
  --rounds 3 --output /tmp/qwen3-14b-awq-http.json
```

HTTP 평가는 모델당 warm-up 1건을 제외한 12개 실제 조회×3회, 정확한 총건수·완료·저장 복원·전체
삭제와 첫 SSE p95 ≤1초, 완료 p95 ≤30초를 검사한다. 나머지 두 모델도 동일 명령의 프로필과 출력
경로만 바꾼다. 기존 `local-openai` CLI와 F3 활성 모델은 변경하지 않는다.

## 검증 기록

저장된 Luna·Qwen 측정값은 workflow v2의 조건 근거 검사·v3의 고정 재생성 메시지 및 scorer v2
도입 전 실행이다. 이번 병합·단위 테스트는 수정 후 실제 모델 재평가가 아니다. 기존 원본·검토
요약의 점수와 hash를 유지하고 현재 workflow의 정확도·성능으로 표시하지 않는다.

[Luna 2026-09-08 결과](validation/luna-20260908.json): 기본·단위 112/120(93.33%),
멀티턴 30/30, 모호·미지원 29/30, 공격 차단 60/60. 모델 해석 p95는 2.884초다.
반복별 점수와 오답 조건은 결과 파일에 보존한다. 지원 조건이 항상 정확하다는 뜻은 아니며
화면의 적용 조건을 확인할 수 있어야 한다. 검토 중 추가된 과거 차단 질문의 비밀값 제외 처리는
별도 회귀 테스트로 확인했고, 모델이 실제 받은 59종 입력의 hash는 수정 전후 동일했다.


## 원본 보고서와 검토 요약의 형식

`evaluate.py --output ...`은 사례별 `rows`, 전체·반복별 `summary`, 실행 provenance가 있는 **원본
보고서**를 만든다. `results/`의 원본은 수정하지 않고 SHA-256으로 결속한다. 2026-09-08 원본의
`provenance.prompt_sha256`은 당시 workflow 파일 전체의 hash인 기존 필드명이다.

`validation/luna-20260908.json`은 이 CLI의 직접 출력이 아닌 **수동 집계·검토 요약**이다.
`artifact_kind=chatbot_evaluation_reviewed_summary`, `schema_version=1`,
`creation_method=manual_aggregation_and_review`로 이를 구분한다. 수치·오답에는 원본의
`rows`를 집계하고, 보안 검토 후 입력 동등성·검토 시점 workflow hash·Qwen 보류 결정은 별도
검토 주석으로 추가했다. `evaluated_workflow_sha256`은 원본의 workflow hash를 보존한다.

요약 생성 절차는 다음과 같다.

1. 완료된 원본 파일을 보존하고 그 파일 바이트의 SHA-256을 `raw_report_sha256`에 기록한다.
2. `verify_summary.recompute_aggregates(raw["rows"])`로 전체·반복별 점수, 그룹별 분모·정답 수,
   오답 목록을 다시 계산해 요약에 넣는다. 이 함수는 현재 `evaluate.summarize`를 재사용한다.
3. 실행 provenance를 대조하고 검토 주석을 별도 추가한다. 원본 실행을 다시 했다고 표시하지 않는다.
4. 아래 검증기로 schema·원본 hash·80종×3회 구성·전체·반복별 집계·오답 목록을 확인한다.
   검증기 버전은 `chatbot-summary-verifier:v1`이며 수동 검토 자체를 자동 생성했다고 주장하지 않는다.

```bash
uv run --locked --project ai python ai/eval/chatbot/verify_summary.py \
  --raw ai/eval/chatbot/results/luna-20260908.json \
  --summary ai/eval/chatbot/validation/luna-20260908.json
```

이 명령은 모델이나 DB를 호출하지 않는다. 원본 파일이 없으면 실제 검증을 완료할 수 없으며,
요약만으로 원본 실행을 다시 만들 수 있다고 간주하지 않는다. 저장소 단위 테스트는 합성 원본으로
수치·반복별 값 변경, 원본 바이트 변경, 중복 관측과 잘못된 artifact 형식의 거절을 검증한다.

## Qwen 검토 과정 재현

재채점은 원본 provenance의 `scorer_version`을 따른다. 키 자체가 없거나 명시적으로
`chatbot-intent-scorer:v1`이면 당시 규칙대로 실제·기대·현재 조건의 `recent`를 비교에서 제외한다.
`chatbot-intent-scorer:v2`는 명시적 최근 정렬을 비교하며, null·빈 문자열·미등록 버전은 거절한다.
원본에 버전이 있을 때만 새 요약에 그대로 보존하므로 기존 무버전 요약을 소급 수정하지 않는다.
`verify_summary.py`는 저장된 판정을 재채점하지 않고 집계하며 버전 metadata 일치를 검사한다.
이는 과거 기록의 재검토이고 현재 workflow v3로 모델을 다시 실행하는 절차가 아니다.

`review_summary.py`는 기존 임시 검토 도구를 저장소에 옮긴 오프라인 CLI다. 완료된 원본의
전체 80개×3회 구성, 정본 fixture hash, 각 사례의 재채점, `actual`·`attempts` 구조와
민감 문자열 패턴, 허용 metadata 필드, 가중치 manifest hash 및 실행 전후 모델 증빙을 검사한다.
그 후 기존 `recompute_aggregates`와 `verify_summary`로 수치·실패 목록·원본 hash를 검증한다.
모델·DB·GPU를 호출하지 않으며, endpoint 증빙 대조를 원격 파일 재검증이나 실제 Pod 이미지
확인으로 해석하지 않는다. 민감 문자열 검사는 사람의 검토를 보조하며 완전한 탐지를 보장하지 않는다.

검토자가 원본의 합성 출력과 실패 내용을 확인한 뒤 `--reviewed`를 명시한다. `RUNNING`,
`FAILED`, 부분 평가 또는 일치하지 않는 fixture는 거절한다. 출력은 항상 새 파일이어야 하며
원본·기존 요약을 덮어쓰지 않는다. `COMPLETED`는 실행 완료 상태이며 정확도 합격 여부와 별개다.

```bash
uv run --locked --project ai python ai/eval/chatbot/review_summary.py \
  --raw ai/eval/chatbot/results/qwen38-27b-fp8-20260908.json \
  --output /tmp/qwen38-27b-fp8-reviewed-new.json \
  --verify-against ai/eval/chatbot/validation/qwen38-27b-fp8-20260908.json \
  --reviewed
```

`--verify-against`는 기존 요약도 같은 원본으로 검증하여 집계와 원본 hash가 일치하는지 확인한다.
기존 요약에 추가된 수동 원인 분석·채택 판단 주석을 새로 작성하거나 복제하지 않는다. 재현 범위는
자동 검사·집계·원본 결속이며, 수동 주석은 기존 검토 문서에 남는다. 실행한 모델의 프로필 snapshot을
원본에서 읽으므로 이후 다른 모델이 추가되어 현재 프로필 파일 hash가 달라져도 과거 검토가 가능하다.

세 기존 결과를 새 디렉터리에서 재현하려면 다음을 실행한다.

```bash
review_output_dir="$(mktemp -d /tmp/qwen-review-replay.XXXXXX)"
for profile in qwen3-14b-awq qwen3-32b-awq qwen38-27b-fp8; do
  uv run --locked --project ai python ai/eval/chatbot/review_summary.py \
    --raw "ai/eval/chatbot/results/${profile}-20260908.json" \
    --output "${review_output_dir}/${profile}.json" \
    --verify-against "ai/eval/chatbot/validation/${profile}-20260908.json" \
    --reviewed
done
```

원본 `results/`는 비추적 산출물이므로 새 checkout에는 없을 수 있다. 평가 때 보존한 정확한 원본
파일이 필요하며, 요약만으로 원본 실행을 재생성하거나 검증을 통과했다고 표시하지 않는다.

## 개발 검증 의존성

AI의 기존 F2 AAC 변환 테스트와 Pyright 검사에는 PyAV가 필요하다. `av==18.1.0`은 AI의 `dev`
그룹과 `uv.lock`에 고정한다. `uv sync --locked --project ai`로 재현하며 production 의존성에는
추가하지 않는다. 이전 실행에서 사용한 임시 `--with av` 설치가 CI의 숨은 선행조건이 되지 않게 한다.
