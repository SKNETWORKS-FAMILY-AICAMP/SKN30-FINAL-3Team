---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 구현·로컬 검증

[요구사항](../../requirements/chatbot/overview-and-scope.md) · [HTTP·SSE](api-and-stream.md) · [저장](persistence.md) · [화면](../../screen/chatbot.md)

## 구현 경계

- AI 공개 계약·워크플로는 `ai/src/brokerage_ai/chatbot/`, HTTP·조회·저장·작업 관리는 `backend/src/domain/chatbot/`과 `backend/src/api/chatbot.py`가 소유한다.
- UI는 `frontend/src/features/chatbot/`이며 공통 앱 셸에서 기존 F2·장부·캘린더 상세를 연결했다. Backend가 활성화된 경우에만 버튼을 제공하며 기능의 기본 비활성 상태를 유지한다.
- 챗봇 결과의 숫자·조건·총계는 Backend가 계산한다. 조회 자료·개인정보·원시 결과 행은 모델 프롬프트에 보내지 않는다.
- `CHATBOT` 전용 모델 설정만 읽는다. F2 모델과 F3의 `POSITION_CARD`·`BROKERAGE_JUDGMENT` 설정을 변경하지 않는다.
- PostgreSQL 15의 전진 migration `019_CREATE_CHATBOT`으로 세 테이블을 추가한다. 기존 migration과 업무 데이터를 초기화하지 않는다.
- Backend의 단일 API 프로세스 안에서 최대 1개 작업을 실행한다. 브라우저 연결과 분리한다. 명시적 취소·전체 삭제는 즉시 DB에 반영하되 진행 중인 Provider·DB 작업은 응답 또는 제한 시간까지 정리하고 수용 슬롯을 반환한다.
- 챗봇의 수용 제한이 F3와 공유 GPU 전체를 조정하는 것은 아니다. Provider 혼잡·실패와 60초 deadline을 처리하며 자동 Provider 전환은 없다.

## 활성화와 모델 선택

기본 `CHATBOT_ENABLED=false`다. prod 활성화는 합성 시연 범위를 벗어나므로 거절한다.
공유 dev 배포·migration은 이번 구현의 실행 범위에서 제외한다. GPU 기동은 초기 구현에서 보류했으나,
후속 승인된 [Qwen 3모델 비교](../../../infra/serving/model-comparison-2026-09-08.md)에서 평가 전용 Pod로 수행한다.

1. 기존 절차로 격리된 로컬 PostgreSQL에 migration을 적용한다.
2. Backend 로컬 환경에 기존 개발 계정을 설정하고 Provider 비밀값을 주입한다. 개인 AI 키가 `ai/.env`에만 있으면 Backend 명령 실행 시 해당 파일도 명시적으로 주입한다. 키를 다른 tracked 파일에 복사하지 않는다.
3. 해당 로컬 사무소에 챗봇 모델을 선택한다. 먼저 `--apply` 없이 설정·대기 작업을 확인한 뒤 적용한다.

```bash
uv run --locked --project backend --env-file ai/.env python backend/src/chatbot_model.py \
  --brokerage-id BROKERAGE_ID --model-profile local-openai --apply
```

4. 로컬 Backend 실행 환경에서 `CHATBOT_ENABLED=true`로 설정한다. 화면은 인증 후 활성 여부를 조회한다.

관리 명령은 loopback 로컬 DB만 허용하고 `CHATBOT` capability만 변경한다. 업무 데이터 reset과 F3 모델 설정 전환을 수행하지 않는다.
Qwen용 `dev-qwen38-vllm-bnb` 프로필은 고정 revision과 `general-dev-gpu` alias를 사용한다.

## 평가 합의

초기 구현에서는 사용자 요청으로 RunPod 기동과 Qwen 평가를 보류하고 Luna를 평가했다.
이후 사용자가 Infra 프로필 도입과 **14B AWQ·32B AWQ·27B BnB 비교 평가**를 승인했다.
후속 Qwen 결과와 한계는 [비교 기록](../../../infra/serving/model-comparison-2026-09-08.md)이 정본이며,
아래 Luna 표는 초기 구현 당시의 검증 기록이다.

| 검증 | 기준 |
|---|---|
| Luna 모델 평가 | 기본 30·단위/동의어 10·멀티턴 10·모호/미지원 10 시나리오를 3회 반복 |
| 정확도 | 지원 질문 도구·조건 및 멀티턴 각각 90% 이상. 반복별 결과도 기록 |
| 안전성 | 별도 20건의 권한·주입 공격과 실제 DB/API 소유권·변조 ID·쓰기 차단 검사 |
| 저장·복구 | 중복 실행·전체 삭제 후 재생성 0건, 연결 종료 후 완료 저장·서버 중단·수동 재시도 |
| warm 성능 | 동시 추론 1건에서 HTTP 접수부터 첫 진행 p95 ≤ 1초, 일반 조회 완료 p95 ≤ 30초 |
| 화면 | 새로고침·재접속·중복/역순 이벤트·계정 전환·F2 명시적 이동·키보드·좁은 화면 |

