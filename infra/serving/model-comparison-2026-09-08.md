# Qwen 3모델 비교 — 2026-09-08

상태: 프로필 구현·단위 검증과 AWQ 2종·공식 FP8의 모델 및 HTTP 비교 평가 완료. 공유 dev 배포·활성 모델 변경은 포함하지 않는다.

## 범위와 재현 계약

사용자의 최종 선택으로 `qwen3-14b-awq`, `qwen3-32b-awq`, `qwen38-27b-fp8`를 비교한다.
세 번째 모델은 공식 `Qwen/Qwen3.8-27B-FP8`이다. 최초 BnB 요청 이후 사용자가 추론용
양자화를 재검토하고 FP8으로 변경했다. BnB 기동 이력은 보존하되 품질 비교에는 포함하지 않는다.
프로필 정본은 [model-profiles.json](model-profiles.json)이다. 모델 repository·불변 revision·
가중치별 크기/SHA256·공식 vLLM base image digest와 실행 옵션을 함께 고정한다.

- 공통 조건: vLLM 0.28.0 linux/amd64, L40S 48GB 1대, 8K context, 동시 추론 1건,
  GPU 메모리 비율 0.85, eager, thinking off. 모델별 양자화·loader는 프로필에 명시한다.
- RunPod 호스트 선택은 `allowedCudaVersions=["13.0"]`, 실행은
  `VLLM_ENABLE_CUDA_COMPATIBILITY=0`으로 고정한다. 호환 라이브러리를 켠 `1`은
  실제 L40S에서 CUDA 803으로 실패했고 `0`에서 14B 로딩을 확인했다.
  CUDA 필터는 호스트 선택 조건이며 실제 드라이버 버전을 증명하지 않는다. AWS 실기동은 미검증이다.
- 가중치는 이미지에 포함하지 않는다. GPU에서 고정 revision을 다운로드한 후 실제 파일을
  해시 검증한다. 검증 결과는 인증된 `/ops/status`에 최소 metadata로 제공한다.
- 공식 vLLM 0.28.0 이미지에는 bitsandbytes가 없어 `runtime-requirements.txt`로
  0.50.2와 wheel hash를 고정해 설치한다. 실제 기동에서 BnB 플러그인도 필요함을 확인해
  공식 `vllm-bnb-plugin==0.0.2`와 wheel hash를 추가했다. torch 등 기존 의존성은 교체하지 않는다.
- `runtime_image`는 공식 base image, `deployment_image`는 실제 게시한 general-serving
  wrapper image다. 두 digest를 구분한다. 최초 공통 wrapper의 AWQ 평가를 완료했으나
  BnB에서 `Unknown quantization method: bitsandbytes`가 발생해 해당 플러그인을 추가한
  wrapper로 BnB 기동에 성공했다. FP8 프로필을 추가한 이미지로 마지막 모델을 평가하므로
  세 모델의 wrapper digest가 완전히 동일한 비교는 아니다.
  GPU·vLLM 0.28.0·질문·프롬프트·실행 제한은 유지하고 모델별 의존성 차이를 기록한다.
- 선택은 `GENERAL_MODEL_PROFILE`로 명시한다. 모델 변경은 서버 재기동·가중치 재로딩이
  필요하며 추론 중 hot swap이나 자동 fallback은 제공하지 않는다.

## 평가와 기록

기존 F4 합성 평가셋(기본 30, 동의어/단위 10, 멀티턴 10, 모호/미지원 10,
별도 공격 20)을 각 모델에 3회 적용한다. 기존 fixture·프롬프트를 평가 중 수정하지 않는다.
정확도와 warm 지연은 분리하며 모델 실패·기동 실패를 0점 추론이나 평가 통과로 표시하지 않는다.
공격 점수는 guard를 포함한 workflow 결과이며 모델 자체의 주입 공격 저항성을 뜻하지 않는다.
HTTP 평가는 별도의 loopback PostgreSQL에서 12개 질의를 각 3회 측정한다.

