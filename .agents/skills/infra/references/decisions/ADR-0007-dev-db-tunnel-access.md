---
status: 결정
updated: 2026-08-19
---

# ADR-0007: 개발 DB 터널 접근

- 상태: 승인됨
- 결정일: 2026-08-19

## 맥락

개발 RDS는 private subnet에 있고 public access를 허용하지 않는다. 팀원의 로컬 PC에서 개발 DB를 점검하려면 RDS를 공개하거나 SSH 포트를 여는 대신, SSM 관리형 EC2를 경유하는 제한된 터널이 필요하다.

## 결정

- `infra/environments/dev`가 `team-db-tunnel` IAM 그룹과 관련 정책 연결을 소유한다.
- 그룹에는 AWS 관리형 `SignInLocalDevelopmentAccess`와 프로젝트·환경·관리 태그가 일치하는 dev EC2에서만 `AWS-StartPortForwardingSessionToRemoteHost`를 시작하는 고객 관리형 정책을 연결한다.
- interactive shell용 SSM 문서, Run Command, SSH 인바운드는 허용하지 않는다.
- IAM 사용자 생성·삭제와 그룹 멤버 추가·제거는 Terraform에서 관리하지 않는다.
- PostgreSQL 사용자, 비밀번호와 데이터 권한은 IAM 터널 권한과 분리해 관리한다.

## 결과

팀원은 장기 access key 없이 `aws login` 세션과 Session Manager plugin으로 dev app EC2를 경유해 private RDS에 접근할 수 있다. AWS 관리형 remote-host 문서는 사용자가 목적지 host와 port를 입력하므로, 실제 도달 범위는 app security group의 outbound 규칙에도 의존한다. 현재 PostgreSQL 5432는 database security group으로만 허용되며, 목적지 고정이 필요해지면 별도의 사용자 정의 SSM 문서를 검토한다.
