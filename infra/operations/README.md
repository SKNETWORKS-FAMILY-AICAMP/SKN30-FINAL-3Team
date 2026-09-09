# 개발자 인프라 운영

모든 명령은 `infra/`에서 실행한다. 저장소 루트에서는 `just -f infra/justfile <명령>`도 가능하다.
새 워크트리에는 개인 `.env`, Terraform 입력과 모델 파일이 복제되지 않는다. 기존 계정에 연결할 때는
`infra/.env.example`을 `infra/.env`로 복사해 계정 ID를 넣고
`just setup-existing 2026-09-23`을 사용한다. 날짜는 현재 dev 환경 종료일이며 변경 시 팀 결정에 맞춘다.

## 매일 사용하는 명령

| 목적 | 명령 | 변경·비용 |
|---|---|---|
| 로컬 설정 확인 | `just env-doctor` | 로그인·네트워크 없음; 주요 모드·출처만 표시, 비밀값 비출력 |
| 옛 변수명·권한 정리 | `just env-fix` | 해당 checkout의 ignored `.env`만 수정; 충돌 시 중단 |
| AWS·RunPod·Secret·등록 확인 | `just doctor` | 읽기 전용, 기동·모델 호출 없음 |
| 배포 준비의 누락 확인 | `just release-ready` | 읽기 전용; 선택 누락·알려진 불량 이미지 차단 |
| F2 모델 목록 | `just f2-releases` | 로컬 catalog만 조회 |
| F2 모델 선택 | `just f2-select consultation-v3` | offline SSM 선택만 저장; GPU 생성·DB 변경 없음 |
| 기동 후 합성 검증 | `just dev-verify` | F2/general 앱 경유 추론; 모델 호출 비용 발생 |
| F2만 검증 | `just dev-verify f2` | 새 파인튜닝 모델의 F2 연결 검증 |
| 정상 시작·종료 | `just dev-start` / `just dev-stop` | 기존 전체 lifecycle; 시작은 비용 발생 |

`doctor`의 INFO/offline은 서비스 정상 동작을 뜻하지 않는다. FAIL은 필요한 조치가 있고,
WARN은 확인할 조건이 있다는 뜻이다. JSON은 `python3 scripts/operations.py doctor --json`으로
출력할 수 있다. 오류 원문·Secret·전체 접속 URL은 출력하지 않는다. 주기적 감시 서비스는 만들지 않는다.

## 최초 배포 또는 오래된 앱 revision 교체

이번 변경 후 실제 기동·추론은 사용자가 실행한다. 먼저 변경을 팀 검토 후 `dev`에 병합한다.
아래는 shared RunPod를 쓰는 첫 실행 순서다. AWS GPU를 쓰려면 기존 [통합 LLM runbook](../serving/README.md)의
AMI·GPU capacity plan 절차를 추가로 따른다. GPU 종류는 사용자 가용 자원·예산에 맞게 명시한다.

1. `just env-doctor`, `just doctor`로 상태를 확인한다. 로그인 만료면
   `aws login --profile skn30-bootstrap` 후 다시 실행한다.
2. `just image-publish f2 dev`, `just image-publish general dev`로 수정 이미지를 게시한다.
   `gh run list`, `gh run watch <run-id>`로 성공을 기다리고 `gh run download <run-id>`로
   `template.json` artifact를 받는다. 성공한 최종 image digest를 사용하고 vLLM base digest와 혼동하지 않는다.
   이미 검증된 general 이미지를 재사용하려면 [catalog](../serving/published-images.json)의 정확한
   image/profile 조합을 선택한다. `evaluated`는 품질 승인 표시가 아니다.
3. 기존 F2/general Console Template을 각 artifact와 일치시키고 `runpod-register-plan → runpod-register`,
   `runpod-general-register-plan → runpod-general-register`를 실행한다. 인자는 이미지 digest·Template ID·registry ID다.
   Secret은 Console 참조를 유지한다. 기존 일회성 불량 이미지로 생성하면 안 된다.
4. 새 모델이 S3에 게시됐는지 확인한 뒤 `just f2-select consultation-v3`를 실행한다.
   general 모델은 Terraform의 `general_model_selection`과 GPU profile을 함께 선택한다.
   현재 기본값은 `vllm` / `Qwen/Qwen3.8-27B-FP8`이며 GPU profile은 `qwen38-27b-fp8`이다.
   공개 SSM 설정은 검토한 Terraform plan으로 반영하고, 아래 명령은 GPU 선택만 저장한다.

   ```bash
   just ai-configure general runpod 'NVIDIA L40S' --model-profile qwen38-27b-fp8 --apply
   just release-ready
   ```

**vLLM 최초 배포 조건:** 아래 앱 배포를 완료하려면 general endpoint가 먼저 준비되어 있어야 한다.
새 Worker는 미구성 provider로 기동하지 않으므로 GPU가 offline인 상태의 앱 배포는 readiness를 통과하지 못한다.
이미지·Template·SSM·선택 준비와 실제 기동을 구분하고, 사용자 기동 창에서 GPU 연결을 준비한 뒤 앱을 배포한다.
`dev-prepare-app`만으로 GPU나 앱 검증까지 완료됐다고 판단하지 않는다.

