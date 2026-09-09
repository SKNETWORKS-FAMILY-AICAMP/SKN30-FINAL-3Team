---
status: 구현됨
updated: 2026-09-09
---

# ADR-0024: 공유 선택 기반 시작 계획·Template 조정·실패 복구

- 상태: 사용자 구현 승인·코드/오프라인 자동 검증. 팀 병합·공유 Terraform 적용·새 이미지 게시·GPU 기동/추론은 미수행이다.
- 공통 정책: [프로젝트 ADR-0036](../../../project-wiki/references/decisions/ADR-0036-shared-dev-serving-selection.md).
- 부분 대체: ADR-0020의 기존 Template 수동 수정, ADR-0022의 분리 선택/전환/시작 경로,
  ADR-0023의 별도 general_model_selection 입력과 최초 배포 뒤 automatic 복구 절차.
- 유지: 최초 Console Secret·registry·Template 준비, Terraform AWS 소유권, ignored plan·승인·drift 확인,
  운영자 순차 실행, Secret 비노출, 기존 전원/캐시와 계정 예산 경계.

## 카탈로그와 계획

F2 기본은 RunPod RTX A5000 24GB 또는 AWS g6.2xlarge/L4 24GB, general은 RunPod L40S 48GB 또는
AWS g6e.2xlarge/L40S 48GB다. 실제 profile·허용 모델·정확한 검증 근거는 Git 카탈로그가 정본이다.
F2 새 release와 A5000의 정확한 조합은 사용자 검증 대기다. 더 작은 CPU/GPU 후보를 임의로
허용하지 않고 공급 부족 시 자동 증설·대체하지 않는다. 범용 기본 후보는 FP8이며 배포 profile은 필수다.

`dev-start`·`dev-prepare-app`·`dev-deep-start`는 공통 계획기를 쓴다. SSM 선택에서 AWS 생성 대상·
고정 이미지와 앱 provider/model·maintenance 배포 모드를 생성한다. 검토한 AMI·EBS 입력은 유지한다.
AWS-only 작업에는 RunPod Template 등록을 요구하지 않는다. Terraform plan 해석값과 생성 입력이
다르면 진행하지 않는다. 형식·검증·계획·확인·saved plan 적용·같은 입력의 drift 확인 순서를 지킨다.

계획 metadata에 선택 ID/내용 해시·이미지·현재 AWS 자원·RunPod Template/등록 상태를 묶고,
기존 로컬 입력 fingerprint·plan hash·24시간 유효기간을 함께 검사한다. 변경되면 새 계획을 검토한다.
현재 공급자의 시간당 USD 요금과 예상 시간을 명시 또는 TTY로 받아 비용을 확인한다. 예상 시간은
자동 종료 타이머가 아니며 storage·IPv4·RDS·앱·edge 등 별도 비용을 표시한다.

## RunPod와 이미지

운영자가 만든 기존 Template의 차이를 시작 계획에 표시하고 확인 후 API로 수정한다. 재조회로 정확한
필드·Secret 참조·registry·시작 명령·고정 image를 검증한 뒤 기존 SSM control 문서에 등록한다.
신규 Template 생성이나 Secret 생성·회전은 자동화하지 않는다. image 선택은 공통 카탈로그가 소유하고
RunPod 등록은 RunPod 자원 연결만 소유한다. 기존 호환 등록 명령도 유지한다.

F2는 private S3 manifest/LoRA 검증 후 제한 시간 presigned URL을 Pod에 주입한다. base Qwen과
Whisper는 고정 Hugging Face revision을 사용한다. URL·장기 AWS 키를 로그나 저장 문서에 넣지 않는다.
이번 계측 코드 사용에는 새 image 게시·카탈로그 digest 갱신이 필요하며 과거 후보 검증은 승계하지 않는다.

## maintenance와 실패 복구

배포 계획은 maintenance로 유지하며 CodeDeploy와 호스트 marker가 API·Worker 시작을 보류한다.
`app-deploy`는 명시적으로 실행한다. 최초/구 revision 호스트에는 CLI 준비를 위한 배포 선행 조건을
표시한다. 이전 검증 근거가 있는 호스트 재생성은 아래의 정확한 revision 복원 경로를 사용한다.
이후 RDS 대상 목록·사용자 확인·모델 준비·Backend 트랜잭션·최종 호환성 검사 뒤에만 앱을 시작한다.

`dev-start`의 앱 합성 검증 후 실제 테스트 호스트에 성공적으로 설치된 CodeDeploy S3 revision을
확인한다. 배포 ID와 S3 version/eTag를 포함한 revision의 SHA-256을 `APPLIED.application_revision`에
기록하고 이후 applying/failed 단계에도 보존한다. 일반/deep 시작의 새 호스트에는 같은 배포의
revision·해시·환경을 재검증한 뒤 정확한 revision만 CodeDeploy로 복원한다. maintenance marker와
배포 모드를 유지하며 새 CodePipeline 실행·미검증 최신 revision 선택·자동 rollback은 하지 않는다.
근거가 없으면 최초 배포를 요구하고, 기록 변경·잘못된 배포·복원 실패는 안전하게 차단한다.

시작 시도는 각 단계와 소유 자원 ID를 추적하고 `serving/APPLIED`에 선택 ID·시각·상태를 기록한다.
실패하면 해당 시도의 endpoint를 offline으로 처리하고 이번 생성 RunPod는 삭제, 이번 시작 AWS GPU는
정지한다. RDS·maintenance 호스트·AWS EBS 등 남은 자원과 정리 명령을 표시한다. 무관한 기존 자원을
삭제하지 않으며 실패를 성공으로 기록하거나 DB 버전을 자동 되돌리지 않는다.

일반/deep 종료는 SSM 선택을 유지한다. deep 종료가 지운 GPU·캐시는 다음 공통 시작에서 같은 선택으로
재구성한다. `ai-switch`는 정지 후 선택 저장의 호환 명령이며 실행 중 전환을 하지 않는다.

운영 순서·사용자 검증·예상 비용 설명은 [개발자 운영](../../../../../infra/operations/README.md),
모델·메모리 근거는 [서빙 구성](../../../../../infra/serving/README.md)가 정본이다.