AI 평가기의 `--profiles-file infra/serving/model-profiles.json --model-profile <id>`는
명시적 데이터 계약으로 프로필을 받으며 Infra 내부 Python 모듈을 import하지 않는다.
`--deployment-image`와 실제 검증된 `--artifact-sha256`가 필요하고, 시작·종료 시 서버 metadata를
대조한다. endpoint와 key는 ignored 개인 환경파일을 통해 해당 로컬 프로세스에만 전달한다.
원본 결과는 ignored `ai/eval/chatbot/results/`, 검토한 집계는 `ai/eval/chatbot/validation/`에 둔다.
원본 본문을 PR·로그에 복제하지 않는다. 집계는 기존 `verify_summary.py`로 검증한다.

## 운영 경계

기존 `xmi5zb7066`의 이름·registry를 사용하되 평가 Pod 생성 시 새 immutable image와
`python3` 시작 명령·프로필을 명시 override한다. 기존 F3 개인 Pod와 학습 Pod는 변경하지 않는다.
평가에서는 공유 endpoint/selection/DB를 변경하지 않는다. 평가자 Hong1008/Codex가
시작·종료 확인을 담당하고, 모델 평가 종료 또는 로딩 실패 확인 후 정확한 평가 Pod ID를 삭제한다.
Volume/Network Volume은 생성하지 않는다. 자동 감시·예약 종료는 추가하지 않는다.

2026-09-08 조회 L40S Secure 단가는 $1.09/h, 시작 전 계정 잔액 약 $176.76이었다.
순차 실행 3시간 가정 GPU 비용 약 $3.27이며 730시간 계속 켜두면 약 $795.70이다.
스토리지·세금·실제 청구 반올림은 별도다. 기존 RunPod 2개월 $300 한도는 유지한다.
실제 실행 시간과 자원 삭제 확인을 아래 결과에 기록한다.

공유 운영 코드의 `configure general --model-profile`은 선택만 저장한다. 이후 명시 기동은
선택 모델을 probe·endpoint metadata·앱 smoke로 전달하고, 명시 활성화는 endpoint 모델과
일치할 때만 진행한다. F3/CHATBOT DB의 기존 활성 모델을 자동으로 바꾸지 않는다.
AWS user-data에도 프로필 파일 복사를 추가하나 이번에 Terraform apply는 수행하지 않는다.

## 결과

F4 챗봇의 고정 합성 평가다. F3의 포지션 카드·중개 판단 품질 점수로 해석하지 않는다.
모델 세대·크기와 양자화가 함께 다른 배포 구성 비교이므로 AWQ 대 FP8의 순수 효과로 해석하지 않는다.

| 항목 | Qwen3 14B AWQ | Qwen3 32B AWQ | 공식 Qwen 27B FP8 |
|---|---:|---:|---|
| 모델 평가 실행 | 240/240 | 240/240 | 240/240 |
| 지원 질문 | 72/150 (48%) | 117/150 (78%) | 141/150 (94%) |
| 기본·단위 | 54/120 (45%) | 93/120 (77.5%) | 111/120 (92.5%) |
| 멀티턴 | 18/30 (60%) | 24/30 (80%) | 30/30 (100%) |
| 모호·미지원 | 21/30 (70%) | 27/30 (90%) | 24/30 (80%) |
| 워크플로 공격 차단 | 60/60 | 60/60 | 60/60 |
| 계약 오류 | 3건 | 0건 | 0건 |
| 해석 p95 | 3.572초 | 7.042초 | 11.930초 |
| HTTP 정확한 결과 | 15/36 | 33/36 | 36/36 |
| HTTP 첫 진행 p95 | 0.160초 | 0.221초 | 0.224초 |
| HTTP 완료 p95 | 3.780초 | 4.819초 | 11.921초 |
| 저장 결과 복원 | 36/36 | 36/36 | 36/36 |
| 평가기 전체 판정 / HTTP 판정 | 실패 / 실패 | 실패 / 실패 | 실패 / 통과 |

- 지원 질문 정확도는 기본·단위·멀티턴 50건을 반복한 150건의 도구와 조건 일치율이다.
  3회 지원 정확도는 14B 48/48/48%, 32B 78/78/78%, FP8 94/94/94%로 같았다.
- HTTP 지연은 warmup 1회를 제외한 **오답 포함 36개 요청**의 p95다. 완료 상태와
  정확한 결과를 구분한다. 세 모델 모두 매회 저장 결과 복원·최종 대화 삭제는 성공했다.
  FP8의 HTTP는 정확도·warm 지연을 통과했지만 모델 평가의 모호·미지원 기준은 미달했다.
  지연만으로 모든 수용 기준 통과를 주장하지 않는다.
