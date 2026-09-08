# Qwen 비교 검토 재현과 이미지 재사용

상태: 2026-09-08 실제 비교·독립 검토 완료. 공유 환경 배포와 기본 모델 변경은 포함하지 않는다.
[결과·한계](model-comparison-2026-09-08.md), [게시 이미지 정본](published-images.json),
[기동·삭제 근거](model-comparison-evidence-2026-09-08.json)를 함께 읽는다.

## 게시 태그와 양자화

이미지 저장소는 `ghcr.io/sknetworks-family-aicamp/skn30-final-3team/general-serving`이다.
아래 태그는 2026-09-08 GHCR 조회에서 catalog의 digest와 일치함을 확인했다.
태그는 찾는 용도로 사용하고 실제 배포에는 catalog의 `image` 전체 digest를 사용한다.

| 게시 태그 | 실제 GPU 검증 | 재사용 판단 |
|---|---|---|
| `git-cfd05ebe09de26fd96fd3e5dec66be3aff146715` | Qwen3 14B·32B AWQ 각 AI 240·HTTP 36건 평가 | 기존 AWQ 비교 재현용. BnB는 플러그인 누락으로 기동 실패 |
| `git-9eea7a9e81e0ae582752384904cc91ffd413aec2` | BnB 플러그인 0.0.3과 vLLM 0.28 API 불일치 | **BnB 재사용 제외**, 장애 이력용 |
| `git-53b97bff79a44a08c26e61111bdcc64469023016` | Unsloth 27B BnB + 플러그인 0.0.2 기동·가중치 검증 | BnB 기동 재현용. 품질 점수는 없음 |
| `git-8bfd2c8c83d11c5b9b03b7e031a62ffacf128fef` | 공식 Qwen 27B FP8 AI 240·HTTP 36건 평가 | 선택한 공식 FP8 비교 재현용 |

모든 이미지는 고정 vLLM 0.28.0 기반이며 가중치를 포함하지 않는다. `GENERAL_MODEL_PROFILE`을
반드시 명시한다. 설정을 생략하면 기존 BnB 기본값이 유지된다. FP8 이미지는 AWQ·BnB 프로필의
CPU CLI 검사도 통과했지만 **같은 이미지에서 해당 프로필의 GPU 재평가를 한 것은 아니다**.
`evaluated`는 평가 실행 완료이며 품질 합격을 뜻하지 않는다. catalog는 `startup_only`,
`cpu_only`, `failed`, `not_in_image`를 별도로 표현한다. 새 양자화 이름이 같다는 이유만으로
다른 repository·revision의 호환성을 주장하지 않는다.

고정 실행 조건은 L40S 48GB 1대, 8K, 동시 추론 1건, 메모리 비율 0.85, eager,
thinking off, RunPod `allowedCudaVersions=["13.0"]`, `VLLM_ENABLE_CUDA_COMPATIBILITY=0`이다.
BnB·AWQ·FP8의 실제 loader는 [모델 프로필](model-profiles.json)에 고정돼 있다.
모델 전환은 재기동과 가중치 재로딩이 필요하다. 공유 F3 capability는 별도 명시 활성화 전까지 유지한다.

## 저장된 검토 결과 다시 검사

저장소 루트에서 GPU·DB·인증 없이 실행한다.

```bash
python3 infra/serving/verify_comparison.py
```

검사기는 HTTP warmup 제외 36건·3회, 고유 사례, 정확도·복원·삭제·p95·판정을 재계산하고
AI 요약·HTTP·게시 이미지·Pod 증거의 모델/revision·프로필·가중치·배포 digest를 대조한다.
과거 프로필 파일의 hash는 해당 이미지 source revision과 연결한다. 지금의 프로필 파일에
FP8이 추가됐다는 이유로 과거 AWQ 보고서의 hash를 덮어쓰지 않는다.
이 명령의 성공은 **근거의 정합성**이며 모든 모델의 품질 합격이나 현재 원격 자원 상태를 뜻하지 않는다.

## 원본에서 AI 검토 요약 다시 만들기

원본은 `ai/eval/chatbot/results/`의 ignored 로컬 파일이다. 공개 저장소에는 검토한 요약만 둔다.
다른 작업자는 원본이 없으면 아래 재평가 절차로 새 원본을 만들어야 한다. 출력 내용을 먼저
검토한 뒤 `--reviewed`를 사용한다. 자동 패턴 검사는 사람이 읽은 검토나 독립 에이전트의
원인 분석을 대신하지 않는다.

```bash
uv run --locked --project ai python ai/eval/chatbot/review_summary.py \
  --raw ai/eval/chatbot/results/qwen38-27b-fp8-20260908.json \
  --output /tmp/qwen38-fp8-reviewed-copy.json \
  --verify-against ai/eval/chatbot/validation/qwen38-27b-fp8-20260908.json \
  --reviewed
```

새 출력만 허용하고 기존 원본·요약을 덮어쓰지 않는다. 전체 80개 × 3회, fixture와 채점,
원본 SHA256·반복별 집계·실패 ID·허용된 metadata·민감 출력 패턴을 검사한다.
별도 해석 주석과 자동 집계는 구분하며, 코드 재생성이 사람의 검토를 자동 인증하지 않는다.

## 평가 당시 코드와 최신 통합 코드

원본 비교는 FP8 게시 소스 `8bfd2c8c83d11c5b9b03b7e031a62ffacf128fef`의
AI workflow·고정 80개 사례를 사용했다. 게시 catalog의 모델별 source revision으로 별도 checkout을
만들면 당시 실행 구성을 재현할 수 있다. 이후 검토 도구 추가는 프롬프트·fixture를 바꾸지 않았다.

