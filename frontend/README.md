# Frontend

## 요구사항

로컬에서 `frontend/`를 설치하고 실행하려면 다음 환경이 필요합니다.

- Node.js `22.18.0` 이상(CodeBuild와 같은 22 major version 권장)
- Node.js 22에 포함된 npm
- 의존성 설치를 위한 인터넷 연결 및 npm 레지스트리 접근 권한
- 개발 서버에 접속할 최신 웹 브라우저
- 저장소를 내려받고 `frontend/` 디렉터리를 읽고 실행할 수 있는 권한

별도의 백엔드 서버, 데이터베이스 또는 환경변수는 현재 로컬 프로토타입 실행에 필요하지 않습니다.

## 설치

Node.js와 npm을 준비한 뒤 `frontend/`에서 의존성을 설치합니다.

```bash
cd frontend
npm ci
```

의존성 버전은 `package-lock.json`으로 고정되어 있습니다. 잠금 파일을 갱신해야 하는 경우에만 다음 명령을 사용합니다.

```bash
npm install
```

## 로컬 실행

개발 서버를 실행합니다.

```bash
cd frontend
npm run dev
```

터미널에 표시된 로컬 주소를 브라우저에서 엽니다. Vite 개발 서버는 기본적으로 `5173` 포트를 사용하며, 설정상 컨테이너·원격 환경에서도 접근할 수 있도록 열려 있습니다.

주요 npm 명령은 다음과 같습니다.

```bash
npm run dev       # 개발 서버
npm run preview   # 빌드 결과 미리보기
npm run typecheck # TypeScript strict 검사
npm run test:ledger # 원장 변환 테스트
npm run test:env    # 환경변수 우선순위·검증 테스트
npm run build     # 프로덕션 빌드
npm run test:release # dist/client release 구조 검사
```

## 환경변수

- `frontend/.env.local`은 비민감 팀 공통 로컬 값으로 Git에서 관리합니다.
- 개인 재정의가 필요하면 Git에서 제외된 `frontend/.env`에 바꿀 키만 작성합니다.
- npm script는 Node의 env-file 기능으로 `.env.local` 다음 선택적 `.env`를 읽습니다. 최종 우선순위는 `process env > .env > .env.local`입니다.
- `.env.production`, `.env.development`, `.env.prod` 같은 profile 파일은 사용하지 않으며, 존재하면 Vite가 시작을 거부합니다.
- `VITE_` 변수는 브라우저 번들에 포함되므로 비밀값을 넣지 않습니다. 앱은 승인된 네 개의 `VITE_` 키만 검증해 번들에 넣습니다.
- `VITE_API_BASE_URL`은 CloudFront 동일 origin의 `/api` 또는 `/api/...` 상대 경로여야 합니다. 절대 URL과 외부 origin은 빌드 시 거부됩니다.
- `FRONTEND_BACKEND_ORIGIN`은 로컬 Vite proxy 전용입니다. `VITE_` prefix가 없어 브라우저 번들에 포함되지 않습니다.
- 기존 개인 `.env`에 `VITE_BACKEND_ORIGIN`이 있다면 `FRONTEND_BACKEND_ORIGIN`으로 이름을 바꿔야 합니다.

## 참고

- 진입점: `src/main.jsx`
- 애플리케이션 조합: `src/AppShell.jsx`
- 주요 기능: `src/features/`
- 프로토타입 데이터: `src/data/ledgerData.js`
- 프로토타입 가정값: `src/config/prototypeAssumptions.js`
- 스타일: `src/styles.css`, `src/shell.css`, `src/features/*.css`
- 빌드 설정: `vite.config.mjs`
- CodeBuild 검증 단계와 같은 정적·원장·환경 검사는 저장소 루트에서 `infra/delivery/scripts/verify_frontend.sh`로 실행합니다.
- release 산출물 생성 계약은 `infra/delivery/scripts/build_frontend_release.sh`로 별도 검증합니다.
- release artifact는 Vite가 생성한 `dist/client`이며 OpenAI Sites worker·server bundle은 만들지 않습니다.

프로토타입 가정값은 제품 정책이나 운영 제한으로 간주하지 않습니다. 운영 기능을 추가할 때는 API 계약, 개인정보 처리 기준, 인증·권한과 실제 저장 방식을 별도로 확인해야 합니다.