AI 평가 실행기는 `ai/eval/chatbot/evaluate.py`, 결정적 검사는 Backend·Frontend 테스트에 둔다.
AI 워크플로의 첫 콜백 시간은 HTTP·SSE 전달 시간과 다르므로 각각 측정한다. 실제 모델 호출 실패·누락을 성공으로 대체하지 않는다.
모델 원문·프롬프트·비밀값 대신 케이스 ID, 도구·조건, 안전한 진단 정보와 집계 결과를 기록한다.
팀원 사용성 평가는 이번 완료 조건에 포함하지 않는다.

## 2026-09-08 로컬 검증 결과

| 검사 | 결과·근거 |
|---|---|
| Luna 기본·단위 40건 × 3회 | **112/120, 93.33%**. 반복별 90% / 92.5% / 97.5% |
| Luna 멀티턴 10건 × 3회 | **30/30, 100%** |
| 모호·미지원 10건 × 3회 | **29/30, 96.67%**. 1건은 명확화 대신 미지원 안내를 반환했으며 조회 실행 없음 |
| 별도 공격 20건 × 3회 | **60/60 차단**. 워크플로 사전 차단이며 모델 자체의 주입 저항성 측정은 아님 |
| 실제 모델 실행 | 240개 시나리오, 모델 호출 177회, 호출 오류 0건. 모델 해석 p95 **2.884초** |
| 실제 HTTP·SSE·Luna·PostgreSQL | 12개 조회 × 3회 **36/36 통과**. 첫 진행 p95 **0.223초**, 완료 p95 **3.273초**, 매회 DB 복원과 최종 전체 삭제 통과 |
| AI 회귀 | 최종 전체 **319개 통과**, Ruff·Pyright 통과. PyAV 18.1.0은 dev 의존성으로 고정하며 운영 의존성에는 추가하지 않음 |
| Backend 회귀 | 최종 전체 **664개 통과**. 실제 PostgreSQL 소유권·경합·삭제·참조/기간/금액·장애 회귀를 포함 |
| 추가 Backend 검사 | 모델 선택 CLI **7개**, Provider·최종 DB 저장 장애 **8개**, 설정·캘린더 상세 **6개** 통과. 전체 Backend Ruff·Pyright 통과 |
| Qwen | 초기 구현에서 보류. 후속 승인된 [3모델 비교 결과](../../../infra/serving/model-comparison-2026-09-08.md)를 별도 기록 |

[Luna 평가 근거](../../../ai/eval/chatbot/validation/luna-20260908.json)에는 fixture·workflow·prompt hash, 반복별 결과와 불일치를 기록했다. 평가 후 보안 수정으로 이전 차단 질문의 비밀값을 후속 문맥에서 제외했으며 실제 모델을 호출한 59종 입력의 전후 hash가 동일함을 확인했다. **조건 해석 점수는 실제 DB 조회 지원율과 다르다.** 구입장 면적은 저장 기준 부재로 Backend가 안내하며 무리하게 검색하지 않는다.

[HTTP 성능 근거](../../../backend/eval/validation/chatbot-http-luna-20260908.json)는 별도 임시 DB·실제 쿠키 인증·HTTP 접수·SSE 수신을 사용했다. 매물 25건, 구입장 5건, 캘린더 25건의 합성 fixture로 정확한 총계를 검사하고 warmup 1회는 p95에서 제외했다. warmup 완료는 3.135초였으며 **인프라 cold start 측정이 아니다**. 동시 모델 추론은 1건이다. 로컬 결과를 공유 dev 경로 성능으로 해석하지 않는다.

재현 시 격리 PostgreSQL과 `TEST_DB_URL`을 준비한다. 평가기는 loopback 서버에 임시 DB를 생성·삭제하므로 해당 테스트 계정의 CREATE DATABASE 권한이 필요하다. 아래 `TEST_ENV_FILE`은 비밀값을 출력하지 않는 ignored 환경 파일의 경로다.

```bash
uv run --locked --project ai --env-file ai/.env python ai/eval/chatbot/evaluate.py --help
uv run --locked --project backend --env-file ai/.env --env-file TEST_ENV_FILE \
  python backend/eval/chatbot_http.py --rounds 3 --output /tmp/chatbot-http.json
uv run --locked --project backend --env-file TEST_ENV_FILE pytest backend/tests
uv run --locked --project ai ruff check --fix ai
uv run --locked --project ai ruff format ai
uv run --locked --project backend ruff check --fix backend
uv run --locked --project backend ruff format backend
uv run --locked --project backend pyright --project backend
```

AI 실제 실행 옵션과 Qwen의 고정 artifact 인자는 [평가 README](../../../ai/eval/chatbot/README.md)를 따른다. Backend 검증은 기존 사용자 DB를 초기화하지 않는 격리 DB에서만 실행한다.

