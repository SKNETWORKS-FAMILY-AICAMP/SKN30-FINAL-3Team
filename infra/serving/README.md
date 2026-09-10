# Local·dev LLM 서빙 구성

명령 실행 순서·비용 확인·실패 복구는 [개발자 운영](../operations/README.md), 저장·Secret 책임은
[설정 관리](../operations/configuration.md)가 정본이다. 이 문서는 모델·하드웨어·이미지와 로컬 연결을 다룬다.
공유 dev 통합 선택 정책은 [프로젝트 ADR-0036](../../.agents/skills/project-wiki/references/decisions/ADR-0036-shared-dev-serving-selection.md),
인프라 구현 경계는 [Infra ADR-0024](../../.agents/skills/infra/references/decisions/ADR-0024-shared-serving-selection-lifecycle.md)를 따른다.

## 지원 조합과 GPU 검증 근거

F2와 general은 별도 모델 서버이며 각 작업의 클라우드를 독립 선택한다. 공유 dev의 통합 메뉴는
vLLM만 제공한다. 기존 OpenAI·Bedrock 수동 경로를 제거하지 않으며 local 개인 OpenAI는 유지한다.
CPU 전환·자동 fallback·상시 예비 GPU·자체 감시는 이번 범위에 없다.

| 작업 | RunPod 기본 profile | AWS 기본 profile | 모델 |
|---|---|---|---|
| F2 | `runpod-a5000-24gb` · RTX A5000 24GB | `aws-g6-2xlarge` · g6.2xlarge/L4 24GB | consultation-v3 · Qwen3-4B LoRA + Whisper-large-v3-turbo |
| general | `runpod-l40s-48gb` · L40S 48GB | `aws-g6e-2xlarge` · g6e.2xlarge/L40S 48GB | `qwen38-27b-fp8` |

하드웨어 선택값은 [hardware-profiles.json](hardware-profiles.json)의 공통 enum과 일치해야 한다.
F2는 `runpod-rtx4090-24gb`도 지원한다. general 모델 선택값은 `qwen3-14b-awq`, `qwen3-32b-awq`,
`qwen38-27b-bnb`, `qwen38-27b-fp8`이며 선택 메뉴의 기본 후보는 FP8다. 배포에는 확정 profile이
필요하고 값 누락을 BnB 등 다른 모델로 대체하지 않는다. 등록·지원과 실제 추론·품질 검증을 구분한다.

F2 24GB 구성은 과거 release·후보 이미지의 RTX 4090 및 AWS L4 성공 근거가 있다.
**consultation-v3 + RTX A5000 + 현재 게시 이미지의 정확한 조합은 사용자 기동 검증 대기다.**
동일 VRAM이라고 다른 GPU의 성능·기동 결과를 승계하지 않는다. F2는 Qwen 문맥 4,096,
각 엔진 동시 처리 1건, GPU 메모리 설정 Qwen 65%·Whisper 20%를 유지한다. 남는 비율은 실제
최대 사용량 보장이 아니며 모델 로딩·CUDA·캐시·요청 중 메모리를 사용자 검증에서 확인한다.

general 48GB는 현재 지원 정책의 최소 용량이다. [게시 이미지 catalog](published-images.json)의
image/profile별 `cpu_only`, `startup_only`, `evaluated` 근거를 확인한다. 작은 모델이 목록에
있다는 이유로 임의 저용량 GPU를 허용하거나 더 큰 GPU로 자동 변경하지 않는다. 가용량 부족 시
실패를 표시하고 운영자가 다시 선택한다. AWS의 AMI·toolkit·Compose·SSM 호환성도 첫 기동에서 확인한다.

## 모델 파일과 이미지

- F2 LoRA·manifest·메타데이터는 private S3 release에서 읽는다. `consultation-v3`와 기존 dev release는
  [F2 release catalog](../runpod/releases.json)에서 별도로 관리하며 덮어쓰지 않는다.
- RunPod 기동 시 manifest·bundle hash를 확인하고 1시간짜리 S3 presigned URL을 Pod에 주입한다.
  세션 자격 증명이 먼저 만료되면 URL도 먼저 만료될 수 있다. 장기 AWS 키나 전체 URL을 로그에 남기지 않는다.
  Console에서 Template만 수동 실행하면 동적 release 입력이 없으므로 통합 시작 명령을 사용한다.
- Qwen base와 Whisper 가중치는 S3 LoRA bundle에 포함되지 않는다. 고정한 Hugging Face revision에서
  내려받으며 모델 로딩·네트워크·캐시 공간이 필요하다. SHA-256 검사와 안전한 압축 해제를 통과한
  adapter만 사용한다. 다운로드·해시 검증·엔진 로딩 실패를 구분해 확인한다.
- F2 선택 이미지는 하드웨어 catalog, general 이미지는 게시 이미지 catalog가 고정 digest로 관리한다.
  AWS와 RunPod가 같은 선택 이미지를 소비하며 AWS가 RunPod control 문서에서 이미지를 가져오지 않는다.
