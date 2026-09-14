# 환경변수 정리 기록

2026-09-09, `origin/dev`의 `4b5d002`를 병합한 별도 워크트리에서 사용자 요청으로 리팩토링했다.
최종 작성·이전·실행 절차는 [환경변수 관리](../../docs/development/environment-variables.md),
공통 결정은 [ADR-0034](../../.agents/skills/project-wiki/references/decisions/ADR-0034-module-owned-environment.md)가 소유한다.

| 문제 | 최종 수정 |
|---|---|
| Worker 비활성 대기와 불필요한 경로/ID 입력 | WORKER_ENABLED/READY_FILE/ID 제거, 실행 자체가 처리 시작, 내부 probe와 자동 ID |
| OpenAPI와 cookie 이름의 불필요한 조절점 | OpenAPI는 APP_ENV에서 결정, cookie 이름 내부화 |
| Backend/AI 입력 중복 | AI 파일 단일 소유, Infra launcher 명시 주입, 잘못된 모듈 파일 거부 |
| JSON 주소록만 있고 범용 선택값 없음 | AI_GENERAL_PROVIDER/MODEL와 연결 입력, enum 조합 검증, 내부 registry 구성 |
| 모델 선택 정본 혼동 | 환경값은 명시 적용 대상, DB는 capability별 적용 버전·snapshot; 새 버전 추가 명령 |
| F2 수동 상태 flag | URL 쌍과 Infra endpoint에서 내부 상태 계산, 미구성 503 유지 |
| 선택 URL 빈 예시·embedding/STT 주소 충돌 | 고급 override 주석 처리, 미사용 embedding 기본 주소 제거 |
| 변수별 주석 부족 | 각 변수마다 목적·허용값/단위·기본값·조건·반영 시점 기록 |
| 과도한 Secret 전달 | Worker에 F2/embedding 제외, 챗봇 비활성 API에 범용 키 제외, migration DB URL만 전달 |
| 진단 오류의 비밀 노출 가능성 | 잘못된 enum 값을 포함한 config 오류 원문을 CLI에 출력하지 않음 |

AUTH 서버/UI, 기능별 source, 합성 데이터 opt-in, DB_TARGET은 목적을 유지한다.
서로 다른 provider의 동시 연결은 제공하지 않으며 provider 전환 시 사용하는 capability도 명시 반영한다.
실제 개인 파일·공유 Secret·SSM·클라우드 전원·DB 활성 모델은 이 리팩토링에서 변경하지 않았다.

검증: Backend 단위 294, AI 단위 434, Infra 232, Frontend 환경 21·release 2 = 983개 통과.
Backend/AI Ruff·Pyright, Frontend 타입/빌드, Terraform dev validate, 문서 링크·스킬 검사 통과.
CLI local-config/model 미리보기와 잘못된 enum 비밀값 비출력을 합성 입력으로 확인했다.
실제 DB migration·서비스 기동·모델 추론은 사용자 수행이다.