- 32B는 14B 대비 17종 사례(51회)가 개선되고 회귀는 없었다. 14B의 불필요한 일정 조건,
  잘못된 후속 질문 처리, 보증금·임대료 혼동과 반복 계약 오류가 개선됐다.
  32B에도 요청하지 않은 SALE 추가, 조건 유지·명확화 복원 오류가 남았다.
  HTTP의 32B 오답은 `진행 중인 구입장 보여줘`가 재질문으로 바뀐 3회다.
- FP8은 32B 대비 9종 사례(27회)가 개선되고 2종(6회)이 회귀했다.
  남은 지원 질문 오답은 `basic-17`, `basic-18`, `units-09`의 요청하지 않은 SALE 조건 추가다.
  `ambiguous-04`는 모순 범위를 재질문하지 않고 조회 조건으로 내보냈고, `ambiguous-06`는
  기대한 clarification 대신 unsupported로 분류했다. 각 반복의 실패 ID 5개는 같았다.
  FP8의 모델 해석 p95 11.930초는 32B의 7.042초보다 길었다.
- 공격 차단은 모델 호출 전 애플리케이션 guard의 결과다. 모델 자체의 공격 저항성 점수가 아니다.
- 기존 평가기의 `model_calls` 집계는 실패행의 구조화 응답을 제외한다. 14B는 집계 177회이나
  측정 사례의 구조화 응답은 186개(계약 오류 3건의 9회 포함)다. warmup은 별도다.
  원본·채점·프롬프트는 평가 중 수정하지 않았고 이 한계는 검토 요약에도 기록했다.

검토 요약은 원본 SHA256·240개 고유 관측·반복별 집계·실패 ID·endpoint 전후 metadata를
`verify_summary.py`로 대조했다. 구조화 출력에는 실제 개인정보·비밀값·SQL이 없는지 검토했다.

- [14B AI 근거](../../ai/eval/chatbot/validation/qwen3-14b-awq-20260908.json),
  [14B HTTP 근거](../../backend/eval/validation/chatbot-http-qwen3-14b-awq-20260908.json)
- [32B AI 근거](../../ai/eval/chatbot/validation/qwen3-32b-awq-20260908.json),
  [32B HTTP 근거](../../backend/eval/validation/chatbot-http-qwen3-32b-awq-20260908.json)
- [공식 FP8 AI 근거](../../ai/eval/chatbot/validation/qwen38-27b-fp8-20260908.json),
  [공식 FP8 HTTP 근거](../../backend/eval/validation/chatbot-http-qwen38-27b-fp8-20260908.json)

## 실행 근거와 적용 한계

AWQ 평가 wrapper는 `general-serving@sha256:ce0e6e07d3656b81c63b4698e82f04421548b4f06ab1e428e9de3778adf9da6e`다.
게시 소스 `cfd05ebe09de26fd96fd3e5dec66be3aff146715`,
[성공한 이미지 workflow](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34190920284)를 확인했다.
공식 base와 모델 revision·가중치 해시는 프로필과 각 검토 요약에 포함한다.

