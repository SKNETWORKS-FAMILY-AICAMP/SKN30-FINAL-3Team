# 개발자 인프라 운영

공유 dev의 설정은 `ai-select`, 실행은 `dev-*`, 새 앱 배포는 `app-deploy`로 관리한다.
모든 명령은 `infra/`에서 실행한다. 루트에서는 `just -f infra/justfile <명령>`을 사용한다.
이번 통합은 코드·자동 검사 범위이며 **클라우드 적용, 새 이미지 게시와 실제 기동·추론은 사용자가 수행한다.**
과거 후보 검증을 새 이미지·release의 검증 완료로 간주하지 않는다.

**현재 catalog에 고정된 F2 `ca2cfefb…`와 general `801473c8…` 이미지는 새 identity/VRAM
계측 코드보다 이전 이미지다. 이 이미지 그대로는 강화된 `dev-verify`에서 계측 누락으로 실패한다.**
아래 최초 배포 2단계의 이미지 게시·artifact 검토·Git catalog 변경 후, 완전히 정지된 상태에서
`ai-select`로 새 digest를 저장해야 한다. 이번 구현에서는 이미지 게시를 실행하지 않았다.

새 checkout에는 개인 `.env`, Terraform 입력과 모델 파일이 복제되지 않는다.
`infra/.env.example`에서 `infra/.env`를 준비하고 계정 ID를 넣은 뒤
`just setup-existing 2026-09-23`으로 기존 계정 입력을 구성한다. 종료일은 현재 팀 기준이며
변경할 때는 팀 결정에 맞춘다. 로그인 만료 시 `aws login --profile skn30-bootstrap`을 사용한다.

## 선택·상태·기동 명령

| 목적 | 명령 | 동작 |
|---|---|---|
| 로컬 변수·소유권 검사 | `just env-doctor` / `just env-fix` | 후자는 해당 checkout의 ignored 개인 파일만 정리 |
| 클라우드 등록·구조 검사 | `just doctor` / `just release-ready` | 읽기 전용; 서비스 기동 성공 표시가 아님 |
| 공유 dev 선택 | `just ai-select` | 작업·클라우드·GPU·모델 메뉴, 전후 비교 후 확인하여 SSM 저장 |
| 선택·적용·실제 상태 확인 | `just dev-status` | 선택 ID, 마지막 적용 단계와 실제 자원·검증 상태 구분 |
| 시작 계획만 확인 | `just dev-start-plan --hours 2` | 로컬 Terraform plan·Template 차이·비용 항목 표시, 기동 없음 |
| 최초 revision 준비 | `just dev-prepare-app --hours 2` | 검토 후 maintenance 호스트·모델 준비, 앱 배포는 별도 |
| 통합 앱 배포 | `just app-deploy` | 최신 dev Pipeline 실행; 완료는 Pipeline에서 확인 |
| 시작 | `just dev-start --hours 2` | 계획·비용 확인, DB 대상 확인, 모델 준비·반영 후 앱 시작 |
| 합성 검증 | `just dev-verify` / `just dev-verify f2` | 기동된 서비스 검사·추론; 자동 기동·선택 변경 없음 |
| 일반 종료 | `just dev-stop` | 앱·Worker drain, 관리 GPU 종료, 앱 호스트·RDS 정지 |

`ai-select`는 앱 호스트와 모든 관리 AWS GPU가 정지하고 RunPod Pod가 삭제되어 있으며
두 endpoint가 offline일 때만 저장한다. 실행 중 변경하려면 먼저 `dev-stop`을 수행한다.
선택 단계는 GPU를 생성하거나 DB 모델을 바꾸지 않는다. 기존 RunPod 선택값도 그대로 보존한다.

명시형은 다음처럼 사용한다. `--apply`를 생략하면 전후 비교만 보여준다.

```bash
just ai-select --workload f2 --cloud runpod --hardware-profile runpod-a5000-24gb --release consultation-v3 --apply
just ai-select --workload general --cloud runpod --hardware-profile runpod-l40s-48gb --model-profile qwen38-27b-fp8 --apply
# AWS 선택 예시. 기동 전 검토한 AMI/EBS 프로필을 별도로 준비한다.
just ai-select --workload f2 --cloud aws --hardware-profile aws-g6-2xlarge --release consultation-v3 --apply
```

기존 `f2-select`, `ai-configure`, `ai-switch`는 같은 정지 조건·카탈로그 검증·SSM 저장을 사용한다.
`ai-switch`는 정지 후 선택을 바꾸는 호환 명령이며, 실행 중 GPU 교체나 앱 재시작을 수행하지 않는다.
허용 프로필·메모리와 검증 근거는 [서빙 구성](../serving/README.md), 저장 책임은
[설정 관리](configuration.md)가 정본이다. local의 개인 OpenAI 설정은 이 명령의 대상이 아니다.

## 처음 배포하는 순서

