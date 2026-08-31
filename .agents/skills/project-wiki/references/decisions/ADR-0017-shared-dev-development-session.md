---
status: 결정
updated: 2026-08-27
---

# ADR-0017: 공유 AWS dev 환경과 합성 개발 세션

- 상태: 승인됨
- 결정일: 2026-08-27
- 수정일: 2026-08-27
- 대체 범위: [Backend ADR-0002](../../../backend/references/decisions/ADR-0002-backend-runtime-database-authentication.md)의 개발 세션 `local` 전용 조항
- 관련 결정: [ADR-0009](ADR-0009-dev-demo-operating-constraints.md), [ADR-0015](ADR-0015-environment-configuration-ownership.md)

## 맥락

`infra/environments/dev`는 합성·비식별 데이터를 사용하는 공유 개발·시연 환경이지만 Backend에는
`local`, `test`, `prod`만 있어 배포 설정이 이를 `prod`로 표시했다. 그 결과 실제 운영 보안 기준을
갖추지 않은 환경이 운영으로 오인되고, 이미 구현된 개발 세션 API와 Frontend 진입 버튼도 서로 다른
설정으로 동작했다.

실제 비밀번호 로그인은 현재 MVP 범위 밖이다. 공유 환경에서 F1·F2·F3 흐름을 시연하려면 실제
자격증명을 도입하지 않고도 고정된 합성 사용자 문맥을 안전하게 발급할 수 있어야 한다.

## 결정

- 애플리케이션 환경은 `local`, `test`, `dev`, `prod`를 구분한다. 현재 AWS root는 `dev`이며 실제
  `prod` Terraform root는 아직 없다.
- Backend의 `dev`는 `DB_TARGET=development`만 허용한다. Backend와 AI의 `dev`, `test`, `prod`는
  저장소 dotenv를 읽지 않고 배포 프로세스 환경변수만 사용한다.
- 개발 세션 API는 `local`과 공유 `dev`에서 명시적으로 설정했을 때만 등록한다. `prod`에서는 설정과
  관계없이 금지하며 실제 비밀번호 로그인 API를 이 결정으로 추가하지 않는다.
- 공유 dev의 개발 계정 식별자는 ignored `dev.tfvars`의 비민감 입력으로 관리한다. Terraform의 같은
  입력에서 Backend API 활성화와 Frontend 버튼 표시를 함께 파생한다.
- 공유 dev 세션은 유휴 30분, 절대 12시간으로 제한하고 브라우저 Cookie에 `Secure`, `HttpOnly`,
  `SameSite=Lax`를 적용한다. 원문 세션·CSRF 토큰을 저장하거나 로그로 남기지 않는 기존 계약은 유지한다.
- CloudFront 기본 도메인은 WAF·IP 제한 없이 공개한다. URL을 아는 누구나 같은 개발 계정의 세션을
  발급받을 수 있으므로 실제 개인정보, 실제 로그인 ID, 비밀번호와 인증정보는 dev에 넣지 않고
  명백한 합성·비식별 데이터만 사용한다.
- 계정 생성과 Backend sample seed 명령은 `local` 애플리케이션 경계에서 실행한다. 운영자가 개인 IAM
  인증과 SSM 터널로 공유 development DB를 지정하는 것은 배포 API에 관리 기능을 노출하는 것이 아니다.
- `docs/db/seed/`의 검토된 F3 합성 reset·seed·verify 세 파일은 공유 dev에도 적용할 수 있다. Infra의
  `seed-f3 --apply`만 이 예외를 구현하며, 명시적 확인 뒤 파일을 고정 순서로 실행하고 29개 검사가
  모두 `PASS`일 때만 완료한다. 대상은 현재 Terraform dev RDS와 `F3_SYNTHETIC` 사무소로 제한하고
  개인 IAM·SSM 터널·15분 DB token을 사용하며 token·DB URL을 출력하지 않는다. prod와 임의 DB 적용,
  임의 SQL 경로 입력과 migration 자동 편입은 계속 금지한다.

## 결과

공유 AWS 배포는 이름과 실제 보안 수준이 일치하고, 기존 서버 세션·CSRF 계약과 로그인 화면을 그대로
사용해 합성 데모에 진입할 수 있다. Frontend 공개 플래그는 화면 표시만 제어하며 Backend route가 최종
권한 경계다.

실제 prod 로그인은 계속 제공되지 않는다. 실사용 전에는 별도 prod 환경, 사용자 도메인, 종단 간 TLS,
접근 통제, 자격증명 검증, 비밀번호 저장·회전과 실패 제한 정책을 새 결정과 계약으로 승인해야 한다.