평가 종료 후 `dev`의 #109가 Time Keeper 재연락 기능을 제거하여 최신 Backend 통합은
재연락 종류를 미지원으로 안내한다. 과거 모델 평가의 재연락 2개 사례는 역사적 비교 입력으로
보존하며 현재 지원 범위를 증명하지 않는다. 새 범위를 평가할 때는 새 버전의 fixture와 별도
원본 파일을 사용하고 이 보고서를 소급 채점하거나 덮어쓰지 않는다.

## 같은 모델 다시 평가

운영자가 위 catalog에서 프로필과 이미지 digest를 명시해 격리 Pod를 준비한다. 기존
[운영 도구](README.md)와 계정·비용·자원 소유 확인을 사용하며 이 검토 명령이 GPU를 생성하지 않는다.
공유 template을 덮어쓰지 않고 평가 Pod의 image·시작 명령·프로필을 override한다.
가중치 다운로드·실제 bytes 해시 검증과 인증된 `/ops/status` 준비 완료, RunPod API의
배포 digest·CUDA 환경을 대조한다. 모델 metadata만으로 실제 컨테이너 이미지를 증명하지 않는다.

ignored 개인 환경파일에는 `general-dev-gpu` endpoint와 키를 넣고 채팅·로그·보고서에는 기록하지 않는다.
아래 `<...>`는 catalog와 실제 검증 metadata에서 얻은 값으로 교체한다.

```bash
uv run --locked --project ai --env-file ai/.env.gpu-general \
  python ai/eval/chatbot/evaluate.py \
  --profiles-file infra/serving/model-profiles.json --model-profile qwen38-27b-fp8 \
  --endpoint-alias general-dev-gpu --deployment-image '<catalog의 image 전체 digest>' \
  --artifact-sha256 '<실제 검증 manifest SHA256>' --rounds 3 \
  --output ai/eval/chatbot/results/qwen38-27b-fp8-new.json

uv run --locked --project backend --env-file backend/.env.gpu-general \
  python backend/eval/chatbot_http.py \
  --profiles-file infra/serving/model-profiles.json --model-profile qwen38-27b-fp8 \
  --deployment-image '<catalog의 image 전체 digest>' \
  --artifact-sha256 '<실제 검증 manifest SHA256>' --rounds 3 \
  --output backend/eval/validation/chatbot-http-qwen38-27b-fp8-new.json
```

HTTP 명령은 별도 loopback PostgreSQL의 `TEST_DB_URL`과 CREATE DATABASE 권한이 필요하다.
기존 사용자 DB를 초기화하지 않는다. 매 실행의 임시 DB는 평가기가 제거하며, 평가용 Pod·컨테이너는
운영자가 정확한 소유 ID를 확인해 종료하고 삭제 증거를 기록한다. 종료 후 개인 endpoint 파일도 제거한다.

## 이번 검토에서 판정한 내용

| 검토 | 확인 및 수정·판정 |
|---|---|
| 실제 배포 식별 | 기반 이미지와 배포 wrapper를 구분하고 Pod inventory·전후 모델 metadata·실제 가중치 hash를 연결 |
| 모델 선택 경계 | F3 smoke의 기존 BnB 고정을 제거해 명시한 프로필을 전달. 기존 활성 모델·DB는 유지 |
| CUDA 재사용 | 기존 Pod도 native CUDA 설정을 확인하도록 수정. compatibility=1의 CUDA 803 실패 보존 |
| BnB 의존성 | 누락 플러그인 추가 후 0.0.3 API 불일치 확인, 0.0.2 고정·실제 loader 초기화 빌드 검사 추가 |
| FP8 검증 | 공식 revision·66개 shard hash·registry/CLI·실기동·240개 모델 평가·36개 HTTP 평가 대조 |
| 결과 한계 | FP8 지원94%·멀티턴100%·HTTP통과, 모호/미지원80%로 기존 평가기 전체 실패. 기준을 바꾸지 않음 |
| 독립 검토 | 구현 작성자와 다른 에이전트가 보안·기본값·배포 증거·반복 집계·HTTP p95를 재계산. 사람의 PR 승인은 별도 |

F4 합성 평가를 F3 업무 품질·모델 자체의 공격 저항성·공유 배포 성능으로 확장하지 않는다.
모델 세대·크기·양자화가 동시에 다르므로 양자화만의 효과로 해석하지 않는다.


## 최신 dev 병합 시 평가 기록의 경계

PR #99~#101의 workflow v3·필터 근거 검사·scorer v2·UI 경합 수정을 보존했다. 위 Qwen
평가는 이 변경 전의 역사적 결과이며 새 코드의 성능 합격 근거가 아니다. 원본에 scorer 버전이
없으면 당시 v1 규칙으로만 검토 요약을 재현하고, 명시된 v2는 현재 규칙을 사용한다. 알 수 없는
버전은 거절한다. 원본·요약 점수는 소급 변경하지 않으며 새 모델 평가는 별도 원본으로 수행한다.


이번 dev 통합의 기준은 `29d6ae7`이다. 새 AI·Backend 가상환경의 locked sync, AI 전체 416개,
Infra 209개·serving 23개, Terraform fmt·오프라인 init/validate를 검증했다. Qwen 3종 원본의
검토 요약 재생성은 각 240건의 기존 hash·집계와 일치했고, Luna 초기 원본도 기존 요약 검증기를
통과했다. 원격 plan/apply·이미지 재게시·모델 재평가는 실행하지 않았다.

격리 PostgreSQL 15에서 전체 migration 적용·재적용과 Backend 전체 691개 테스트를 통과했다.
AI·Backend의 지정 Ruff·포맷·Pyright도 통과했다. 임시 검증 DB는 작업 종료 시 제거한다.