5. 새 환경변수 계약으로 최초 전환할 때 `just dev-first-deploy-plan` → `just dev-first-deploy-show`로 환경변수 삭제·추가, 비용·자원을 함께 검토하고
   **최초 앱 배포에는 `just dev-prepare-app`**을 실행한다. 선택 GPU를 기동하고 인증·직접 합성 추론을 검증한 뒤 endpoint를 게시하고 RDS·앱 호스트를 시작한다.
   이 시점부터 GPU 비용이 발생한다. 앱 경유 smoke는 최신 앱 배포 후 사용자가 수행한다.
   최초 plan은 CodeDeploy의 ASG 자동 배포 연결을 해제하고 정확한 앱 태그로 배포 대상을 제한한다.
   구 revision이 새 설정으로 자동 기동되는 것을 막는다. 기존 `dev-deep-start`는 최초 전환에 사용하지 않는다.
6. `just app-deploy`로 최신 dev 통합 Pipeline을 실행하고 CodePipeline에서 Succeeded를 확인한다.
   migration과 Frontend 배포도 포함된다. 실패 시 CodeBuild/CodeDeploy의 해당 단계에서 해결하고 진행한다.
   새 revision의 Succeeded를 확인한 뒤 `dev-deep-start-plan → dev-deep-start-show → 승인 → dev-deep-start`로
   `automatic` 연결을 복구한다. 이 단계부터 앱 경유 합성 검증이 포함된다.
7. 사용자가 `just dev-start`로 선택한 GPU·endpoint를 준비한다. 이 명령에는 합성 추론도 포함된다.
   기존 DB 선택을 바꿔야 한다면 API/Worker를 drain해 중지한 maintenance 상태에서
   `just ai-activate-general <brokerage-id> POSITION_CARD`처럼 capability 하나씩 반영한다.
   허용값은 `POSITION_CARD`, `BROKERAGE_JUDGMENT`, `CHATBOT`이며 주입된 provider/model을 사용한다.
   모델 명령은 자동 중지·재기동·추론을 하지 않는다. 중지된 상태를 검사하고 반영 후에도 유지한다.
   DB에 남은 대기·진행 요청이 있으면 변경을 거부한다. 반영 후 재기동·검증은 사용자가 수행한다.
8. `just dev-verify`를 실행한다. 새 F2만 우선 확인하려면 `just dev-verify f2`를 사용한다.
   검증 중 원문 음성을 제공하지 않고 저장소 합성 fixture를 사용한다.
9. 사용 후 `just dev-stop`, `just doctor`로 잔여 자원을 확인한다. 장기 정지는 기존
   `dev-deep-stop-plan → dev-deep-stop-show → dev-deep-stop` 절차를 사용한다.

반복 사용은 `dev-start → dev-verify → dev-stop`이다. `dev-verify`는 앱·대상 endpoint가 꺼져 있으면
추론 전에 중단하며 자동 기동·fallback·모델 변경을 하지 않는다. F2 응답이 맞는지는 합성 연결 검사와
별개로 확인한다. 왕복 전환·부하·모델 품질 평가는 이 명령의 수용 범위가 아니다.

## 실패했을 때

| 표시 | 다음 행동 |
|---|---|
| 로그인/권한 조회 실패 | `aws login --profile skn30-bootstrap`; 개인 계정과 역할 권한 확인 |
| 옛 이미지/Template 불일치 | 성공 workflow artifact로 Template 수정, register-plan부터 재실행 |
| S3 release checksum 불일치/없음 | 정확한 원본 bundle을 inspect/publish; 기존 release 덮어쓰기 금지 |
| 앱 없음/배포 실패 | `dev-prepare-app`·통합 배포 단계 확인. 새 revision 배포 전에 GPU를 반복 생성하지 않음 |
| endpoint offline | `doctor`에서 선택을 확인하고 `dev-start` 또는 명시한 `ai-switch` 재시도 |
| 합성 요청 실패 | `dev-status`와 CloudWatch 안전 로그 확인; 실패 상태를 성공으로 표시하지 않음 |
| 오래되거나 변경된 plan | 해당 `*-plan` → `*-show` 재실행; 검토하지 않은 새 plan을 바로 적용하지 않음 |

## 파일·비용 관리

saved plan은 생성 순간부터 600 권한이며 입력 fingerprint와 24시간 유효기간을 갖는다.
`*-apply`, deep start/stop, destroy는 입력·파일이 바뀌면 실행을 거부한다. 새 checkout의 과거 plan은
재사용하지 않는다. 직접 `terraform apply`하면 이 로컬 guard를 거치지 않으므로 just를 진입점으로 사용한다.

`serving-validation.auto.tfvars.json`처럼 검증용 이름의 파일도 Terraform은 자동 로딩한다.
`just gpu-profiles-import <검토한 파일>`로 GPU 프로필만 `gpu-profiles.auto.tfvars.json`에 준비하고,
동일 내용인지 확인한 뒤 예전 validation 파일을 root 밖으로 옮긴다. 프로필은 AMI·image·EBS만,
`serving-capacity.auto.tfvars.json`은 생성 대상만 소유한다. 비밀값은 어느 파일에도 넣지 않는다.

학습·개인 Pod/Template/registry는 [자원 관리표](resources.md)에서 담당자·보존 기한을 확인한 뒤
정리한다. 중지 Pod의 volume, AWS stopped EBS/RDS도 비용이 남는다. Budget 자동 제어는 도입하지 않는다.
RDS 자동 재시작 시각은 `doctor`에 표시된다.

설정·비밀 정본과 반영 방법은 [configuration.md](configuration.md),
적용 현황 정본은 [인벤토리](../../.agents/skills/infra/references/resource-inventory.md),
새 F2 전달 기록은 [모델 목록](../runpod/releases.json)과 [전달 기록](../runpod/releases.md)을 따른다.
이번 변경의 테스트 결과·bootstrap 적용·모델 게시 결과는 [검토 기록](change-review.md)에서 확인한다.
