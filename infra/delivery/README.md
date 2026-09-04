# Development CI/CD runbook

이 문서는 저장소 구현을 AWS dev 환경에 적용하는 승인 경계를 설명한다. 애플리케이션 Pipeline은 Terraform을 실행하지 않는다.

## 적용 전 gate

- 현재 변경을 저장소 Git 정책에 맞는 PR로 개발 통합 브랜치 `dev`에 병합한다.
- `.github/workflows/pr-policy-review.yml`의 별도 사용자 변경은 이 delivery 변경과 섞지 않는다.
- `pipeline_operator_user_names`가 승인된 기존 IAM 사용자만 포함하고 `student` 외 추가 사용자가 없는지 확인한다.
- `SKN30_FINAL` Connection이 `AVAILABLE`이고 승인된 repository만 접근하는지 확인한다.
- `just -f infra/justfile secret-status`로 선택적 AI provider key, 기존 delivery Discord webhook과 새 Alarm
  전용 Discord webhook의 AWSCURRENT 존재만 확인한다. F2 active에는 SLLM·STT key가 필요하지만
  Bedrock은 Instance Role을 사용해 key가 없다. 값은 TTY 기반 bootstrap/rotation 명령으로 넣으며
  Alarm webhook은 기존 delivery webhook을 재사용하지 않는다.
- Frontend/Backend 정적 검사, migration, Docker/Compose 검증이 성공했는지 확인한다. Frontend
  Verify에는 env·auth·최상위 오류 복구·F2·F3 계약, `typecheck`과 원장 테스트가 모두 포함된다.

## 로컬 CodeBuild 동등 검증

전체 검증은 CodeBuild와 같은 Node.js 22, Python 3.13, `uv 0.11.2`, Docker와
Compose plugin `v2.30.0` 이상이 설치된 Linux 환경에서 저장소 루트 기준으로 실행한다.
Compose 최소 버전은 process별 env 파일의 `format: raw` 계약에 필요하며 배포 host는
Terraform Launch Template에서 `v2.35.1`로 고정한다.

```bash
infra/delivery/scripts/verify_local_delivery.sh
```

이 명령은 ECR Public PostgreSQL base와 고정 pgvector commit으로 로컬 검증 image를 만들고
disposable DB를 시작한 뒤 다음을 순서대로 검증한다. Docker Hub image는 사용하지 않는다.
컨테이너와 임시 파일은 종료 시 정리한다.

1. AI와 Backend의 frozen lock 설치, format, lint, type, 전체 테스트
2. 빈 DB migration과 두 번째 no-op migration
3. CodeDeploy lifecycle shell 구문과 image metadata 전달 계약 테스트
4. Frontend Verify: clean install, env·로그인·최상위 오류 복구·F2·F3 계약 테스트, typecheck, 원장 테스트
5. Frontend Build: 별도 clean install, release build와 release 계약 테스트
6. Backend root-context image build와 UID 10001 실행
7. Compose config

Backend DB 테스트는 `TEST_DB_URL`이 없으면 실행 자체를 거부한다. 부분 검증이 필요할 때도
CodeBuild가 호출하는 아래 진입점을 그대로 사용한다.

```bash
infra/delivery/scripts/verify_backend_ai.sh
infra/delivery/scripts/verify_frontend.sh
infra/delivery/scripts/build_frontend_release.sh
```

Pipeline에서는 각 진입점을 격리된 CodeBuild project에서 실행한다.

| Stage | Buildspec | DB 사용 | Output artifact |
|---|---|---|---|
| Backend Verify | `buildspec-backend-verify.yml` | disposable PostgreSQL+pgvector | 없음 |
| Backend Build | `buildspec-backend-build.yml` | 없음 | CodeDeploy revision과 image digest |
| Frontend Verify | `buildspec-frontend-verify.yml` | 없음 | 없음 |
| Frontend Build | `buildspec-frontend-build.yml` | 없음 | `dist/client` release |

Backend Verify는 검증 DB image를 전용 immutable ECR에 캐시한다. 최초 실행만 image를 만들고,
이후에는 tag의 digest를 조회해 재사용한다. 검증 실패 단계에는 artifact 설정이 없으므로
`_backend_release` 누락이 원래 테스트 오류를 덮지 않는다.

PR에는 실행한 진입점과 결과를 기록하고, Pipeline 최초 적용 전에는 로컬 전체 검증과
Backend·Frontend 독립 Pipeline을 모두 통과시킨다.

### 지속 검증 운영

- Backend·AI 변경은 `verify_backend_ai.sh`, Frontend 변경은 `verify_frontend.sh`와
  `build_frontend_release.sh`를 PR마다 실행한다.
- lockfile, migration, Dockerfile, Compose 또는 buildspec 변경은 영향 모듈만 확인하지 않고
  `verify_local_delivery.sh` 전체를 실행한다.
