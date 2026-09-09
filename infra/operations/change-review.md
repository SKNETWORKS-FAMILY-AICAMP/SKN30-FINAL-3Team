# 2026-09-09 개선 검토 및 인계

작업 브랜치는 `chore/infra-developer-operations`이며 별도 워크트리에서 구현했다.
최신 origin/dev `4b5d002`를 병합했으며 원래 checkout의 개인 `.env` 값·이름, 활성 모델, 클라우드 전원은 변경하지 않았다.
후속 점검에서 ignored 개인 파일 5개의 권한만 0600으로 제한했다.

## 검증 결과

- 최종 환경변수 리팩토링 후 Infra 262개, Backend 단위 294개, AI 단위 434개, Frontend 환경 21개·release 2개 통과(합계 1,013개).
- 앞선 RunPod runtime/proxy 테스트 36개도 통과했으며 이후 해당 runtime은 수정하지 않았다.
- Backend·AI Pyright, Frontend 타입 검사·빌드 통과. 환경변수 리팩토링은 [정리 기록](configuration-audit.md)을 따른다.
- Infra check 범위 Ruff, just 포맷, Terraform fmt와 두 root validate 통과.
- 변경 문서의 상대 링크와 `git diff --check` 통과.
- 실제 `doctor`는 저장된 Secret의 필수 구조와 Console 등록을 조회했다. 과거 불량 F2/general 이미지,
  현재 checkout과 다른 Pipeline revision은 조치 항목으로 표시했다.
- 새 LoRA 원본의 manifest·adapter·평가 metadata checksum 검증 통과. 실제 모델 기동·추론은 미실행.

실제 클라우드 조회 결과의 `OK`는 해당 구조 검사 범위만 뜻한다. 테스트는 합성 입력과 mock을 사용하며
GPU 생성·SSM 실행·배포·모델 추론 성공을 증명하지 않는다.

## Bootstrap saved plan 검토

`just bootstrap-plan`으로 생성했고 입력·plan hash 검사를 통과했다. 생성·삭제·교체 없이
관리 자원 3개가 update로 표시됐다. **2026-09-09 사용자 명시 승인 후 새 plan으로 재검토·적용 완료.**

| 대상 | 검토 결과 |
|---|---|
| state bucket policy | 비운영자 Deny에 `ListBucketVersions`, `GetObjectVersion`, `DeleteObjectVersion` 추가. 허용 예외는 기존 TerraformOperatorRole·account root 유지 |
| TerraformOperatorRole | 이미 dev 브랜치에 있던 description 문구와 원격 값의 차이. trust·최대 세션 시간·정책 attachment 변경 없음 |
| 운영자 AssumeTerraformOperatorRole inline policy | 위 role update 의존성으로 policy document가 apply 때 재계산됨. 같은 기존 role ARN을 참조하며 이번 소스 변경은 없음 |

정책 document data source 2개는 역할 update 의존성 때문에 apply 때 재계산됐다.
승인된 범위와 같은 plan임을 확인하고 적용했으며 결과는 **0 added, 2 changed, 0 destroyed**다.
실제 변경은 TerraformOperatorRole description과 state bucket policy였다.
기존 assume-role inline policy는 재계산 결과가 같아 실제 변경되지 않았다.

AWS 조회로 추가된 세 version 접근 Deny, 기존 operator/root 예외, 역할 description·trust·session,
기존 assume-role inline policy가 Terraform 상태와 일치함을 확인했다.
같은 구성의 `bootstrap-drift`는 **No changes**, exit code 0으로 통과했다.
앱·DB·GPU를 시작하거나 dev 환경변수 Terraform 변경을 적용하지 않았다.

## 새 모델 게시 완료

