# 기반 saved plan 검토

작성·적용일: 2026-09-07. **사용자 승인 후 적용 완료**. 현재 deep suspend를 유지한다.

- 파일: `infra/environments/dev/dev-serving-foundation.tfplan`
- SHA-256: `728d371db88a4f4194d5fb2df598b3d30e897a58e378d93c1b9765bf194b612f`
- 같은 plan을 `dev.tfplan`에도 복사하여 `dev-show`/`dev-apply`로 검토·적용할 수 있다.
- 변경 합계: 9개 생성, 7개 변경, 16개 삭제.
- 입력: 기존 `dev.tfvars`, `dev_edge_enabled=false`, `dev_gpu_enabled=false`; GPU profiles 기본 빈 집합.
- 신규 GPU·EBS·ALB 생성 없음. RDS·업무 S3·모델 release 삭제 없음.
- 기존 사용자 승인 감시 축소 변경도 포함한다. RunPod 감시 Lambda·주기 실행·8개 경보·전용 IAM/Secret·로그 그룹을 제거한다. 로그 그룹 삭제는 과거 감시 로그도 삭제하므로 별도 보존이 필요하면 적용 전에 내보낸다.
- 신규 general endpoint·등록·selection SSM 문서와 고정 포트 SSM 문서·팀 GPU 그룹을 만든다.
- 기존 앱 Launch Template의 Bedrock hop-limit 변경, IAM/Secret 설명·기존 RunPod 등록 설명 변경을 포함한다. 기존 ready 등록 값은 덮어쓰지 않는다.
- 일부 SSM 설정은 기존 범용 Provider 준비 변경이다. DB 활성 모델은 변경하지 않는다.
- 실제 GPU 배포는 이미지 게시·등록·AMI 검증과 별도 GPU plan 검토 이후다.

| 변경 | 자원 |
|---|---|
| update | `aws_autoscaling_group.app` |
| delete | `aws_cloudwatch_event_rule.runpod_monitor` |
| delete | `aws_cloudwatch_event_target.runpod_monitor` |
| delete | `aws_cloudwatch_log_group.runpod_monitor` |
| delete | `aws_cloudwatch_metric_alarm.runpod["control_plane_unreachable"]` |
| delete | `aws_cloudwatch_metric_alarm.runpod["endpoint_mismatch"]` |
| delete | `aws_cloudwatch_metric_alarm.runpod["offline_orphan"]` |
| delete | `aws_cloudwatch_metric_alarm.runpod["runtime_warning"]` |
| delete | `aws_cloudwatch_metric_alarm.runpod["sllm_unhealthy"]` |
| delete | `aws_cloudwatch_metric_alarm.runpod["stt_unhealthy"]` |
| delete | `aws_cloudwatch_metric_alarm.runpod_monitor_errors` |
| delete | `aws_cloudwatch_metric_alarm.runpod_monitor_heartbeat` |
| create | `aws_iam_group.team_gpu_tunnel` |
| create | `aws_iam_group_policy.team_gpu_tunnel` |
| update | `aws_iam_policy.sllm_release_publisher` |
| update | `aws_iam_policy.team_db_tunnel` |
| delete | `aws_iam_role.runpod_monitor` |
| update | `aws_iam_role_policy.app_runtime` |
| delete | `aws_iam_role_policy.runpod_monitor` |
| delete | `aws_lambda_function.runpod_monitor` |
| delete | `aws_lambda_permission.runpod_monitor_schedule` |
| update | `aws_launch_template.app` |
| update | `aws_secretsmanager_secret.runpod["ghcr_registry"]` |
| delete | `aws_secretsmanager_secret.runpod["monitor_api_key"]` |
| create | `aws_ssm_document.gpu_tunnel["f2_sllm"]` |
| create | `aws_ssm_document.gpu_tunnel["f2_stt"]` |
| create | `aws_ssm_document.gpu_tunnel["general"]` |
| create | `aws_ssm_parameter.application["ai_ai_llm_endpoints"]` |
| create | `aws_ssm_parameter.general_endpoint` |
| create | `aws_ssm_parameter.general_runpod_control` |
| update | `aws_ssm_parameter.runpod_control_set` |
| create | `aws_ssm_parameter.serving_selection` |

## 실행한 명령

```bash
AWS_PROFILE=skn30-session terraform -chdir=infra/environments/dev apply dev-serving-foundation.tfplan
AWS_PROFILE=skn30-session terraform -chdir=infra/environments/dev plan -input=false -detailed-exitcode -var-file=dev.tfvars -var=dev_edge_enabled=false -var=dev_gpu_enabled=false
```

다른 apply나 외부 변경으로 state가 바뀌었으면 saved plan을 다시 생성하고 재검토한다. 이 파일은 전체 plan의 민감값을 복사하지 않은 검토 요약이다.


## 적용 검증 결과

- Terraform apply: **9 added, 7 changed, 16 destroyed**, 종료 코드 0.
- 같은 입력의 drift plan: **No changes**, 상세 종료 코드 0.
- 앱 ASG desired 0·인스턴스 0, RDS stopped, CloudFront disabled, 관리 AWS GPU 0대를 확인했다.
- RDS resource identity, 업무 S3 버킷 3개와 기존 F2 RunPod 등록값이 보존됐다.
- 신규 SSM 터널 문서 3개는 Active이며 general endpoint는 offline, general 등록은 uninitialized,
  f2/general 선택은 null이다. GPU 실배포를 활성화한 상태가 아니다.
- 기존 RunPod 감시 Lambda·주기 실행·8개 경보가 제거됐다.
- 이 saved plan은 적용 이력이다. 재적용하지 말고 후속 변경은 새 plan으로 검토한다.