1. `env-doctor → doctor → release-ready`로 계정·입력·등록 누락을 확인하고 `ai-select`로
   F2와 general 선택을 확인한다. AWS는 검토한 AMI·EBS 프로필을
   `just gpu-profiles-import <파일>`로 준비한다. GPU가 없어도 조회·선택은 가능하다.
2. 변경 코드가 dev에 병합된 뒤 `just image-publish f2 dev`, `just image-publish general dev`를
   실행한다. `gh run list`·`gh run watch <run-id>`로 성공을 확인하고
   `gh run download <run-id>`로 받은 artifact의 완성 이미지 digest·시작 명령을 검토한다.
   F2는 `serving/hardware-profiles.json`의 `f2_image`, general은
   `serving/published-images.json`의 새 항목과 `hardware-profiles.json`의 기본 image ID를
   Git 변경으로 검토하여 갱신한다. 게시 성공을 GPU 검증 성공으로 표시하지 않는다.
   기존 F2 이미지 항목은 `f2_image_history`에 보존하여 저장된 이전 선택도 계속 읽을 수 있게 한다.
   **앱·Worker·관리 GPU가 완전히 정지된 상태에서 `ai-select`를 다시 실행해 두 작업의 새 digest를
   전후 비교하고 저장한다.** Template만 수정하거나 태그를 재사용해도 SSM 선택은 바뀌지 않는다.
3. 최초 RunPod Secret·registry·Template 생성은 [RunPod 준비](../runpod/README.md)를 따른다.
   이후 **기존 Template** 수정은 시작 계획에 차이를 표시하고 확인 후 API로 반영·재조회·SSM 등록한다.
   자동 신규 Template 생성이나 Secret 회전은 하지 않는다.
4. `just dev-prepare-app --hours 2`를 실행하고 Terraform 변경·Template 차이·비용을 검토한다.
   확인 후 RDS·maintenance 호스트와 필요한 모델을 준비한다. 구 revision이나 유지보수 CLI가 없으면
   `awaiting-app-deploy`에서 멈춘다. GPU·RDS가 준비되어 있으면 이때부터 비용이 발생한다.
5. `just app-deploy` 후 통합 Pipeline 성공을 확인한다. CodeDeploy는 maintenance 상태에서
   migration·이미지·구성 준비를 수행하며 API·Worker를 시작하지 않는다. `dev-prepare-app`이나
   Pipeline 성공만으로 앱 기동 검증이 끝난 것은 아니다.
6. `just dev-start --hours 2`에서 같은 계획을 확인한다. RDS의 중개사 ID·capability별 현재 모델을
   보고 바꿀 대상만 `7:CHATBOT,7:POSITION_CARD`처럼 명시한다. 전후 비교를 확인한 뒤 모델 준비가
   통과하면 선택 대상에만 새 DB 버전을 추가한다. 마지막에 API·Worker와 앱 경유 합성 검증을 실행한다.
7. `just dev-verify`로 선택한 release·모델·이미지와 합성 요청 결과를 확인하고, 사용 후
   `just dev-stop`, `just dev-status`로 잔여 자원을 확인한다.

최초 순서는 `ai-select → dev-prepare-app → app-deploy → dev-start`다. 이후 일반 사용은
`dev-start → dev-verify → dev-stop`, 구성을 바꿀 때는 `dev-stop → ai-select → dev-start`다.
앱 revision을 바꾸는 `app-deploy`는 시작 명령에서 자동 실행하지 않는다. 유지보수 배포 모드를
수동으로 `automatic`으로 복구할 필요가 없다. 통합 시작 계획이 `maintenance`를 유지하고,
성공한 마지막 단계에서만 앱·Worker 시작을 허용한다.

일반 stop으로 앱 ASG가 0이 되면 다음 시작에서 앱 호스트가 새로 만들어질 수 있다.
이 경우 이전 `dev-start`가 실제 테스트 호스트의 배포 성공과 앱 합성 검증을 확인해 기록한
**정확한 CodeDeploy S3 revision만** maintenance 상태에서 복원한다. 기록한 배포 ID와 revision
해시가 일치하는지 검사하며 최신 빌드를 임의로 고르거나 CodePipeline을 시작하지 않는다.
검증 기록이 없는 최초 실행은 위 `dev-prepare-app → app-deploy → dev-start` 순서가 필요하다.
기록이 잘못됐거나 복원이 실패하면 maintenance를 유지하고 명시적 앱 배포를 안내한다.

## DB 모델 변경과 실패 처리

DB 대상은 GPU 기동 전 RDS·maintenance 호스트에서 조회한다. 허용 capability는
`POSITION_CARD`, `BROKERAGE_JUDGMENT`, `CHATBOT`이다. 명시하지 않은 대상과 업무 데이터·기존
run snapshot은 보존한다. 같은 모델이면 버전을 추가하지 않으며 클라우드만 바뀌어도 DB 이력은 유지한다.