- 원본: `f2-consultation-v05-qwen3-4b-v2.tar.gz`.
- 내부 release ID: `consultation-v3`; 기존 release를 덮어쓰거나 기본값으로 활성화하지 않는다.
- 목적 bucket: `skn30-final-3team-dev-data-model-apse2-398563707017`.
- 목적 prefix: `releases/sllm/consultation-v3/`.
- 생성 객체: `bundle.tar.gz`, `release.json`.
- bundle SHA-256: `2ca9f5ea643d2f689cc92d778a1152dd156315d49059126751ea46d4b1e1866d`.

이전 자동 승인 검토의 거부 사유에 대해 사용자가 파일·목적지 전송을 명시 승인했다.
2026-09-09 두 객체를 조건부 신규 생성했고, 원격 본문을 읽어 SHA-256 및 상호 metadata hash를 검증했다.
bundle은 60,693,443 bytes, release.json은 1,405 bytes이며 두 객체 모두 AES256 암호화다.
대상 bucket의 public access block과 예상 소유 계정도 확인했다.
기존 release·기본 모델·active endpoint는 변경하지 않았다. 실제 기동·합성 추론 검증은 사용자 수행이다.

## 사용자 기동 전 남은 단계

[운영 안내](README.md)의 최초 실행 순서를 따른다. 수정 이미지 게시·Console Template 등록,
최신 앱 배포와 사용자 기동 검증은 아직 실행하지 않았다.
F2 consultation-v3/RunPod RTX A5000, general 공식 FP8/RunPod L40S의 offline 선택은 저장했다.
활성 endpoint와 사무소 DB 모델 버전은 변경하지 않았다.
해당 checkout의 개인 설정 정리는 `just env-fix`로 실행한다. 학습·개인 자원 정리는
[관리표](resources.md)의 담당자·보존 조건 확인 후 진행한다.


## 후속 배포 준비 점검

- Terraform `general_model_selection`은 provider/model/region 조합을 검증한다. shared dev 기본은
  `vllm`/공식 `Qwen/Qwen3.8-27B-FP8`이며 OpenAI/Bedrock 선택도 명시적으로 지원한다.
- Renderer는 active endpoint 모델과 공개 `AI_GENERAL_MODEL`이 다르면 배포를 중단한다.
- 원격 모델 변경은 capability 하나를 새 Backend 관리 명령으로 반영하고 이미 중지된 API/Worker를 확인한다.
  자동 재시작이나 추론을 하지 않으며 대기·진행 작업과 챗봇 요청도 검사한다.
- 사용자 최초 준비 명령은 선택 GPU의 인증·직접 합성 추론을 먼저 수행하고 endpoint와 앱 호스트를 준비한다.
  최신 앱은 별도 Pipeline으로 배포한다. 이 준비 명령은 이번 작업에서 실행하지 않았다.
- 원본 개인 `.env` 5개는 권한만 0600으로 변경했다. OpenAI 키와 GPU 키가 다르므로 자동 덮어쓰지 않았다.
  새 코드 반영 뒤 `env-fix`로 충돌 없는 옛 이름을 이전하고 충돌은 선택 provider에 맞게 정리한다.

### 초기 검토: dev 설정 plan (후속 변경으로 재생성 필요)

`dev-deep-stop.tfplan`은 현재 deep 중지 상태를 유지하는 옵션으로 생성·봉인했다.
GPU·ALB·DB·앱 생성/기동은 없으며 **2 create / 1 update / 7 delete**다.

- 생성: `AI_GENERAL_PROVIDER`, `AI_GENERAL_MODEL` SSM 공개 설정.
- 삭제: `AI_LLM_ENDPOINTS`, `AI_OPENAI_BASE_URL`, `APP_OPENAPI_ENABLED`,
  `AUTH_CSRF_COOKIE_NAME`, `AUTH_SESSION_COOKIE_NAME`, `WORKER_ENABLED`, `WORKER_READY_FILE` SSM 설정.
- 갱신: app runtime IAM policy. SSM ARN 목록 변경 의존성으로 document를 apply 때 재계산하며
  정책 생성 소스 자체는 변경하지 않았다. apply 뒤 예상 SSM ARN 목록과 기존 나머지 statement 보존을 대조해야 한다.

