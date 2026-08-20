# Development CI/CD runbook

이 문서는 저장소 구현을 AWS dev 환경에 적용하는 승인 경계를 설명한다. 애플리케이션 Pipeline은 Terraform을 실행하지 않는다.

## 적용 전 gate

- 현재 dev 변경을 저장소 Git 정책에 맞는 PR로 `main`에 병합한다.
- `.github/workflows/pr-policy-review.yml`의 별도 사용자 변경은 이 delivery 변경과 섞지 않는다.
- `pipeline_operator_user_names`가 승인된 기존 IAM 사용자만 포함하고 `student` 외 추가 사용자가 없는지 확인한다.
- `SKN30_FINAL` Connection이 `AVAILABLE`이고 승인된 repository만 접근하는지 확인한다.
- Discord secret container에 `{"webhook_url":"..."}` 값을 저장소와 Terraform 밖에서 주입한다.
- Frontend/Backend 정적 검사, migration, Docker/Compose 검증이 성공했는지 확인한다.

## 로컬 CodeBuild 동등 검증

전체 검증은 CodeBuild와 같은 Node.js 22, Python 3.13, `uv 0.11.2`, Docker와
Compose plugin이 설치된 Linux 환경에서 저장소 루트 기준으로 실행한다.

```bash
infra/delivery/scripts/verify_local_delivery.sh
```

이 명령은 ECR Public PostgreSQL base와 고정 pgvector commit으로 로컬 검증 image를 만들고
disposable DB를 시작한 뒤 다음을 순서대로 검증한다. Docker Hub image는 사용하지 않는다.
컨테이너와 임시 파일은 종료 시 정리한다.

1. AI와 Backend의 frozen lock 설치, format, lint, type, 전체 테스트
2. 빈 DB migration과 두 번째 no-op migration
3. CodeDeploy lifecycle shell 구문과 image metadata 전달 계약 테스트
4. Frontend Verify: clean install, typecheck, 원장 테스트
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
  Pipeline의 `main` source를 검사한다. buildspec이나 stage를 바꾸면 이 계약 테스트도 함께 갱신한다.
- `main` 통합 Pipeline은 merge 이후 배포 gate다. merge 이전 강제 gate가 필요하면 같은
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
terraform plan -var-file=dev.tfvars
# plan 승인 후에만
terraform apply -var-file=dev.tfvars
```

구성의 import block이 기존 Connection ARN을 state로 가져온다. plan에서 Connection replacement 또는 destroy가 보이면 적용하지 않는다.

## Pipeline 실행

논리 이름과 실제 이름은 다음과 같다.

| 용도 | Pipeline |
|---|---|
| 통합 | `skn30-final-3team-dev-integrated` |
| Backend | `skn30-final-3team-dev-backend` |
| Frontend | `skn30-final-3team-dev-frontend` |

최신 `main`은 Console의 Release change 또는 다음 명령으로 시작한다.

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

Pipeline과 CodeDeploy에서는 다음 순서로 확인한다.

1. CodePipeline의 Source revision이 요청한 40자리 SHA인지 확인한다.
2. Backend Build artifact의 image가 `repository@sha256:...` 형식인지 확인한다.
3. CodeDeploy `AfterInstall`에서 설정 조립과 migration이 성공했는지 확인한다.
4. `ApplicationStart`, `ValidateService`가 성공하고 deployment 상태가 `Succeeded`인지 확인한다.
5. Target Group의 유일한 target이 `healthy`인지 확인한다.
6. CloudFront `https://<distribution-domain>/health/ready`가 200을 반환하는지 확인한다.
7. API·Worker CloudWatch log에 revision 전환 이후 지속적인 error가 없는지 확인한다.
8. `/opt/brokerage/deploy-record.json`의 revision, image digest와 Pipeline execution ID가
   실행 이력과 같은지 확인한다. 파일에는 비밀값이 없어야 한다.

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

안전한 `main` 변경으로 통합 Pipeline 자동 실행을 확인한다.

## Rollback

- Backend는 CodeDeploy의 마지막 정상 revision으로 되돌린다. DB down migration은 실행하지 않는다.
- Frontend는 `frontend-releases/<pipeline-execution-id>/index.html` backup을 복원하고 `/`, `/index.html`을 invalidation한다.
- Breaking API 변경은 Frontend 독립 Pipeline으로 배포하지 않는다.
