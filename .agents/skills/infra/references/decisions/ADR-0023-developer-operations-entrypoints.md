---
status: 구현됨
updated: 2026-09-09
---

# ADR-0023: 개발자 운영 진입점과 검증 인계

- 상태: 사용자 개선 요청으로 구현, 팀 병합 검토 전. 실제 기동 검증은 사용자 수행.
- 유지: Terraform/SSM/Secrets Manager 소유권, 개인 dotenv 경계, 수동 전원·명시적 모델 선택.

## 결정

- just의 env-doctor/env-fix, doctor/release-ready, dev-verify를 개발자 진입점으로 둔다.
- doctor는 자원·Secret 구조만 조회한다. daemon·추론·SSM RunCommand·전원 변경이 없다.
- dev-verify는 기동된 앱·active endpoint에 기존 합성 smoke만 실행한다. 모델 선택·배포·GPU 생성은 하지 않는다.
- 개인 파일 정리는 해당 checkout의 ignored `.env`만 대상으로 한다. 중복 이름·symlink·추적 파일은 수정하지 않는다.
- saved plan은 600 권한·입력 fingerprint·plan hash·24시간 유효기간을 기록한다.
  변경·만료 시 재계획·재검토한다. seal은 apply 승인을 뜻하지 않는다.
  PR 검토 후 root 하위 재귀 입력과 Dockerfile·정책·템플릿 추적, symlink 거부를 보강했다.
  수집 범위와 제외 규칙은 [Terraform 기준](../terraform-standards.md)이 정본이다.
  metadata schema 2 이전 plan은 재생성하고 다시 검토한다.
- state bucket 비운영자 Deny를 ListBucketVersions/GetObjectVersion/DeleteObjectVersion까지 확대한다.
  2026-09-09 사용자 명시 승인 후 bootstrap 적용·AWS 조회·drift 없음 검증을 완료했다.
- shared dev provider/model/region은 Terraform의 검증된 `general_model_selection` 객체로 관리한다.
  endpoint 모델과 공개 선택이 다르면 배포를 거부한다.
- 최초 전환 plan은 `app_deployment_mode=maintenance`로 CodeDeploy/ASG 자동 연결을 해제하고
  앱의 Project/Environment/Name 태그를 모두 일치시키는 배포 대상을 사용한다. 구 revision 자동 배포를 방지하며
  새 Pipeline revision 성공 후 `automatic` 연결 복구 plan을 검토한다. Terraform 운영 입력으로만 관리한다.
  기본값 `automatic`은 유지한다. 최초 전환 파일은 seal/check 양쪽에서 실제 saved plan의 입력과
  예정 배포 대상을 검사하며, 잘못된 plan을 이름만 바꿔 사용하는 것을 차단한다.
  태그는 각각 하나의 `ec2_tag_set`에 넣는다. [AWS EC2TagSet 계약](https://docs.aws.amazon.com/codedeploy/latest/APIReference/API_EC2TagSet.html)은
  그룹 간 AND이며 그룹 내부는 OR다. 세 태그를 하나의 그룹으로 합치면 대상이 넓어지므로 금지한다.
- 최초 `dev-prepare-app`은 GPU 직접 검증·endpoint 게시 후 앱 호스트를 준비하고 최신 Pipeline 배포를 기다린다.
  실제 기동과 직접 추론이 포함되므로 사용자가 검증 창에서 실행한다.
- 원격 모델 변경은 사무소·capability 하나씩, API/Worker 중지 및 대기 요청 부재에서만 실행한다.
  모델 선택만으로 재시작하거나 추론하지 않는다.
- 일상 절차는 infra/operations/README.md, 적용 현황은 resource-inventory, 과거 결정은 ADR, 검증 증거는 날짜별 기록이 소유한다.
- F2 release ID는 전달 manifest 내부 ID를 사용한다. 번들 검증·S3 게시·기동·품질 승격은 별도다.

## 검증 범위

오프라인 테스트로 비밀 비출력·설정 보존·이미지 검사·stale plan 차단·진단 무변경을 확인한다.
신규 consultation-v3는 기존 release와 분리하며 원본 bundle은 Git에 넣지 않는다.
개인/학습 자원은 담당자·보존 기한 확인 목록으로 남기고 승인 없이 삭제하지 않는다.
