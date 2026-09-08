---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 구현·로컬 검증

[요구사항](../../requirements/chatbot/overview-and-scope.md) · [HTTP·SSE](api-and-stream.md) · [저장](persistence.md) · [화면](../../screen/chatbot.md)

## 구현 경계

- AI 공개 계약·워크플로는 `ai/src/brokerage_ai/chatbot/`, HTTP·조회·저장·작업 관리는 `backend/src/domain/chatbot/`과 `backend/src/api/chatbot.py`가 소유한다.
- UI 통합은 의존 PR의 `frontend/src/features/chatbot/`에서 수행한다. 이 API PR의 기본 비활성 상태를 유지하고 기존 F2·장부·캘린더 상세 연결은 화면 PR에서 검토한다.
- 챗봇 결과의 숫자·조건·총계는 Backend가 계산한다. 조회 자료·개인정보·원시 결과 행은 모델 프롬프트에 보내지 않는다.
- `CHATBOT` 전용 모델 설정만 읽는다. F2 모델과 F3의 `POSITION_CARD`·`BROKERAGE_JUDGMENT` 설정을 변경하지 않는다.
- PostgreSQL 15의 전진 migration `019_CREATE_CHATBOT`으로 세 테이블을 추가한다. 기존 migration과 업무 데이터를 초기화하지 않는다.
- Backend의 단일 API 프로세스 안에서 최대 1개 작업을 실행한다. 브라우저 연결과 분리한다. 명시적 취소·전체 삭제는 즉시 DB에 반영하되 진행 중인 Provider·DB 작업은 응답 또는 제한 시간까지 정리하고 수용 슬롯을 반환한다.
- 챗봇의 수용 제한이 F3와 공유 GPU 전체를 조정하는 것은 아니다. Provider 혼잡·실패와 60초 deadline을 처리하며 자동 Provider 전환은 없다.

## 활성화와 모델 선택

기본 `CHATBOT_ENABLED=false`다. prod 활성화는 합성 시연 범위를 벗어나므로 거절한다.
공유 dev 배포·migration·GPU 기동은 이번 구현의 실행 범위에서 제외한다.

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

2026-09-08 구현 요청 후 사용자는 **RunPod 기동과 Qwen 실제 평가를 보류하고 OpenAI로 구현·평가 진행**을 선택했다. 따라서 이번 필수 실제 모델은 Luna이며 Qwen의 실제 품질·성능은 미검증으로 남긴다.

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
| AI 회귀 | 전체 **306개 통과**(PyAV 임시환경). 후속 평가기·보안 수정 대상과 모듈 경계 **37개 통과**, Ruff·Pyright 통과 |
| Backend 회귀 | 전체 **646개 통과**. 이후 경합·조회 수정은 실제 PostgreSQL **15개**, 정규화 **19개**, migration 정적 검사 **6개**로 재검증 |
| 추가 Backend 검사 | 모델 선택 CLI **7개**, Provider·최종 DB 저장 장애 **8개**, 설정·캘린더 상세 **6개** 통과. 전체 Backend Ruff·Pyright 통과 |
| Qwen | **NOT_RUN** — 사용자 요청으로 RunPod 기동·실제 품질·성능 평가 보류 |

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

## 후속 검증

- Qwen endpoint를 운영자가 준비한 뒤 동일 fixture·반복 횟수로 평가한다. 모델 revision·artifact hash·runtime을 함께 기록한다.
- 공유 dev 배포 시 CloudFront→ALB→API의 SSE buffering·idle timeout과 F3 경합을 실제 경로에서 검증한다.
- 현재 공개 dev의 공용 합성 계정은 같은 작성자다. 실제 사람별 인증·개인정보 이용 승인을 대신하지 않는다.