대기·진행 요청이 있거나 선택하지 않은 비호환 활성 모델이 남으면 앱 기동을 차단한다.
대상을 추가해 다시 확인하거나 이전 모델을 선택한다. 확인한 DB snapshot이 바뀌면 다시 조회·확인한다.
준비 중인 DB 변경은 Backend CLI의 단일 트랜잭션으로 적용하며 Infra가 직접 SQL을 쓰지 않는다.

| 실패 | 다음 행동 |
|---|---|
| 선택·Template·등록·이미지·입력 변경 또는 plan 만료 | `dev-start-plan`부터 재검토; 이전 plan 재사용 금지 |
| 새 호스트/CLI 없음 | 이전 검증 revision이 있으면 정확한 revision 복원; 기록 없으면 `dev-prepare-app → app-deploy → dev-start` |
| 검증 revision 변경/복원 실패 | maintenance 유지, 배포 기록·CodeDeploy 확인 후 명시적 `app-deploy` |
| 비호환 DB 모델/대기 요청 | 대상·요청 상태 확인 후 명시적으로 해결; 자동 전체 변경 없음 |
| S3 release/hash/다운로드 실패 | 고정 release와 접근·만료 시간을 확인; 기존 release 덮어쓰기 금지 |
| GPU 부족/모델 로딩·합성 요청 실패 | `dev-status`와 안전 로그 확인; 다른 GPU나 모델로 자동 변경하지 않음 |
| 실패 후 잔여 자원 | `dev-status → dev-stop`; 캐시 제거는 deep 종료 plan 검토 후 수행 |

실패한 시도에서 만든 RunPod는 삭제하고 이번에 시작한 AWS GPU는 정지한다. 기존 무관한 자원은
보존하며 RDS·maintenance 호스트·AWS EBS 등 잔여 비용과 정리 명령을 표시한다. 실패를 적용 성공으로
기록하지 않는다. DB 반영 후 후속 앱 검증이 실패해도 이전 버전을 삭제하거나 자동 되돌리지 않는다.

## 비용·deep 종료·검증 기록

현재 공급자 견적을 확인해 `--hourly-usd f2=RATE --hourly-usd general=RATE --hours 2`로 전달한다.
RATE는 USD/시간의 양수이며 생략하면 TTY에서 작업별 현재 견적을 묻고 계산 결과를 다시 보여준다.
비대화형 실행에서는 요금을 명시해야 하며 과거 측정 요금을 현재 견적으로 사용하지 않는다.
**hours는 예상 비용 계산용이며 자동 종료 시간이 아니다.** 무요청 GPU도 과금되며 EBS·IPv4·RunPod disk·
앱·RDS·edge·세금은 별도다. 현재 계정 예산과 종료일은 변경하지 않는다.

장기 종료는 `dev-deep-stop-plan → dev-deep-stop-show → 승인 → dev-deep-stop`을 사용한다.
선택·release·DB·등록 정본은 보존하고 GPU·캐시·edge를 검토된 범위에서 제거한다.
`dev-deep-start`는 `dev-start`와 같은 계획·확인·복구 흐름을 사용한다. 기존 `dev-deep-start-plan/show`는
낮은 수준 Terraform 검토용 호환 명령이며 그 plan으로 통합 선택 검증을 우회하지 않는다.
실제 시작은 `dev-serving.tfplan`을 새로 생성·확인하며 edge/GPU 활성 입력과 선택된 AWS 생성 대상을
복원한다. saved plan·입력 fingerprint 검사 → 적용 → drift 확인을 통과한 뒤 RDS·호스트를 준비한다.

saved plan과 metadata는 Git에서 제외하고 600 권한·24시간 유효기간을 적용한다.
Terraform 입력·plan hash에 공유 선택 ID/내용·이미지·Template 등록 상태를 함께 묶어 확인한다.
새 checkout의 plan을 복사하거나 직접 `terraform apply`로 통합 guard를 우회하지 않는다.

`dev-verify`는 F2 두 엔진·합성 음성/구조화 응답과 general·Backend 연동을 검사한다.
계측 가능한 이미지에서는 검증 중 관측한 VRAM·응답시간·오류도 확인한다. 관측값은 설정한
GPU 메모리 비율이나 검증 구간 밖의 절대 최대치가 아니다. 일반 재기동, deep 재생성, AWS↔RunPod
전환은 각 실행 뒤 검증하고 조합별 결과를 남긴다. 이 명령이 왕복 전환을 자동 실행하지는 않는다.

현재 자원은 [인벤토리](../../.agents/skills/infra/references/resource-inventory.md),
과거 적용·검토는 [change-review.md](change-review.md), 모델별 검증 근거는
[서빙 검증](../serving/validation.md)을 확인한다. 진단 INFO/offline·등록 성공·품질 평가는 서로 다른 상태다.
