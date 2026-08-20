---
status: 결정
updated: 2026-08-20
---

# ADR-0008: 개발 DB 계정과 IAM 인증 관리

- 상태: 승인됨
- 결정일: 2026-08-19
- 수정일: 2026-08-20

## 맥락

개발 RDS의 master 계정을 Backend와 migration에 공유하지 않고 runtime DML, Yoyo DDL, 개인 개발자 접속을 분리해야 한다. 실제 비밀번호를 Terraform state에 저장하지 않으면서 DB 역할과 Secrets Manager 값을 재현 가능하게 초기화하고 회수할 운영 절차도 필요하다.

Backend는 현재 일반 실행에도 `DB_MIGRATION_URL`을 요구하므로 migration Secret 컨테이너를 즉시 제거할 수 없다. Backend 변경은 이번 Infra 작업에서 제외한다.

## 결정

### 인증과 역할

- RDS master `dbadmin`은 RDS가 생성·회전하는 Secrets Manager secret을 사용하며 초기화와 복구에만 사용한다.
- `app_owner`는 로그인하지 않는 객체 소유 역할이다.
- `app_rw`는 로그인하지 않는 runtime DML 권한 역할이다.
- `app_runtime`은 비밀번호 로그인과 `app_rw`만 사용하며 DDL과 role 관리를 허용하지 않는다.
- `app_migrator`는 비밀번호 없이 IAM DB 인증을 사용하고 `app_owner`로 전환할 수 있다. 미래 delivery identity의 migration 연결점으로 남긴다.
- `team-db-tunnel`의 모든 IAM 사용자는 같은 이름의 PostgreSQL LOGIN 역할, `rds_iam`, `app_owner` 권한을 받는다.
- 개인 DDL 권한은 개발 환경에만 허용한다. DDL은 커밋된 Yoyo migration으로만 실행하고 운영 승격 전 개인 `app_owner` 권한을 제거한다.
- Yoyo는 `PGOPTIONS=-c role=app_owner`로 실행해 객체 소유자가 개인 계정이 되지 않게 한다.

### Secret과 Terraform 경계

- Terraform은 RDS IAM DB 인증, IAM 정책, Secret 컨테이너와 경보를 소유한다.
- RDS가 master secret의 실제 값을 소유한다.
- Backend runtime Secret의 실제 값은 Terraform 밖에서 구조화된 JSON으로 주입하며 Terraform 코드, plan, output과 state에 넣지 않는다.
- runtime Secret JSON은 `engine`, `host`, `port`, `dbname`, `username`, `password` 필드를 사용한다.
- migration은 실행 직전에 만든 15분 IAM 토큰을 `DB_MIGRATION_URL`로 주입하며 장기 비밀번호를 저장하지 않는다.
- 기존 migration Secret 컨테이너는 Backend 호환을 위해 비어 있는 deprecated 자원으로 유지한다. Backend의 필수 설정이 분리된 후 별도 Terraform 변경으로 제거한다.
- IAM 사용자 생성·삭제와 `team-db-tunnel` 멤버십은 Terraform에서 관리하지 않는다.

### 운영 도구

- `infra/scripts/manage_db_access.py`는 Backend와 분리된 PEP 723 `uv` Python 도구다.
- `bootstrap --apply`는 `TerraformOperatorRole`을 assume해 고정 역할, runtime 비밀번호, runtime Secret과 현재 그룹 멤버의 DB 역할을 초기화한다.
- `sync-team --apply`는 그룹 멤버를 DB 역할과 동기화한다. 제거된 사용자는 권한을 회수하고 `NOLOGIN`으로 바꾸며 활성 세션을 종료하되 role은 감사 목적으로 보존한다.
- `rotate-runtime --apply --maintenance-window-confirmed`는 pending Secret과 DB 비밀번호를 검증한 뒤 current version을 전환한다.
- `migrate --apply`는 개인 IAM 사용자로 SSM 터널과 IAM 토큰을 만들고 Yoyo를 실행한다.
- `verify`는 runtime credential과 필수 역할을 읽기 전용으로 검증한다.
- 도구는 장기 비밀번호, AWS 자격 증명과 전체 접속 URL을 출력하거나 저장소에 기록하지 않는다.
- `client-info`는 사용자가 psql Password 프롬프트나 GUI 클라이언트에 직접 입력할 수 있도록 15분 IAM DB 토큰만 명시적으로 한 번 출력한다. 토큰을 셸 명령에 삽입하지 않으며 터미널 로그·화면 공유 노출 방지와 사용 후 클립보드 삭제를 안내한다.
- psql은 RDS hostname과 로컬 SSM tunnel 주소를 분리하고 CA bundle 기반 `verify-full`을 사용한다. localhost만 받는 GUI 클라이언트는 CA chain을 검증하는 `verify-ca`를 사용한다.

### 관측과 실행 책임

- IAM DB 인증의 추가 메모리 사용을 확인하기 위해 RDS `FreeableMemory < 256 MiB` 경보를 기존 runtime SNS topic에 연결한다.
- Terraform apply, bootstrap, 그룹 동기화, migration, 적용 후 검증과 drift plan은 운영자가 명시적으로 실행한다.
- 이 ADR 구현은 AWS apply, DB 역할 생성, Secret value 쓰기와 migration 실행을 자동 수행하지 않는다.

## 결과

runtime과 migration 권한이 분리되고 사람은 공유 DB 비밀번호 없이 개인 IAM identity로 migration을 실행할 수 있다. 그룹 제거 후 DB 권한 회수는 명시적 동기화가 필요하다. 모든 팀원이 dev DDL 권한을 가지므로 migration 검토와 Yoyo 전진 적용 규칙이 핵심 운영 통제가 된다.
