# site — 소개용 정적 페이지

ZIPKEKE(Propeller AI) 제품 소개용 정적 랜딩 페이지와 그 생성 자료를 둔다.
제품 애플리케이션이 아니다. 실제 서비스 UI는 [frontend/](../frontend/)에 있다.

> **범위 주의** — 이 폴더는 [AGENTS.md](../AGENTS.md)가 정의한 루트 모듈(`frontend/` `backend/` `ai/` `data/` `infra/`)에 속하지 않는 대외 홍보용 자료다. 제품 코드나 빌드 파이프라인에 연결되어 있지 않으며, 여기의 문구는 승인된 요구사항이 아니다.

## 구성

| 경로 | 내용 |
|---|---|
| [index.html](index.html) | 현재 랜딩 페이지. Tailwind CDN 기반 단일 HTML. 빌드 없이 브라우저에서 바로 연다 |
| [prompts/how-it-works.md](prompts/how-it-works.md) | 상단 내비게이션 `How it works` 페이지를 UI 생성 AI로 만들기 위한 프롬프트 |

## How it works 페이지 만드는 순서

1. [prompts/how-it-works.md](prompts/how-it-works.md)의 `## 프롬프트 본문` 이후 전체를 복사한다.
2. UI 생성 AI(v0, Stitch, Figma Make, Claude Artifacts 등)에 붙여넣어 단일 HTML을 받는다.
3. 결과를 `site/how-it-works.html`로 저장한다.
4. [index.html](index.html)의 내비게이션에서 `How it works` 링크 `href`를 `#`에서 `how-it-works.html`로 바꾼다.
   같은 링크의 클래스를 활성 상태(`text-secondary` + `font-bold` + `border-b-2 border-secondary`)로 옮기는 작업은 새 페이지 쪽에서 한다.
5. 아래 점검 항목을 확인하고 커밋한다.

## 문구 점검 기준

이 폴더의 대외 문구는 실제 동작과 어긋나면 안 된다. 다음을 확인한다.

- 승인되지 않은 기능을 제공 기능으로 쓰지 않는다. 판단 근거는 [요구사항 인덱스](../docs/requirements/index.md)와 [현재 MVP 범위](../docs/requirements/common/mvp-scope-and-evaluation.md)다.
- 정확도·속도·만족도 같은 성능 수치를 쓰지 않는다. 승인된 평가 지표가 아직 없다.
- 판정 실행 시점을 정확히 쓴다. 저장은 포지션 카드까지만 만들고, 후보 조회와 판정은 `[교차 판정]` 버튼이 시작한다 ([F3 교차 판정](../docs/requirements/f3/cross-judgment.md) F3-CR-01~04).
- 정기 배치나 자동 발송이 있는 것처럼 쓰지 않는다. F3는 사용자 행동에만 반응한다 (F3-CM-01).
- 실제 개인 이름·연락처·주소를 예시로 넣지 않는다.

## 알려진 정리 대상

현재 [index.html](index.html)에 남아 있는 항목이며, 아직 손대지 않았다.

- `이동 중에도 접근` 카드의 "모바일과 데스크톱 실시간 동기화" 문구는 요구사항 문서에 근거가 없다.
- `등록 매물 128건` `등록 고객 84명`은 예시값인데 실적처럼 읽힌다.
- 로고와 삽화 4개가 `lh3.googleusercontent.com` 외부 URL을 참조한다. 생성형 도구가 발급한 임시 URL이라 만료될 수 있으므로, 유지할 페이지라면 이미지를 저장소로 옮기는 편이 안전하다.
