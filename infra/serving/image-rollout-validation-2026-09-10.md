# F2·general 이미지 게시와 공유 dev 적용 검증

- 기준일: 2026-09-10. 사용자는 F2 수정 PR #129의 `dev` 병합 후 새 이미지 게시·적용과 전체 기동 검증을 요청했다.
- 작업 기준: 병합된 `dev` 커밋 `50dc58402b00cd78fbc3252e891df2ece57396d5`에서 시작한
  `chore/infra-serving-image-rollout` 브랜치.
- F2 수정의 원인·로컬 및 AWS 비교는 [공백 반복 검증](f2-whitespace-validation-2026-09-10.md)이 정본이다.
  이번 기록은 수정 코드를 포함한 새 불변 이미지의 게시와 공유 환경 적용을 다룬다.
- 현재 판정: **두 이미지 게시·적용 및 공식 `dev-start`·`dev-verify` 성공.
  F2/general 직접 추론·앱 합성 요청·identity 검증 통과. GPU 모델은 별도 공급자 조회로 보완 확인했다.**

## 게시된 불변 이미지

| 항목 | F2 | general |
|---|---|---|
| 저장소 | `ghcr.io/sknetworks-family-aicamp/skn30-final-3team/f2-serving` | `ghcr.io/sknetworks-family-aicamp/skn30-final-3team/general-serving` |
| digest | `sha256:4566d037a02911902aa3cd624d2ff48d88125114cbbae9a2e922fc24eb262628` | `sha256:7d9598e8b8263fd5b43adb19cb778832c8f5189d8c6a2b4ba81eac3a06ceeb08` |
| 소스 SHA | `d5556dc3e460ec9d21080559f256e01ebbe997c4` | `f336dead312cc842207f0dd365c7d5ec719be6cd` |
| 게시 실행 | [34434463130](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34434463130) | [34434593863](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34434593863) |
| artifact 이름 | `runpod-template-d5556dc3e460ec9d21080559f256e01ebbe997c4` | `general-template-f336dead312cc842207f0dd365c7d5ec719be6cd` |
| 플랫폼 | `linux/amd64` | `linux/amd64` |

실행은 모두 성공했다. GHCR 태그는 `git-<소스 SHA>`이며, 실제 선택에는 위 digest를 사용한다.
두 artifact의 `template.json`을 각 소스 템플릿과 구조적으로 비교해 `image` 필드만 달라졌음을 확인했다.
general은 빌드 로그의 게시 태그·manifest digest와 artifact 값도 일치했다.
서로 다른 소스 SHA의 차이는 아래 테스트 import 주석 한 곳이며 F2 런타임 변경은 아니다.

## 게시를 막던 CI 오류와 수정

1. 최초 두 실행은 checkout에서 실패했다. `dev`가 `.worktrees/chatbot-ui-pr`와
   `.worktrees/f3-revert-116-117-118`를 gitlink로 추적하지만 `.gitmodules`가 없어,
   checkout의 인증 정보 정리 중 `git submodule foreach`가 exit 128로 끝났다.
   `d5556dc`에서 두 gitlink를 index에서만 제거하고 `.gitignore`에 `/.worktrees/`를 추가했다.
   실제 디렉터리는 보존했고, 같은 명령의 exit 0 및 추적 gitlink 0건을 확인했다.
2. general의 다음 실행 [34434465174](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34434465174)는
   checkout을 통과했으나 `test_verify_comparison.py`의 경로 설정 후 import에서 Ruff E402로 실패했다.
   `f336dea`에서 해당 import에 의도적인 경로 준비를 설명하는 `noqa: E402` 한 곳을 추가했다.
   린트 검사를 생략하거나 워크플로의 게시 조건을 완화하지 않았다.

general은 CI와 같은 Ruff `0.14.10` 검사, 런타임 테스트 40개 및 `compileall`을 통과했다.
F2도 게시 워크플로의 Ruff·런타임 검사와 이미지 빌드 시작 인자 검증을 통과했다.
이 검사들은 GPU에서의 실제 추론·품질 평가를 대신하지 않는다.

## 공유 선택 적용과 기동 검증 범위

`dev-stop` 완료 후 앱 ASG 0, RDS stopped를 확인한 상태에서 catalog를 갱신하고
공식 `ai-select`로 두 새 digest를 공유 선택
`4049d41d-b013-4ae6-9888-593ca20046df`에 저장했다.
F2는 `consultation-v3`·RTX 4090 24GB, general은 `qwen38-27b-fp8`·L40S 48GB를 유지한다.
이전 이미지와 평가 근거는 이력으로 보존하며 새 이미지로 승계하지 않는다.

| 단계 | 상태 | 확인 범위 |
|---|---|---|
| GHCR 게시 및 artifact 검토 | 완료 | 위 정확한 SHA·digest·템플릿 비교 |
| 정지 상태의 catalog 및 공유 선택 갱신 | 완료 | 두 digest 저장; 모델·GPU 선택 유지 |
| Terraform 계획·적용 및 후속 drift | 완료 | 기존 CloudWatch Alarm SNS 구독 1건 복구, 후속 변경 0건 |
| 두 RunPod Template 적용 | 완료 | 등록·선택 image 일치 및 원격 Template 대조 |
| 공식 `dev-start` 실행 | 성공 | 동일 설정의 재시도 exit 0 |
| 새 이미지의 GPU 준비·직접 추론 | 통과 | F2 SLLM/STT 및 general readiness·직접 probe |
| API·Worker 기동 및 F2/general 앱 합성 요청 | 통과 | 공식 lifecycle의 두 workload 앱 smoke 성공 |
| ALB·CloudFront 외부 진입 | 통과 | 앱 대상 healthy, 프런트엔드 HTTP 200 |
| 강화된 `dev-verify` | 통과 | exit 0, 두 workload의 직접 추론·앱 요청·identity 일치 및 VRAM 관측 |