## 화면·통합 및 독립 검토

- Frontend 순수 테스트 **12개**, 실제 HTTP/SSE fixture를 사용하는 챗봇 Playwright **8개**, 기존 F3 브라우저 **5개**가 통과했다. 계정 전환·전체 삭제·역순/중복 이벤트·구독 실패·재접속·참조 만료·키보드/IME·초점 복귀를 포함한다.
- 기존 인증·장부·F2·F3·Time Keeper·캘린더·환경·오류 경계 회귀를 통과했다. `npm run typecheck`와 임시 outDir의 production build도 통과했다. 기존 대형 bundle 경고는 유지된다.
- 별도 실제 앱 확인에서는 Vite→FastAPI→Luna→임시 PostgreSQL로 로그인, 가격 조건 조회(정확한 15건), 새로고침 복원, 기존 상세 이동, 전체 삭제, F2 기존 접수 화면 진입을 확인했다. F2 화면 진입에 따른 분석 POST는 **0회**였다.
- 저장 결과의 순번은 당시 첫 페이지 기준이다. 페이지를 다시 조회한 답변은 첫 페이지로 돌아와도 후속 순번 선택을 제한하고 개별 상세 버튼을 제공한다. 다른 탭에서 문맥이 만료되면 선택을 해제한다.
- 작성자와 다른 담당자가 교차 검토했다. Frontend 담당은 데이터·실행, Backend 담당은 AI·조회, AI 담당은 UI·통합을 검토했다. 취소 후 슬롯 조기 반환, 모델 변경 경합, 참조 SQL timeout, 이전 차단 질문의 비밀값 전달, 재조회/만료된 순번 선택을 수정하고 재확인했다. 미해결 blocking finding은 없으며 사람의 PR 검토는 별도다.

```bash
cd frontend
npm run test:chatbot
npm run test:chatbot:browser
npm run test:ledger && npm run test:auth && npm run test:f2 && npm run test:f3
npm run test:time-keeper && npm run test:calendar && npm run test:root-error && npm run test:env
npm run test:browser
npm run typecheck
npm run build -- --outDir /tmp/chatbot-validation-build
```

## 전체 delivery 검증과 자동 검토 확인

[Delivery 결과](../../../backend/eval/validation/chatbot-delivery-20260908.json): 개인 `.env`와 기존 build 산출물을 포함하지 않은 임시 복사본에서 `infra/delivery/scripts/verify_local_delivery.sh`가 종료 코드 0으로 통과했다. Python 3.13.12·Node 22.23.2·uv 0.11.2·PostgreSQL 15.18/pgvector 0.8.6을 사용했다. 사용자 기본 런타임은 변경하지 않았다.

- Backend 664개, 배포 스크립트 56개, Frontend component 136개·release 2개 및 production build, Backend image·비특권 UID·Compose config를 확인했다. 해당 AI 단계는 311개이며 이후 요약 검증기 8개를 추가한 최종 전체 319개도 별도로 통과했다.
- lockfile 변경에 따른 추가 `docker build --no-cache --file backend/Dockerfile`도 통과했고 UID 10001 실행을 확인했다. 공개 GHCR 이미지의 기존 자격 설정 오류는 빈 임시 Docker 설정의 익명 pull로 해소했다. 이미지 게시·배포는 하지 않았다.
- 자동 리뷰의 매물 조인 누락 지적은 기존 `latest_listing_alias()` 내부 사무소·세대 상관과 `LIMIT 1 LATERAL`, 실제 PostgreSQL 총계·페이지 회귀로 오탐임을 확인했다. CI DB 누락 지적도 `verify_backend_ai.sh`의 필수 `TEST_DB_URL` 검사와 전체 pytest 실행이 이미 적용됨을 확인했다.
- 비밀값 경고는 외부 client를 만들지 않는 합성 FakeProvider 회귀 입력이며 실제 키는 변경 파일에 포함되지 않았다. 원문과 다른 평가 요약 형식은 종류·스키마·수동 집계 방식을 명시하고 `verify_summary.py`로 원본 240행의 해시·집계·오답을 검증한다. 경고를 사람 승인으로 간주하지 않는다.

## 후속 검증

- Qwen 3모델 비교는 완료했다. 공식 FP8은 지원 질문 94%·멀티턴 100%·HTTP 36/36을 기록했지만 모호·미지원 80%로 평가기 전체 기준은 미달했다. 모호한 질문 처리 개선 후 재평가가 남아 있다. 근거와 비교 범위는 [Qwen 비교 기록](../../../infra/serving/model-comparison-2026-09-08.md)을 따른다.
- 공유 dev 배포 시 CloudFront→ALB→API의 SSE buffering·idle timeout과 F3 경합을 실제 경로에서 검증한다.
- 현재 공개 dev의 공용 합성 계정은 같은 작성자다. 실제 사람별 인증·개인정보 이용 승인을 대신하지 않는다.
