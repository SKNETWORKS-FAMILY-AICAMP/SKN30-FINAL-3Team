---
name: frontend
description: "`frontend/`의 React·TypeScript 화면, 상태, 접근성, API 연동과 프론트엔드 구조·의존성·검증을 개발하거나 변경할 때 사용한다."
---

# 프론트엔드 개발

`frontend/`는 화면, 사용자 상호작용, 브라우저 상태와 API 표현을 소유한다. 서버 업무 규칙, AI 실행, 데이터 파이프라인과 IaC를 복제하지 않는다. 저장소 지침과 승인된 프로젝트·모듈 결정이 일반 설계 권장안보다 우선한다.

## 필요한 문서 선택

공통 탐색·결정 확인·지식 갱신은 루트 `AGENTS.md`와 project-wiki를 따른다. [참조 인덱스](references/index.md)에서 작업에 해당하는 문서만 읽는다.

| 변경 | 읽을 정본 |
|---|---|
| UI 화면·컴포넌트·스타일·상호작용 | [디자인 가이드](references/design/index.md)와 해당 세부 가이드. 모든 UI 작업은 접근성 가이드를 확인하고 완료 시 디자인 검토 체크리스트 적용 |
| Screen ID·화면 상태·소유권·이동 | `docs/screen/index.md`와 해당 화면 문서 |
| API 요청·응답·오류·권한 해석 또는 변경 | project-wiki의 `contracts/api.md`에서 해당 기능 계약 |
| 개인정보가 화면·저장소·URL·분석·로그를 통과 | project-wiki 개인정보 정책 |
| 구조·라이브러리·개발 방식 | [결정 인덱스](references/decisions/index.md)와 관련 ADR |

## 유지할 기준

- 새 운영 코드는 TypeScript `.ts`·`.tsx`와 `strict`를 사용한다. 기존 JavaScript는 안전한 변경 범위에서 점진적으로 전환한다. 설치 버전·설정은 `frontend/package.json`, lockfile과 `tsconfig`로 확인한다.
- API 응답, URL, 사용자 입력과 브라우저 저장 데이터는 런타임에서 검증한다. `any`나 무검증 타입 단언으로 오류를 숨기지 않는다.
- 관리자 UI는 PatternFly 6, 복잡한 표는 AG Grid Community, 단순 표는 PatternFly Table을 따른다. Enterprise 기능은 별도 라이선스·비용 승인이 필요하다. semantic token과 공통 컴포넌트를 재사용하고 화면별 임의 테마를 만들지 않는다.
- 관련 loading·empty·no-match·error·offline·permission-denied·재시도 상태를 정의한다. 비동기 요청의 취소, 중복 제출과 순서 역전을 처리한다.
- 네트워크·DTO 변환은 기능별 API 경계에서 다룬다. API 계약 변경을 화면 내부 우회로 해결하지 않는다. 비밀값을 번들·로그·URL·브라우저 저장소에 넣지 않는다.
- WCAG 2.2와 디자인 시스템의 키보드 패턴을 적용한다. 키보드·포커스·반응형·상태 전달을 보장하고 의미를 색상만으로 전달하지 않는다.
- 새 공통 계층·상태·의존성은 실제 결합 문제나 반복이 있을 때 도입한다. 새 표준은 모듈 ADR로 남긴다. 권장안·디자인 규칙 예외는 이유, 사용자 이점, 영향, 검증과 공통화 여부를 PR에 기록한다.

## 검증

저장소 명령으로 변경 범위에 맞는 타입 검사, 관련 테스트와 프로덕션 빌드를 실행한다. 사용자 흐름과 실패·복구 상태, 키보드·포커스·반응형을 확인한다. 접근성 자동 검사는 수동 동작 검토로 보완하고 개인정보·성능·라이선스·API 계약 영향을 점검한다. 실행하지 못한 검증과 이유를 보고한다.