### 실행 중 오류와 복구 근거

첫 기동 시 F2 Pod 생성 `POST /pods`가 HTTP 500으로 실패했다. lifecycle의 자동 정리 후
관리 Pod 0개를 확인했다. RTX 4090과 L40S Secure 재고·요금 및 Template을 읽기 전용으로
재확인했으며, 같은 설정의 공식 `dev-start` 재시도에서는 두 Pod 생성과 전체 기동이 성공했다.
500의 원인은 확정하지 못했다. 재시도 성공을 재고 부족·이미지 오류 등 특정 원인의 증거로 해석하지 않는다.

- 기동 Pod: F2 `uexuh6k98ybabx`, general `g0n8ikzxy0p42g`.
- 앱 호스트: `i-002c7a3a8d7e9e419`. 이전 합성 검증 revision `d-PVP2YSOPK`를
  복원한 CodeDeploy `d-WWXKZV5QK`는 2026-09-10 13:22:19 KST에 성공했다.
  `WITHOUT_TRAFFIC_CONTROL`로 `ValidateService`를 포함한 모든 단계가 성공했다.
- DB 사전 확인: pending 0건, 현재 대상 모두 호환, 모델 설정 변경 0건.
- 최종 컨테이너 확인: `brokerage-dev-api-1`과 `brokerage-dev-worker-1` 모두 running·healthy.
- 별도 읽기 확인: ALB의 해당 호스트 healthy, CloudFront `E326VIF3YYXAO7` Enabled·Deployed,
  프런트엔드 `GET /` HTTP 200·`text/html`, 문서 제목 `집크크`.
- F2 시작 로그에서 xgrammar 공백 제한 적용과 엔진 시작을 확인했다. general은 다운로드 완료,
  `model-weights-verified`, 가중치 로딩과 앱 시작 완료 후 공식 probe를 통과했다.

### `dev-verify` 측정 결과와 한계

| 대상 | 확인 시각 (UTC) | 직접 추론 응답시간 | 관측 device VRAM peak / total | 표본 수 | 결과 |
|---|---|---|---|---|---|
| F2 SLLM | 2026-09-10 04:45:09 | 2.658초 | 21,561 / 24,564 MiB | 6 | 직접 추론·앱 요청 통과, 모든 identity 검사 일치 |
| F2 STT | 2026-09-10 04:45:09 | 2.001초 | 21,561 / 24,564 MiB | 5 | 직접 추론·앱 요청 통과, 모든 identity 검사 일치 |
| general | 2026-09-10 04:47:15 | 3.346초 | 39,099 / 46,068 MiB | 7 | 직접 추론·앱 요청 통과, image·model·profile·revision 일치 |

F2 두 엔진은 같은 GPU를 공유하므로 device VRAM 값을 더하지 않는다. 수치는 검증 요청 중
수집된 표본에서 관측한 peak이며, 전체 실행 시간의 절대 최대나 프로세스별 사용량이 아니다.
RunPod REST 응답에 `machine.gpuTypeId`가 없어 두 workload의 `hardware_verification`은
`unavailable`로 보고됐다. 공식 검증의 해당 필드를 성공으로 바꾸지 않았다. 별도 읽기 전용
GraphQL `myself.pods.machine.gpuDisplayName` 조회에서는 F2 Pod가 `RTX 4090`, general Pod가
`L40S`임을 확인해 선택한 하드웨어와 대조했다. 이 공급자 조회 근거로 실제 GPU 모델 확인을 보완한다.
합성 요청 성공은 모델 품질 평가나 AWS↔RunPod 왕복 전환 검증 완료를 뜻하지 않는다.

catalog의 새 general 이미지·FP8 조합은 이 실제 기동 근거에 따라 `startup_only`로 기록했다.
다른 모델 조합과 이전 wrapper의 품질 평가를 승계하지 않았으며, catalog 반영 후 런타임 테스트
40개를 다시 통과했다.

새 general 이미지는 CPU·CLI 빌드 검증 근거만으로 이전 wrapper의 품질 평가를 승계하지 않는다.
실제 GPU 준비와 추론이 확인된 뒤에도 `startup_only`와 모델 품질의 `evaluated`를 구분한다.
시작·실패 정리·종료는 [개발자 운영](../operations/README.md)의 lifecycle을 따른다.
기동 요청의 `--hours 2`는 비용 추정 입력이며 자동 종료 타이머가 아니다.

현재 두 GPU를 실행 상태로 유지했다. 확인한 GPU 견적은 F2 $0.74/시간, general $1.09/시간,
합계 $1.83/시간이며 앱·RDS·스토리지·네트워크 비용은 별도다. 운영 소유자는 프로젝트 Infra 운영자이며,
사용 후 `just dev-stop`으로 종료한다. 기존 2026-09-23까지 누적 300,000원 참고 상한은 변경하지 않았다.
