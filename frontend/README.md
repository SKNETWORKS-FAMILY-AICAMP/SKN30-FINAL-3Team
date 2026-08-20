# Frontend

## 요구사항

로컬에서 `frontend/`를 설치하고 실행하려면 다음 환경이 필요합니다.

- Node.js `22.x` (CodeBuild와 같은 major version)
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
npm run build     # 프로덕션 빌드
npm run test:release # dist/client release 구조 검사
```

## 참고

- 진입점: `src/main.jsx`
- 애플리케이션 조합: `src/AppShell.jsx`
- 주요 기능: `src/features/`
- 프로토타입 데이터: `src/data/ledgerData.js`
- 프로토타입 가정값: `src/config/prototypeAssumptions.js`
- 스타일: `src/styles.css`, `src/shell.css`, `src/features/*.css`
- 빌드 설정: `vite.config.mjs`
- CodeBuild 검증 단계와 같은 정적·원장 검사는 저장소 루트에서 `infra/delivery/scripts/verify_frontend.sh`로 실행합니다.
- release 산출물 생성 계약은 `infra/delivery/scripts/build_frontend_release.sh`로 별도 검증합니다.
- release artifact는 Vite가 생성한 `dist/client`이며 OpenAI Sites worker·server bundle은 만들지 않습니다.

프로토타입 가정값은 제품 정책이나 운영 제한으로 간주하지 않습니다. 운영 기능을 추가할 때는 API 계약, 개인정보 처리 기준, 인증·권한과 실제 저장 방식을 별도로 확인해야 합니다.
