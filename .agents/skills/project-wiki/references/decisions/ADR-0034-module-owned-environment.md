---
status: 구현됨
updated: 2026-09-09
---

# ADR-0034: 모듈 소유 설정과 enum 선택

상태: 사용자 명시 구현 승인에 따른 코드 변경, 팀 병합 검토 전. 실제 기동·추론과 클라우드 적용은 사용자 수행.
ADR-0015·0030·0033의 Backend dotenv에 AI 입력을 중복 작성하던 방식과 F2 수동 상태 변수를 대체한다.
Backend ADR-0003의 비활성 Worker 계약, Backend ADR-0005의 F2 수동 상태 입력과
AI ADR-0004의 사용자 JSON 주소록 입력도 부분 대체한다.

## 구현 승인과 병합 상태

사용자는 불필요 변수 제거·모듈 책임 분리안을 요청하며 `WORKER_ENABLED`,
`AI_F2_PROVIDER_STATUS`, `AI_LLM_ENDPOINTS`를 직접 지목한 뒤
“개선안을 진행해주세요”와 provider/model 선택값의 enum 제한을 명시했다.
따라서 이 PR의 구현 범위에는 아래 계약의 부분 대체가 포함된다.
이는 사용자 요청 없이 에이전트가 작성한 미확정 후보가 아니다.
출처는 [manifest](../../sources/manifest.yaml)의 `module-owned-environment-approval-2026-09-09`다.

팀 병합 검토 전이라는 표시는 작성자 외 승인과 필수 검사를 아직 대체하지 않았다는 뜻이다.
코드와 이 ADR을 같은 PR에서 검토하며, `dev`에 병합되기 전 공유 환경의 승인된 계약이나
실제 배포 상태가 이미 바뀌었다고 간주하지 않는다.

## 부분 대체 범위

| 기존 계약 | 이 PR의 변경 | 보존하는 동작 |
|---|---|---|
| AI ADR-0004 | 사람이 작성하는 다중 endpoint JSON 입력을 provider/model 선택에서 만든 내부 registry로 교체 | `(provider, endpoint_alias)` exact match·자동 fallback 금지·안전 URL 검사 |
| Backend ADR-0003 | 비활성 대기 Worker 환경변수를 제거하고 실행 여부를 프로세스 시작/중지로 관리 | 고정 readiness probe·기동 전 구성 검증·DB 작업 선점 |
| Backend ADR-0005 | `active/offline` 수동 입력을 URL 쌍 및 검증된 Infra endpoint 문서에서 계산 | 미구성 F2의 `F2_UNAVAILABLE` 503·부분 구성 거부·다른 기능 유지 |

## 모듈 소유 설정

- Backend는 HTTP/DB/인증/업무 제한, AI는 모델/provider/연결/키를 소유한다.
  Infra 로컬 launcher가 각 모듈 파일을 읽고 실행 역할에 필요한 값만 주입한다.
  Backend는 AI 개인 파일을 읽지 않으며 AI binder는 DB/AWS/FastAPI를 모른다.
- `.env.local`은 공개 기본 선택, `.env.example`은 개인 비밀 이름과 주석 처리된 고급 override,
  `.env`는 개인 비밀·override다. 변수마다 목적·허용값/단위·기본값·필수 조건·반영 시점을 기록한다.
- 사용자 확정 기본값은 로컬 `openai`, shared dev `vllm`이다. 개인 OpenAI 이전은 기존 GPU 키·주소를
  Git 제외 0600 원본 백업에 보존하고 활성 입력을 OpenAI로 명시 전환한다.
- ProviderKind, GeneralModel, F2 모델/언어, Backend log, Frontend DataSource를 enum으로 제한한다.
  모델은 기존 지원 프로필을 유지하고 provider/model 조합도 검증한다.
- Worker를 실행하면 처리한다. 비활성 대기 flag·사용자 지정 ID/readiness 경로를 제거한다.
  readiness는 내부 고정 probe로 확인하고 OpenAPI는 local/test에서만 공개한다.
  세션 cookie 이름은 내부 계약으로 고정한다. 데이터 사용 opt-in·DB 용도 검증은 유지한다.
- F2 상태는 URL 쌍과 Infra의 검증된 endpoint 문서에서 계산한다. 미구성 시 503이고 자동 우회하지 않는다.
  일반 endpoint registry는 AI가 선택값에서 구성하며 사람이 JSON 주소록을 작성하지 않는다.
- 모델 설정은 명시 DB 적용 대상이다. Backend model_selection 명령은 사무소/capability 하나에
  새 버전을 추가하고 기존 이력·snapshot을 보존한다. 자동 DB 변경·전체 seed 초기화는 없다.
  진행 요청이 있으면 거부하고 API/Worker 중지 확인을 요구한다. capability별 다른 모델은 보존하되
  실행 연결은 선택 provider와 일치해야 한다. 서로 다른 provider를 동시에 사용하는 추가 연결 설정은 제공하지 않는다.
- 현재 AWS Secret 원본 필드는 유지하고 선택 provider에 따라 명시 매핑한다. API/Worker에 필요한
  범용 키만 전달하고 챗봇 비활성 API에는 범용 키를 제외한다. Worker에는 F2/embedding 키를 전달하지 않는다. migration은 DB URL만 받는다.
- CHATBOT_ENABLED, 개발 인증의 서버 허용/화면 표시, DB_TARGET, 합성 데이터 opt-in은 목적이 있어 유지한다.
  새 HTTP capability 조회 같은 기능은 이번 설정 변경에 추가하지 않는다.

이전과 사용자 검증은 [환경변수 관리](../../../../../docs/development/environment-variables.md)가 정본이다.
설정 입력 구조 변경과 인프라 실제 적용 상태를 구분하며, 예전 plan은 재생성·검토 후에만 사용한다.
