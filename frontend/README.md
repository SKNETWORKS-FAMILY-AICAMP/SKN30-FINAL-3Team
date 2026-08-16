# Frontend

## 요구사항

로컬에서 `frontend/`를 설치하고 실행하려면 다음 환경이 필요합니다.

- Node.js `v24.19.0` (프로젝트 기준 고정 버전)
- npm `11.17.0` 권장
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
npm run build     # 프로덕션 빌드
npm run test:sites # Sites worker 테스트
npm run test:workflow # 워크플로 스모크 테스트
```

## 참고

- 진입점: `src/main.jsx`
- 애플리케이션 조합: `src/AppShell.jsx`
- 주요 기능: `src/features/`
- 프로토타입 데이터: `src/data/ledgerData.js`
- 프로토타입 가정값: `src/config/prototypeAssumptions.js`
- 스타일: `src/styles.css`, `src/shell.css`, `src/features/*.css`
- 빌드 설정: `vite.config.mjs`
- `npm run build`는 Vite 빌드 후 `scripts/prepare-sites-build.mjs`를 실행하도록 정의되어 있습니다. 현재 해당 후처리 스크립트가 저장소에 없으므로 Vite 번들 생성은 완료되지만 전체 명령은 후처리 단계에서 실패합니다.
- `npm run test:workflow`도 `scripts/workflow-smoke.mjs`가 필요하므로 실행 전 파일 존재 여부를 확인하세요.

프로토타입 가정값은 제품 정책이나 운영 제한으로 간주하지 않습니다. 운영 기능을 추가할 때는 API 계약, 개인정보 처리 기준, 인증·권한과 실제 저장 방식을 별도로 확인해야 합니다.