이 plan은 bootstrap 승인 범위에 포함되지 않으며 아직 적용하지 않았다. 이후 최초 전환 보호 코드가 추가되어
해당 초기 plan은 재사용하지 않는다. 아래 `dev-first-deploy.tfplan`이 최종 전환 검토 대상이다. 기존 dev.tfplan은 edge를 복구하므로
현재 중지 상태의 설정 반영에 사용하지 않는다. 새 코드 병합/배포와 함께 위 삭제의 호환성을 검토한 뒤 승인한다.
복구는 이전 revision의 Terraform 공개 설정과 앱 revision을 함께 복원하는 새 plan으로 수행한다.

### 이미지 준비

- F2: 최신 dev `4b5d002`의 [게시 workflow](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34304809097)를 실행했다.
  빌드 서버의 GPU 부재를 처리하지 못한 CLI parser 검사로 실패했다.
  parser 기본값 생성에만 CPU 장치 종류를 제공하도록 수정했다.
  [수정 branch 게시 run 34305829152](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/actions/runs/34305829152)가 성공했고
  실제 installed vLLM CLI parser 검사를 통과했다. 게시 source는 `ebd3cf9`다.
  최종 image: `ghcr.io/sknetworks-family-aicamp/skn30-final-3team/f2-serving@sha256:ca2cfefb47e97c4b664b388ff585ae4d512e7ae33d6718fe400dc2ebe486b769`.
- General: 기존 성공 run `34200029859`의 공식 FP8 이미지와 Template artifact를 확보했다.
  정확한 digest는 `infra/serving/published-images.json`을 따른다. 평가 이력은 품질 승인을 뜻하지 않는다.
- Console Template 변경·SSM 재등록은 아직 수행하지 않았다. 브라우저 연결 도구가 workspace URI 오류로 실행되지 않았다.


최초 앱 전환은 `dev-first-deploy-plan`의 `app_deployment_mode=maintenance`로 ASG 자동 배포 연결을
일시 해제하고 정확한 Project/Environment/Name 태그의 앱만 배포 대상으로 지정한다.
이 설정 없이 새 SSM 계약부터 적용하면 구 revision 자동 배포가 실패할 수 있다.
새 Pipeline revision 배포 성공 뒤 `automatic` 복구 plan을 별도로 검토·적용한다.
이 운영 모드는 Terraform 입력이며 애플리케이션 환경변수가 아니다.

최초 전환 saved plan은 **6 create / 5 update / 7 delete**, replacement 없음이다.
ALB·listener·alarm 복구와 CloudFront 활성화가 포함되며 실행 전 사용자가 비용·전환 창을 검토한다.
이 apply 자체는 ASG desired 0/RDS stopped를 유지하지만 뒤의 `dev-prepare-app` 단계에서 GPU·앱·DB를 기동한다.

변경 주소(민감값 제외):

- `aws_cloudfront_distribution.frontend`: update
- `aws_cloudwatch_metric_alarm.alb_target_5xx[0]`: create
- `aws_cloudwatch_metric_alarm.alb_unhealthy_hosts[0]`: create
- `aws_codedeploy_deployment_group.backend`: update
- `aws_iam_role_policy.app_runtime`: update
- `aws_lb.app[0]`: create
- `aws_lb_listener.http[0]`: create
- `aws_s3_bucket_policy.frontend`: update
- `aws_ssm_parameter.application["ai_ai_general_model"]`: create
- `aws_ssm_parameter.application["ai_ai_general_provider"]`: create
- `aws_ssm_parameter.application["ai_ai_llm_endpoints"]`: delete
- `aws_ssm_parameter.application["ai_ai_openai_base_url"]`: delete
- `aws_ssm_parameter.application["backend_app_openapi_enabled"]`: delete
- `aws_ssm_parameter.application["backend_auth_csrf_cookie_name"]`: delete
- `aws_ssm_parameter.application["backend_auth_session_cookie_name"]`: delete
- `aws_ssm_parameter.application["backend_http_allowed_hosts"]`: update
- `aws_ssm_parameter.application["backend_worker_enabled"]`: delete
- `aws_ssm_parameter.application["backend_worker_ready_file"]`: delete