- 현재 F2 `ca2cfefb…`와 general `801473c8…` pin은 새 identity/VRAM 계측 이전 이미지다.
  이 이미지로 강화된 검증을 실행하면 계측을 확인할 수 없어 실패한다. `image-publish f2 dev`와
  `image-publish general dev`의 artifact를 검토한 뒤 F2 `hardware-profiles.json:f2_image`,
  general `published-images.json`·기본 image ID를 갱신하고 정지 상태의 `ai-select`로 새 pin을 저장한다.
  이번 구현은 이미지 게시를 실행하지 않았다. 코드·테스트 완료는 실제 기동 완료를 뜻하지 않는다. `python3`·vLLM 버전별 시작 인자를
  이미지 빌드에서 검증하며 F2와 general 옵션을 혼용하지 않는다.

## 전원·배포의 내부 경계

AWS 자원은 Terraform dev root가 소유한다. 검토한 AMI·EBS 프로필을 보존하면서 시작 계획이
선택 image·capacity·앱 provider/model을 같은 입력으로 만든다. RunPod는 최초 Console 자원을
보존하고 기존 Template 차이만 검토·API 수정·재조회 후 SSM 등록한다. Secret 참조·registry 권한은
기존 경계를 유지하고 자동 생성·회전하지 않는다.

`dev-start`와 `dev-prepare-app`은 같은 선택·Terraform·Template·비용 계획을 쓴다.
CodeDeploy maintenance 모드와 호스트 marker가 구/새 revision의 API·Worker 자동 기동을 막는다.
`app-deploy`는 별도이며, 앱·Worker는 DB 대상 확인·모델 준비·호환성 검사가 통과한 마지막 단계에 시작한다.
DB 조회·적용은 [Backend 모델 선택 계약](../../.agents/skills/backend/references/model-selection.md)을 호출한다.

일반/deep 종료로 앱 호스트가 교체되면 이전 `dev-start`의 실제 호스트·앱 합성 검증을 통과한
정확한 CodeDeploy S3 revision을 maintenance에서 복원할 수 있다. SSM `APPLIED`의 배포 ID·revision
해시로 대조하고, 검증하지 않은 최신 revision이나 새 Pipeline을 자동 실행하지 않는다.
기록이 없는 최초 환경은 명시적 `dev-prepare-app → app-deploy → dev-start`가 필요하다.

일반 stop은 AWS GPU를 정지하고 RunPod Pod를 삭제한다. AWS EBS 캐시는 보존되어 비용이 남는다.
deep stop은 검토한 범위에서 GPU·캐시·edge를 제거하며 모델 release·DB·선택·등록은 보존한다.
다음 시작은 같은 선택에서 주소·캐시를 재구성한다. 선택 자체를 마지막 성공값으로 자동 되돌리지 않는다.

## Local 연결

개인 OpenAI 설정은 공유 dev 선택과 별개다. GPU에 연결할 때만 새 ignored 파일을 명시적으로 생성한다.

```bash
just -f infra/justfile ai-connect general ../ai/.env.gpu-general
just -f infra/justfile ai-connect f2 ../ai/.env.gpu-f2
```

출력 파일은 기존 파일을 덮어쓰지 않는다. 필요한 값을 `ai/.env`에 반영하며 Backend에 AI 변수를
중복 작성하지 않는다. general 파일에는 실제 활성 profile에 맞는 provider/model이 포함된다.
AWS는 고정 loopback 포트 18000/18001/18002의 SSM 터널을 유지하고 RunPod는 해당 Pod HTTPS proxy를
사용한다. 키는 승인된 값을 TTY로 전달하며 공유 GPU 자동 기동·공유 DB 모델 변경은 하지 않는다.

`local-config`로 설정을 확인하고 `local-model <사무소 ID> <capability>`로 로컬 DB 전후 입력을 확인한다.
API·Worker 중지 후에만 `--apply --workloads-stopped`를 사용한다. 기동은 `local-api`, `local-worker`다.
개인 파일·주석 기준은 [환경변수 관리](../../docs/development/environment-variables.md)를 따른다.

## 검증 기록

`dev-verify`의 성공은 해당 실행의 연결·합성 요청 근거다. 품질 평가나 다른 image/release/cloud의
검증 성공을 뜻하지 않는다. 계측 누락은 0으로 표시하지 않으며 새 이미지 게시·적용 필요 여부를 확인한다.
일반 재기동·deep 재생성·양방향 전환은 운영 절차로 직접 실행하고 각각 검증한다.

[validation.md](validation.md)는 기존 GPU 검증 진입점,
[RunPod 기록](remote-validation-2026-09-07.md)과 [AWS 사설 검증](aws-private-validation-2026-09-07.md)은
그 시점의 후보 근거다. 이 기록을 이번 release의 성공으로 수정하지 않는다.
[비교 재현](comparison-reproduction.md)은 저장 근거 검사·동일 조건 평가의 별도 절차다.
