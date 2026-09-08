# Qwen 3모델 비교 — 2026-09-08

상태: 프로필 구현·단위 검증 완료, 실제 모델 평가 진행 중. 공유 dev 배포·활성 모델 변경은 포함하지 않는다.

## 범위와 재현 계약

사용자 요청으로 `qwen3-14b-awq`, `qwen3-32b-awq`, `qwen38-27b-bnb`를 비교한다.
마지막 프로필은 `unsloth/Qwen3.8-27B-unsloth-bnb-4bit`이며 FP8 모델로 대체하지 않는다.
프로필 정본은 [model-profiles.json](model-profiles.json)이다. 모델 repository·불변 revision·
가중치별 크기/SHA256·공식 vLLM base image digest와 실행 옵션을 함께 고정한다.

- 공통 조건: vLLM 0.28.0 linux/amd64, L40S 48GB 1대, 8K context, 동시 추론 1건,
  GPU 메모리 비율 0.85, eager, thinking off. AWQ와 BnB의 loader만 다르다.
- 가중치는 이미지에 포함하지 않는다. GPU에서 고정 revision을 다운로드한 후 실제 파일을
  해시 검증한다. 검증 결과는 인증된 `/ops/status`에 최소 metadata로 제공한다.
- 공식 vLLM 0.28.0 이미지에는 bitsandbytes가 없어 `runtime-requirements.txt`로
  0.50.2와 wheel hash를 고정해 설치한다. torch 등 기존 의존성은 교체하지 않는다.
- `runtime_image`는 공식 base image, `deployment_image`는 실제 게시한 general-serving
  wrapper image다. 두 digest를 구분하며 세 모델에 같은 wrapper를 적용한다.
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

진행 중. 실제 실행 결과·정확도·지연·비용·남은 제한을 평가 종료 후 기록한다.
