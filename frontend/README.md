# Frontend

부동산 중개 원장(F1), 음성 AI 입력 자동화(F2), 멀티 에이전트 중개 판단(F3), 그리고 지능형 업무 어시스턴트 챗봇을 제공하는 React 19 기반 웹 애플리케이션입니다.

---

## 주요 기능

- **중개 원장 및 상담 관리 (F1 / `src/features/ledger`, `timeKeeper`)**:
  - AG Grid 기반 매물 및 구입 원장 그리드 (고속 필터링, 정렬, 행 추가/수정/삭제)
  - 상세 워크스페이스, 고객/단지 마스터 연동 및 상담 로그 타임라인
- **음성 상담 AI 입력 자동화 (F2 / `src/features/f2`)**:
  - 현장 상담 음성메모 파일 업로드 및 STT 전사·필드 추출 진행 상태 표시
  - 원문 근거(Evidence) 및 기존 장부값과의 차이점(Diff) 검토 모달
  - 중개사 수정 및 1-Click 승인을 통한 원장 데이터 자동 반영
- **멀티 에이전트 중개 판단 (F3 / `src/features/f3`)**:
  - 매물 및 손님 측 포지션 카드(입장, 제약, 유연성) 뷰어
  - 비동기 에이전트 실행 상태 폴링 및 결과 조회
  - 중개 성사 가능성(High/Med/Low), 타협안, 리스크를 포함한 판정 리포트 렌더링
- **지능형 업무 어시스턴트 챗봇 (`src/features/chatbot`)**:
  - 자연어 질의를 통한 장부 조건 검색(매물, 구입 조건, 일정 등)
  - Server-Sent Events (SSE) 기반 실시간 스트리밍 응답
  - 대화 히스토리 영속화 및 F2 음성 분석 모달 직접 호출 연동
- **인증 및 세션 (`src/features/auth`)**:
  - 로컬/개발 환경용 개발 세션 원클릭 로그인 지원 (`VITE_AUTH_DEVELOPMENT_ENABLED=true`)
  - 안전한 세션 쿠키 기반 API 통신

---

## 요구사항

로컬에서 `frontend/`를 설치하고 실행하려면 다음 환경이 필요합니다.

- **Node.js `22.18.0` 이상** (CodeBuild와 동일한 22 major version 권장)
- **npm `11.x` 이상**
- 개발 서버에 접속할 최신 웹 브라우저 (Chrome 권장)
- (선택) 전체 기능 확인 시 로컬 Backend API 서버(`http://127.0.0.1:8000`)

---

## 설치

Node.js와 npm을 준비한 뒤 `frontend/`에서 의존성을 설치합니다.

```bash
cd frontend
npm ci
```

의존성 버전은 `package-lock.json`으로 고정되어 있습니다.

---

## 로컬 실행

개발 서버를 실행합니다.

```bash
cd frontend
npm run dev
```

터미널에 표시된 로컬 주소(`http://localhost:5173`)를 브라우저에서 엽니다.

### 주요 npm 명령어

```bash
npm run dev           # Vite 개발 서버 실행 (기본 포트: 5173)
npm run build         # 프로덕션 번들 빌드 (dist/client)
npm run preview       # 빌드 결과 로컬 미리보기
npm run typecheck     # TypeScript strict 타입 검사
npm run test:ledger   # 원장 변환 및 데이터 매핑 테스트
npm run test:auth     # 인증 계약 및 로그인 화면 테스트
npm run test:env      # 환경변수 우선순위 및 유효성 검증 테스트
npm run test:release  # release 산출물 구조 검사
```

---

## 환경변수 설정

- `frontend/.env.local`은 비민감 팀 공통 로컬 값으로 Git에서 관리합니다.
- 개인별 재정의가 필요하면 Git에서 제외된 `frontend/.env`에 변경할 키만 작성합니다.
- 우선순위는 `process env > .env > .env.local`입니다.
- `.env.production`, `.env.development` 같은 profile 파일은 사용하지 않습니다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | API 호출 상대 경로 (CloudFront 및 Vite Proxy 대상) |
| `FRONTEND_BACKEND_ORIGIN` | `http://127.0.0.1:8000` | 로컬 Vite proxy 대상 Backend 주소 (번들에 미포함) |
| `VITE_AUTH_DEVELOPMENT_ENABLED` | `true` (로컬) | 로그인 화면의 '개발용 세션으로 로그인' 버튼 노출 여부 |

> [!NOTE]
> `VITE_` prefix가 붙은 변수는 브라우저 번들에 포함되므로 비밀값을 절대 기록하지 않습니다.

---

## 디렉터리 구조 및 주요 컴포넌트

```text
frontend/
├── src/
│   ├── main.jsx                  # React 진입점
│   ├── AppShell.jsx              # 전체 레이아웃 (네비게이션, 챗봇 플로팅 패널)
│   ├── features/
│   │   ├── auth/                 # 로그인 화면, 세션 관리 훅
│   │   ├── ledger/               # 매물/구입 원장 AG Grid 및 워크스페이스
│   │   ├── f2/                   # 음성 업로드, STT 결과, Diff 검토 모달
│   │   ├── f3/                   # 포지션 카드, 판정 리포트 뷰어
│   │   ├── chatbot/              # 챗봇 패널, SSE 스트리밍 훅, 검색 카드
│   │   ├── timeKeeper/           # 상담 로그 및 고객 타임라인
│   │   └── calendar/             # 일정 캘린더
│   ├── data/                     # 프로토타입/목업 데이터
│   └── styles.css                # 공통 스타일
├── package.json
└── vite.config.mjs               # Vite 및 프록시 설정
```

---

## 코드 품질 검증

저장소 루트에서 다음 스크립트를 실행하여 CI와 동일한 정적 검사를 수행할 수 있습니다.

```bash
infra/delivery/scripts/verify_frontend.sh
```
