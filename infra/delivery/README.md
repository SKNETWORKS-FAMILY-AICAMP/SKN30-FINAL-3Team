# Development CI/CD runbook

이 문서는 저장소 구현을 AWS dev 환경에 적용하는 승인 경계를 설명한다. 애플리케이션 Pipeline은 Terraform을 실행하지 않는다.

## 적용 전 gate

- 현재 dev 변경을 저장소 Git 정책에 맞는 PR로 `main`에 병합한다.
- `.github/workflows/pr-policy-review.yml`의 별도 사용자 변경은 이 delivery 변경과 섞지 않는다.
- `pipeline_operator_user_names`가 승인된 기존 IAM 사용자만 포함하고 `student` 외 추가 사용자가 없는지 확인한다.
- `SKN30_FINAL` Connection이 `AVAILABLE`이고 승인된 repository만 접근하는지 확인한다.
- Discord secret container에 `{"webhook_url":"..."}` 값을 저장소와 Terraform 밖에서 주입한다.
- Frontend/Backend 정적 검사, migration, Docker/Compose 검증이 성공했는지 확인한다.

## 최초 Terraform 적용

최초 적용은 통합 자동 감지와 ELB health 전환을 보류한다.

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

## 검증 순서

1. Backend 독립 Pipeline으로 첫 정상 CodeDeploy revision을 만든다.
2. Frontend 독립 Pipeline으로 첫 정적 release를 배포한다.
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