27B 최초 시도는 가중치 해시가 맞았으나 ModelConfig에서
`Unknown quantization method: bitsandbytes`로 실패했다. 공식 플러그인의 등록 코드와
일치하는 누락이며, `vllm-bnb-plugin==0.0.3`을 추가하고 실제 quantization/loader registry를
빌드에서 검사하도록 보완했다. 0.0.3은 개발판 vLLM의 `get_rename_mapper()` API를 사용해 고정 0.28에서 실패했다.
공식 0.0.2의 `get_unstacked_mapper()`가 0.28 API와 일치해 핀을 맞추고, 빌드 검사도 실제
`WeightsMapper`를 사용한 로더 초기화까지 확대했다. [공식 변경 PR](https://github.com/vllm-project/vllm-bnb-plugin/pull/10).
플러그인 설치만으로 해당 가중치 호환 성공을 주장하지 않는다.
[공식 플러그인](https://github.com/vllm-project/vllm-bnb-plugin/tree/v0.0.3),
[고정 패키지 metadata](https://pypi.org/pypi/vllm-bnb-plugin/0.0.3/json).

27B BnB 최종 재시도 wrapper는 `general-serving@sha256:c178666e09239c3366f32ad59e1aa85c13db43c8902a1a2729a9fc9fc09eb06f`다.
게시 소스 `53b97bff79a44a08c26e61111bdcc64469023016`,
[이미지 workflow](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34197647141)는 성공했다.
빌드 검사는 실제 CPU LinearBase·WeightsMapper를 플러그인 초기화 경로에 전달한다.
GPU 가중치 호환은 이 빌드 검사와 별도로 판정한다.

공식 FP8은 지원 질문·멀티턴에서 가장 높은 정확도를 보였으나 모호·미지원 정확도는 80%였다.
기존 평가기는 이 항목에도 90%를 요구하므로 전체 판정은 실패다. 수용 문서의 지원 질문·멀티턴
90%와 평가기의 추가 기준을 구분한다. 비교 중 기준을 완화하거나 기본 모델로 자동 승격하지 않는다.
후속 검토 제안은 거래 유형을 명시하지 않았을 때 SALE을 추가하지 않는 대조 예시,
열거형 조건의 질문·이전 조건 근거 검사, refine과 명확화 복원을 구분하는 상태 계약이다.
프롬프트·구조화 조건 규칙을 개선한다면 기존 80개를 회귀로 유지하고 개발 중 보지 않은
별도 holdout(예: 생략·명시·조건 변경·명확화 각 10개)을 준비해 각각 3회 재평가한다.
이 제안은 승인된 추가 구현 범위가 아니며 이번 비교에서는 프롬프트를 바꾸지 않았다.
공유 dev 활성화·F3 실제 품질·AWS 운영·F3 동시 경합·cold start 반복·공유 SSE 경로는
이번 비교의 검증 결과가 아니다. 기존 코드 회귀와 별도로 운영 경로 검증이 필요하다.

## 27B 양자화 변경과 BnB 기동 이력

사용자는 추론용 대안을 검토한 뒤 공식 `Qwen/Qwen3.8-27B-FP8`을 선택했다.
고정 revision은 `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`이며 66개 가중치 파일
약 28.747GiB를 사용한다. vLLM의 FP8 경로를 사용하고 챗봇 Provider·API·DB는 바꾸지 않는다.
 BnB 0.0.2 조합은 실제 `/ops/status` 준비 완료와 가중치 해시를
확인했다. 모델 로딩 메모리 로그는 17.92GiB이며 전체 VRAM 최고점은 아니다.
질문 평가는 시작하지 않았고, 선택 검토 중 비용을 멈추기 위해 해당 Pod를 삭제했다.
따라서 BnB의 마지막 상태는 로딩 실패가 아닌 **기동 성공·품질 미평가**다.

검토 후보는 [공식 FP8](https://huggingface.co/Qwen/Qwen3.8-27B-FP8)과
[cyankiwi AWQ INT4](https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4)다.
후자는 `quant_method=compressed-tensors`인 INT4/group32 저장 형식이므로 기존
`--quantization awq`를 그대로 적용하지 않는다. BnB도 추론 가능하지만 이 환경에서는
별도 플러그인의 버전 관리가 필요했다. 모델별 속도·정확도는 비트 수만으로 판정하지 않는다.

## 코드 검증

AI 전체 342개와 격리 PostgreSQL의 Backend 전체 678개 회귀가 통과했다.
FP8 추가 후 Backend 모델 선택 12개, Infra 209개, serving 13개 검사를 통과했다.
Backend 지정 Ruff·포맷·Pyright와 Infra 변경 파일 Ruff·구문 검사, `git diff --check`를 통과했다.
독립 에이전트가 기존 기본값·F3 활성화 보존, 가중치 manifest·CLI 검증 경계를 검토했으며
FP8 추가 코드에서 확정 결함은 발견하지 못했다. 별도 에이전트가 AI 240행과
HTTP warmup 제외 36행·복원·삭제·p95·전후 provenance를 재계산해 확인했다.
공개 보고서에서 개인정보·비밀값·SQL을 발견하지 않았다. 사람의 PR 검토는 별도다.

## 공식 FP8 게시 근거

FP8 wrapper는 `general-serving@sha256:801473c822b3536c58dd310f0768dfacf0aebd968c06a4ea427d0d9561f5c1e7`이다.
소스 `8bfd2c8c83d11c5b9b03b7e031a62ffacf128fef`,
[성공한 이미지 workflow](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34200029859)를 확인했다.
실제 vLLM FP8 registry·모든 프로필의 CLI 인자 검사와 BnB loader 초기화 검사가 빌드에서 통과했다.
FP8은 `fp8 / auto` 경로로 기동하며 BnB 플러그인은 기존 프로필 호환을 위해 이미지에 보존했다.

공식 FP8은 L40S에서 실제 준비 완료를 확인했다. 검증된 manifest hash는
`df7b86af780f7bfac95ccefe48ef888724e78967039588e62453cae08c9f4e62`다.
모델 로딩 로그는 27.64GiB·3.669초이며, 이는 전체 cold start나 VRAM 최고점이 아니다.
이미지 다운로드·모델 다운로드·GPU 로딩·API 준비를 포함한 최초 준비 관측은 Pod 생성 후 약 652초였다.

## 자원 정리와 비용

이번 비교의 평가 Pod 7개(실패·BnB 기동 이력 포함)는 모두 ID별 삭제 후 RunPod 목록에서
부재를 확인했다. 기존 F2 학습·F3 작업자 Pod, 공유 template·endpoint·활성 모델은 보존했다.
FP8 Pod 사용 시간은 약 3,189초였다. 전체 평가 Pod 사용 시간은 약 7,086초이며
단가 $1.09/h로 산정한 GPU 비용은 **약 $2.15**다. 실제 청구 금액이 아니며 저장 공간·세금·
반올림은 별도다. 로컬 `skn30-qwen-eval-db`도 삭제하고 기존 `brokerage-db`는 유지했다.
[자원·이미지·삭제 근거](model-comparison-evidence-2026-09-08.json)에 최소 metadata만 보존한다.

## 검토 재현과 이미지 재사용

[재현 절차](comparison-reproduction.md)에 검토 순서·코드 명령과 이미지별 재사용 판단을 기록했다.
[게시 태그·양자화 catalog](published-images.json)는 CPU 검사·기동 성공·품질 평가 완료·실패를 구분한다.

재현 도구 추가 후 AI 검토 도구·기존 검증기 관련 39개와 serving 전체 23개 테스트가 통과했다.
실제 세 모델 원본에서 새 요약을 생성해 기존 요약과 집계·원본 hash를 대조했다.
독립 검토에서 반복별 정확도 검증 누락을 발견해 수정했고, 동일한 100% 변조 입력이 거부됨을 재확인했다.

## 평가 후 dev 통합 경계

평가 완료 후 dev #106·#108·#109를 통합했다. #109의 재연락 제거에 맞춰 Backend 일정
조회 window 생성과 미지원 안내를 조정했다. AI 프롬프트·고정 fixture·원본 점수는 보존한다.
80개 입력 중 재연락 2개는 과거 비교 범위이며 최신 지원 기능으로 해석하지 않는다.
현재 범위의 신규 모델 품질 판정은 별도 버전 평가가 필요하다.

통합 후 Backend 단위 26개·격리 PostgreSQL 챗봇 통합 15개, Frontend Time Keeper 42개·
챗봇 브라우저 8개·타입 검사·별도 출력 경로의 production build를 통과했다.
기존 root 소유 dist는 건드리지 않고 `/tmp`로 빌드했다. 추가 통합 검증 DB도 삭제했다.


## 최신 dev 병합 시 평가 기록의 경계

PR #99~#101의 workflow v3·필터 근거 검사·scorer v2·UI 경합 수정을 보존했다. 위 Qwen
평가는 이 변경 전의 역사적 결과이며 새 코드의 성능 합격 근거가 아니다. 원본에 scorer 버전이
없으면 당시 v1 규칙으로만 검토 요약을 재현하고, 명시된 v2는 현재 규칙을 사용한다. 알 수 없는
버전은 거절한다. 원본·요약 점수는 소급 변경하지 않으며 새 모델 평가는 별도 원본으로 수행한다.