- CodeBuild는 로컬과 같은 component script를 호출한다. 검증 명령을 바꿀 때 buildspec에
  명령을 복제하지 않고 component script 한 곳만 수정한다.
- `infra.tests.test_delivery_pipeline_contract`가 Verify/Build 명령·artifact·DB 경계와 세
  Pipeline의 `dev` source를 검사한다. buildspec이나 stage를 바꾸면 이 계약 테스트도 함께 갱신한다.
- `dev` 통합 Pipeline은 merge 이후 배포 gate다. merge 이전 강제 gate가 필요하면 같은
  component script를 호출하는 PR CI를 별도로 연결한 뒤 성공 check를 branch protection의
  required check로 지정한다.
- Node, Python, `uv`, base image 또는 lockfile을 올리는 PR은 clean install과 `--no-cache`
  image build를 추가로 수행한다.
- Frontend release manifest의 bundle bytes를 실행별로 비교한다. 현재 Vite large-chunk 경고는
  관찰 항목이며, 팀이 성능 예산을 승인하면 그 값을 release test의 실패 기준으로 고정한다.

## Verify/Build 분리 Terraform 적용

분리 변경 적용 중에는 통합 자동 감지와 ELB health 전환을 계속 보류한다.

```hcl
integrated_pipeline_detect_changes = false
app_asg_health_check_type          = "EC2"
```

```bash
cd infra/environments/dev
terraform fmt -recursive
terraform validate
terraform plan -var-file=dev.tfvars -out=dev.tfplan
# plan 승인 후에만
terraform apply dev.tfplan
```

Terraform은 Secret 컨테이너만 관리한다. saved plan에 Secret version 생성·삭제나 AI provider key,
Discord webhook과 그 hash가 보이면 적용을 중단한다. 값 회전은 `secret-rotate`와 대상별 fixture로
검증한다.

구성의 import block이 기존 Connection ARN을 state로 가져온다. plan에서 Connection replacement 또는 destroy가 보이면 적용하지 않는다.

## 공유 dev 개발 세션 전환

CloudFront dev 주소는 공개 상태를 유지한다. 접속자는 모두 같은 고정 개발 계정
세션을 발급받을 수 있으므로 실제 개인정보·실제 계정·실제 비밀번호를 사용하지
않고 합성·비식별 데이터만 허용한다. Terraform `development_auth`는 비민감 식별자이지만
실제 값은 Git에서 제외된 `dev.tfvars`에 둔다.

1. 공유 환경과 DB를 시작하고 migration 상태를 확인한다.
2. 저장소 `infra/`에서 다음 고정 합성 계정을 멱등 생성한다.

   ```bash
   just dev-create-session-account "개발 중개사무소" developer "Developer" OWNER
   ```

3. 출력된 식별자를 `environments/dev/dev.tfvars`에 기록한다. `setup-local.sh`를 다시
   실행해도 기존 블록은 보존되며, `target_account_id`나 `expires_at`이 다르면
   `--force`로도 수정하지 않고 실패한다.

   ```hcl
   development_auth = {
     brokerage_id = 1
     login_id      = "developer"
   }
   ```

   `null`이면 Backend 개발 세션 경로와 Frontend 버튼이 모두 비활성화된다.
   값이 있으면 Backend는 `APP_ENV=dev`, `DB_TARGET=development`, 유휴 30분·절대
   720분 세션 설정과 개발 계정 식별자를 받고, Frontend는 개발 로그인 버튼을
   표시한다.
4. `integrated_pipeline_detect_changes = false`를 유지한다.
5. 저장소 `infra/`에서 `just dev-plan → just dev-show → just dev-apply → just dev-drift`
   순서로 적용한다. plan에 RDS·ALB·CloudFront의 교체 또는 삭제가 보이면
   `dev-apply`를 실행하지 않는다.
6. 변경이 `dev` 브랜치에 병합된 뒤 병합 결과의 정확한 40자 commit SHA로
   `skn30-final-3team-dev-integrated` Pipeline을 수동 실행한다.
7. 같은 Pipeline의 Backend와 Frontend 배포가 모두 성공하고 아래 smoke test를
   통과한 뒤에만 별도 검토 Terraform 변경으로 통합 Pipeline 자동 감지를 다시 켠다.

정확한 SHA 수동 실행은 다음 형식을 사용한다.

```bash
aws codepipeline start-pipeline-execution \
  --name skn30-final-3team-dev-integrated \
  --source-revisions actionName=Source,revisionType=COMMIT_ID,revisionValue=<40자리-SHA> \
  --region ap-northeast-2
```

### 개발 세션 smoke test

배포된 CloudFront 동일 origin을 기준으로 다음을 순서대로 확인한다.