최종 읽기 조회(2026-09-09 03:15 UTC): app desired/instances 0, RDS stopped, AWS EBS 0,
CloudFront disabled, 운영 키 범위 RunPod 0. F2/general 선택은 RunPod이며 endpoint offline이다.
Secret의 AWSCURRENT·필수 구조는 통과했고, 두 과거 image 등록과 구 Pipeline revision 교체는 남았다.
PR은 [#113](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/pull/113)이다.


## PR #113 후속 리뷰 판정

검토 기준 revision은 `d0226fd`이며 리뷰 5건을 호출 경로와 실제 입력으로 대조했다.

| 항목 | 판정 | 근거와 처리 |
|---|---|---|
| 1. self-hosted 안전 URL 검사 우회 | 재현되지 않음 | `_http_url` 뒤 `SelfHostedLlmEndpointConfig`의 Pydantic field validator가 `_safe_self_hosted_base_url`을 호출한다. 공개 binder를 통해 OpenAI/vLLM/llama.cpp의 userinfo/query/fragment 거부와 오류 비밀값 비출력을 회귀 테스트로 확장했다. 런타임 코드는 변경하지 않았다. |
| 2. 최초 전환 maintenance 누락 | 기존 보호에 추가 보완 | 기존 first-deploy recipe는 maintenance를 명시하고 runtime도 실제 ASG 연결을 검사했다. saved plan 자체의 모드/대상 검사는 없었으므로 seal/check 모두 실제 Terraform JSON을 검증하도록 추가했다. 일상 ASG 동작을 유지하기 위해 automatic 기본값은 보존했다. |
| 3. launcher의 AI import 순서 | 재현되지 않음 | `brokerage-ai`는 Backend의 명시적 로컬 경로 의존성이다. backend/src 경로 추가는 Backend 모듈용이며 AI 설치와 별개다. 개인 파일·PYTHONPATH·기존 가상환경 없는 archive checkout에서 locked uv 설치 후 config가 통과했다. API/Worker도 execve만 대체해 import/config/주입을 확인했고 서비스를 시작하지 않았다. |
| 4. 하위 입력 fingerprint 누락 | 확인·수정 | bootstrap/dev 하위 파일을 재귀 수집하고 정책·템플릿·Dockerfile·justfile을 포함한다. 변경/추가/삭제, symlink 거부와 기존 metadata 무효화를 검증했다. |
| 5. 선택 source의 빈 공개 할당 | 작성 기준 보완 | 현재 parser는 빈 값도 장부 source로 상속하므로 런타임 장애는 재현되지 않았다. 공개 파일의 빈 할당은 주석 처리하고 실제 Node env-file 로딩에서 변수 부재·상속을 검증했다. |

제외된 Worker/F2 계약 관련 3건은 ADR-0034의 명시적 부분 대체 범위와 일치하므로 제외 판단을 유지한다.

- 검증: AI 설정 63개, Infra 전체 271개, Frontend 환경 22개 통과. Frontend 타입·빌드, AI Ruff,
  Infra Ruff, 문서 검사 통과. 기존 Frontend chunk 크기 경고는 동일하다.
- 실제 기존 최초 전환 plan도 메모리로만 읽어 maintenance/정확한 배포 대상 검증을 통과했다.
  Terraform JSON은 CLI boolean을 문자열 `"true"`로 보존할 수 있어 정확한 `true` 두 표현만 허용한다.
- metadata schema와 입력 범위가 바뀌었으므로 **기존 saved plan은 재생성·재검토해야 한다**.
  이전 metadata를 재봉인해 우회하지 않는다. 이번 검토에서는 새 plan 생성·apply·서비스 기동을 하지 않았다.

## PR #113 sticky review 재검토와 최신 dev 통합

[sticky comment](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/pull/113#issuecomment-5595333949)의
검토 SHA `862a857`에 대한 HIGH 7건을 코드·사용자 요청·공식 계약으로 대조했다.
최신 `dev` `5950681`(PR #114)을 작업 브랜치에 병합했으며 텍스트 충돌은 없었다.
자동 병합된 Infra 테스트/just 명령과 dev의 OpenAI 전송 스키마·Frontend 회귀 변경을 함께 보존했다.

| Sticky 항목 | 판정 | 근거와 처리 |
|---|---|---|
| 1. AI endpoint 주소록 계약 미승인 제거 | 구현 승인과 팀 병합 상태 구분 필요 | 사용자 명시 정리안 구현 승인에 따른 JSON 입력 제거다. 내부 alias exact routing과 fallback 금지는 유지한다. 다중 provider 동시 연결 제한도 ADR-0034에 명시되어 있다. 승인 출처와 대체 범위를 ADR에 보완했다. |
| 2. 안전 URL 검사 우회 | 오탐 | binder가 생성하는 `SelfHostedLlmEndpointConfig`의 field validator가 안전 URL 함수를 실행한다. 공개 binder에서 vLLM/llama.cpp를 포함한 거부·비밀 비출력 테스트가 통과한다. |
| 3. 비활성 Worker 계약 제거 | 사용자 승인된 전환 | 실행 여부는 프로세스 시작/중지로 관리한다. 구성·합성 데이터 opt-in 검증은 DB 선점 전에 유지된다. 팀의 PR 병합 승인이 이미 완료됐다는 뜻은 아니다. |
| 4·6·7. F2 상태 입력 제거 | 같은 계약 변경에 대한 중복 지적 | Infra endpoint 문서 검증과 URL 쌍에서 상태를 계산한다. offline은 runtime 미초기화와 `F2_UNAVAILABLE` 503, 부분 구성은 거부한다. Backend ADR-0005의 대체 범위와 보존 동작을 ADR-0034에 명확히 기록했다. |
| 5. CodeDeploy 그룹 간 OR | 오탐·권고 적용 시 대상 확대 | AWS는 그룹 간 AND, 그룹 내부 OR다. 현재 3그룹×각1태그가 Project/Environment/Name 모두를 요구한다. 한 그룹으로 합치지 않으며 saved plan/runtime guard도 그 형태를 거부한다. |

CodeDeploy 근거: [AWS EC2TagSet API](https://docs.aws.amazon.com/codedeploy/latest/APIReference/API_EC2TagSet.html),
[AWS 태그 예시 3](https://docs.aws.amazon.com/codedeploy/latest/userguide/instances-tagging.html#instances-tagging-examples-multiple-tag-groups-single-tags),
[잠긴 Terraform AWS provider v6.60.0의 그룹 변환](https://github.com/hashicorp/terraform-provider-aws/blob/v6.60.0/internal/service/deploy/deployment_group.go#L834-L843).

교차 점검에서 별도로 발견한 `test_synthetic_seed_postgresql.py`의 구형 환경변수 fixture를
현재 provider/model/base URL 입력으로 수정했다. 실제 fixture를 추출한 오프라인 바인딩으로
F2 offline·범용 alias·모델 일치를 확인했다. DB 통합 실행은 수행하지 않았다.

- 병합 후 검증: AI 전체 483, Backend 단위·경계 321, Infra 268, 범용 serving 23,
  Frontend 빠른 테스트 217개 통과(총 1,312개). dev에서 중복 Infra 테스트 3개를 정리하고
  `serving/tests`를 just check에 포함한 변경도 유지했다.
- AI/Backend Ruff·Pyright, Frontend 타입·빌드, Terraform fmt, 위키 링크 검사 통과.
  Frontend의 기존 500 kB chunk 경고는 남아 있다.
- 사용자 구현 승인과 작성자 외 팀원 PR 승인은 구분한다. PR 병합·dev plan 적용·실제 기동은 미실행이다.
