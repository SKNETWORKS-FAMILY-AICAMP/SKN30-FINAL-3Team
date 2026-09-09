---
status: 구현됨
updated: 2026-09-09
---

# ADR-0033: 환경변수 입력과 관리 기준 정리

> 환경변수 입력·주입 계약은 [ADR-0034](ADR-0034-module-owned-environment.md)에서 부분 대체한다.

사용자 리팩토링 승인으로 구현했으며 팀 병합 검토 전이다. 실제 기동·추론은 사용자 수행이다.
ADR-0015의 파일 소유권·우선순위를 유지하고, 선택 공개 override를 예시에서 주석으로 제공하도록 보완한다.

- 모듈 config가 이름·타입·기본값·검증 정본이다. 별도 환경변수 JSON schema를 만들지 않는다.
- `.env.local`은 주석이 있는 공개 기본값, `.env.example`은 빈 개인 비밀 입력과 주석 처리된 선택 override,
  ignored `.env`는 실제 개인 입력을 소유한다. 선택 URL을 빈 할당으로 복사해 기본값을 덮지 않는다.
- Backend F3 합성 opt-in을 config에 바인딩한다. Worker의 중복 boolean 파서는 제거하고,
  DB·Provider 접근 전의 별도 opt-in 검사는 유지한다. local 우선순위와 non-local dotenv 미사용은 유지한다.
- boolean 작성 표준은 true/false다. Backend의 기존 별칭 입력은 읽기 호환만 유지한다.
- 로컬 F2 공개 기본값을 코드 기본값과 같은 offline으로 바꾸고, 미사용 embedding URL 기본값을 제거한다.
  연결 도구·사용자 입력으로 active와 URL·키를 명시한다. 공유 endpoint·DB 모델은 자동 변경하지 않는다.
- 기능별 source override, 인증 UI/서버 구분, Terraform 전원 입력과 SSM·DB 모델 선택은 역할에 맞게 유지한다.
- env-doctor는 소비 코드와 개인 입력 예시에서 이름을 찾고 비밀값 없는 모드·출처·조합을 표시한다.
  완전한 dotenv/type/DB 검증을 대신하지 않는다. 문서 누락을 오프라인 검사로 감지한다.

사람용 작성 절차는 [환경변수 관리](../../../../../docs/development/environment-variables.md),
공통 정책은 [개발환경](../development/environments.md), 클라우드 주입은 Infra가 소유한다.