1. 초기 `GET /api/v1/auth/me`는 401을 반환한다.
2. `POST /api/v1/auth/development-session`은 200을 반환하고 두 `Set-Cookie`에 각각
   `Secure`, `HttpOnly`, `SameSite=Lax`가 있다.
3. 세션 Cookie로 `GET /api/v1/auth/me`가 200이고, 반환된 CSRF token을 사용한
   상태 변경 요청이 성공한다.
4. `DELETE /api/v1/auth/session`은 204이고 이후 `GET /api/v1/auth/me`는 다시 401이다.
5. 로그인 화면에 비활성 ID·비밀번호 폼과 `개발용 세션으로 로그인` 버튼이
   함께 표시된다.

## Pipeline 실행

논리 이름과 실제 이름은 다음과 같다.

| 용도 | Pipeline |
|---|---|
| 통합 | `skn30-final-3team-dev-integrated` |
| Backend | `skn30-final-3team-dev-backend` |
| Frontend | `skn30-final-3team-dev-frontend` |

최신 `dev`는 Console의 Release change 또는 다음 명령으로 시작한다.

```bash
aws codepipeline start-pipeline-execution \
  --name skn30-final-3team-dev-backend \
  --region ap-northeast-2
```

전체 commit SHA를 지정할 때는 Source action revision override를 사용한다.

```bash
aws codepipeline start-pipeline-execution \
  --name skn30-final-3team-dev-backend \
  --source-revisions actionName=Source,revisionType=COMMIT_ID,revisionValue=<40자리-SHA> \
  --region ap-northeast-2
```

Frontend도 Pipeline 이름만 바꿔 같은 방식으로 실행한다. 실행 전 다른 두 Pipeline이 `InProgress` 또는 `Stopping`이 아닌지 운영자가 확인한다.

## Backend deploy 검증

배포 재실행 전에는 EC2 instance role이 Parameter Store의 개별 값뿐 아니라 조회 경로
자체에도 접근 가능한지 확인한다. `GetParametersByPath`는 아래 base path ARN을 평가하므로
결과가 `allowed`여야 한다.

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::<ACCOUNT_ID>:role/skn30-final-3team-dev-app-instance \
  --action-names ssm:GetParametersByPath \
  --resource-arns arn:aws:ssm:ap-northeast-2:<ACCOUNT_ID>:parameter/skn30-final-3team-dev \
  --context-entries ContextKeyName=ssm:Recursive,ContextKeyValues=true,ContextKeyType=boolean \
  --region ap-northeast-2
```

Bedrock POC Terraform apply는 Launch Template의 새 default version만 만들며 기존 EC2를 자동
교체하지 않는다. 활성 작업을 종료하고 공유 dev 중단 시간을 공지한 뒤 `just -f infra/justfile
dev-stop`과 `just -f infra/justfile dev-start`를 순서대로 실행한다. 이는 기존 EC2를 종료하고
RDS도 정지·재시작한다. 새 EC2가 `InService`, SSM `Online`, IMDSv2 token 필수·hop limit 2인 것을
확인한 뒤 Backend revision을 배포한다. 이 교체와 배포가 끝나기 전에는 doctor나 Bedrock seed를
실행하지 않는다.

Pipeline과 CodeDeploy에서는 다음 순서로 확인한다.

1. CodePipeline의 Source revision이 요청한 40자리 SHA인지 확인한다.
2. Backend Build artifact의 image가 `repository@sha256:...` 형식인지 확인한다.
3. `backend-image.env`에 image digest와 비민감 parameter prefix·secret ARN·port·health/log 메타데이터만 있는지 확인한다.
4. CodeDeploy `BeforeInstall`에서 이전 통합 파일 `/opt/brokerage/config/runtime.env`만 제거되고, `AfterInstall`에서 API·Worker·Migration별 `0600` 환경파일 조립과 migration이 성공했는지 확인한다. 세 파일은 pinned Compose `v2.35.1`의 `format: raw`로 읽으며 비민감 `AI_LLM_ENDPOINTS`·timeout은 API·Worker 파일에 있어야 한다. F2 key는 endpoint active일 때만 API에, 선택적 OpenAI·vLLM key는 Worker에 주입하며 Bedrock key는 없어야 한다.
5. `ApplicationStart`, `ValidateService`가 성공하고 deployment 상태가 `Succeeded`인지 확인한다.
6. Target Group의 유일한 target이 `healthy`인지 확인한다.
7. CloudFront `https://<distribution-domain><APP_READINESS_PATH>`가 200을 반환하는지 확인한다.
8. API·Worker CloudWatch log에 revision 전환 이후 지속적인 error가 없는지 확인한다.
9. `/opt/brokerage/deploy-record.json`의 revision, image digest와 Pipeline execution ID가
   실행 이력과 같은지 확인한다. 파일에는 비밀값이 없어야 한다.
10. Bedrock POC revision이면 `just -f infra/justfile bedrock-doctor`가 추론 없이 Worker 컨테이너의
    IMDSv2·Instance Role·`global.openai.gpt-5.6-luna` profile 조회를 통과하는지 확인한다.

실패한 deployment의 상세 상태는 값을 노출하지 않는 다음 조회로 확인한다.

```bash
aws deploy get-deployment \
  --deployment-id <DEPLOYMENT_ID> \
  --query 'deploymentInfo.{status:status,error:errorInformation,revision:revision}' \
  --region ap-northeast-2

aws deploy list-deployment-instances \
  --deployment-id <DEPLOYMENT_ID> \
  --region ap-northeast-2
```

Lifecycle script의 AWS CLI 오류는 원래 AWS service error와 operation 이름을 stderr에
남겨야 한다. Secret 값, Parameter 값, DB URL과 IAM DB token은 출력하지 않는다.

`root certificate file ... does not exist`가 발생하면 host config directory를 컨테이너에
통째로 mount했는지 확인한다. 이 directory는 root `0700`이므로 비루트 UID 10001이 탐색할
수 없다. 현재 계약은 `/opt/brokerage/config/global-bundle.pem` 파일 하나만 container의
`/etc/ssl/certs/aws-rds-global-bundle.pem`에 read-only mount하며, `AfterInstall`이 migration
전에 실제 readability를 검사한다. config directory mode를 `0755`로 완화해 우회하지 않는다.

### CloudWatch Alarm fixture 검증

새 Alarm 전용 webhook과 Terraform apply가 끝난 뒤에만 합성 fixture를 게시한다. 기존
CodePipeline·CodeDeploy Discord 채널이나 webhook을 이 검증에 사용하지 않는다.
실제 장애 조사 순서는 [CloudWatch Alarm 장애 대응 Runbook](../../docs/operations/cloudwatch-alarm-response.md)을
따른다.

```bash
cd infra/environments/dev
terraform output -json runtime_observability

aws sns publish \
  --topic-arn <RUNTIME_OBSERVABILITY의_ALARM_TOPIC_ARN> \
  --message file://../../tests/fixtures/cloudwatch_alarm_sns_message.json \
  --region ap-northeast-2
```

Alarm 전용 Discord 메시지에 fixture의 alarm name, `module=backend`, `ALARM` state, 상태 전이 시각,
reason과 Alarm·Logs Insights·Runbook 링크가 있고 mention이 발생하지 않는지 확인한다. fixture의
`Region=Asia Pacific (Seoul)`가 아니라 `AlarmArn`의 `ap-northeast-2`가 Console URL에 사용돼야 한다.
일치 로그가 있으면 허용된 안전 필드 1건과 직접 원인이 아니라는 안내가 보여야 한다.

Logs Insights 실패·빈 결과·2초 시간 초과를 주입해도 기본 메시지와 링크가 전송되고 Lambda는 성공해야
한다. 시간 초과에서는 `StopQuery`를 시도한다. Lambda log에는 webhook URL, AWS 예외 원문,
`@message`, `@ptr` 또는 fixture 바깥 원문이 없어야 한다. Discord HTTP 오류를 주입할 때만 Lambda
호출이 실패해 SNS 재시도 대상으로 남아야 한다. `OK` fixture는 Logs Insights API를 호출하지 않고
조사 링크만 유지해야 한다.

## 검증 순서

1. Backend 독립 Pipeline에서 Verify 실패가 Build·CodeDeploy를 시작하지 않는지 확인한 뒤 첫 정상 CodeDeploy revision을 만든다.
2. Frontend 독립 Pipeline에서 Verify와 Build가 분리됐는지 확인한 뒤 첫 정적 release를 배포한다.
3. 통합 Pipeline을 수동 실행해 migration no-op과 Backend 후 Frontend 순서를 확인한다.
4. 실패 주입 revision으로 Backend 자동 rollback, Frontend index 복원과 Discord 알림을 확인한다.
5. ALB target, CloudFront 화면, 같은 origin API, migration version, API·Worker log를 확인한다.
6. drift plan이 비어 있는지 확인한다.

검증 후 별도 승인 Terraform 변경으로 다음 두 값만 전환한다.

```hcl
integrated_pipeline_detect_changes = true
app_asg_health_check_type          = "ELB"
```

안전한 `dev` 변경으로 통합 Pipeline 자동 실행을 확인한다.

## Rollback

- Backend는 CodeDeploy의 마지막 정상 revision으로 되돌린다. DB down migration은 실행하지 않는다.
- Frontend는 `frontend-releases/<pipeline-execution-id>/index.html` backup을 복원하고 `/`, `/index.html`을 invalidation한다.
- Breaking API 변경은 Frontend 독립 Pipeline으로 배포하지 않는다.
