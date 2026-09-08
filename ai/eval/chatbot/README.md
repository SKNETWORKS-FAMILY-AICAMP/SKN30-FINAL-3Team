# F4 챗봇 합성 평가

`cases.json`은 합성 질문 60개(기본 30, 단위 10, 멀티턴 10, 모호·미지원 10)와
공격 질문 20개다. 기준일은 2026-09-08이며 실제 고객·업무 데이터는 사용하지 않는다.

```bash
uv run --locked --project ai python ai/eval/chatbot/evaluate.py \
  --provider openai --model gpt-5.6-luna --rounds 3 \
  --output ai/eval/chatbot/results/luna.json
```

기존 AI 설정 로더가 `ai/.env.local`, 비추적 `ai/.env`, 환경변수를 읽는다. 키를 명령행에 넣지
않는다. OpenAI Luna가 지원하지 않는 `temperature`는 챗봇 요청에서 생략한다. 모델을 자동으로
다른 Provider로 전환하지 않는다.

평가는 실제 Provider를 사용하지만 조회 capability는 호출을 기록하는 fake다. 따라서 **의도·조건
추출과 워크플로의 차단 동작**을 검증한다. DB 권한·숫자·정확한 총계·실제 조회·브라우저 SSE
시간은 Backend 통합 평가에서 별도로 확인해야 한다. 특히 구입장 DB의 면적 기준은 전용/공급으로
구분되지 않으므로, 면적 표현을 추출한 평가 성공을 실제 구입장 면적 조회 지원으로 해석하지 않는다.

표시된 금액·면적 표현은 질문 원문을 복사한다. 평가는 누락뿐 아니라 불필요하게 추가한 조건도
오답으로 처리하며, refine에서는 이전 조건을 합친 결과를 비교한다. 공백, 기본 정렬, 진행 상태의
동의어만 정규화한다. 명확화 응답에는 이전 질문의 표현을 사용하되 직전 답변이 명확화일 때만
복원한다. DB 이력 전체를 문맥으로 제공하지 않는다.

첫 warm-up은 별도로 기록하고 각 모델은 동시 1건으로 반복한다. 결과에는 전체·반복별 정확도,
멀티턴 정확도, 공격 실패 수, 모델 해석 시간 p95, 첫 workflow callback 시간 p95, 모델·프롬프트·
평가셋 hash를 기록한다. callback 시간은 HTTP/SSE 전달 시간이 아니다. 20개 공격 사례는 현재
요청 차단기에서 모델 호출 전에 종료하므로, 모델 자체의 공격 저항성을 증명하지 않는다.

부분 실행은 `--rounds 1 --case-ids basic-01,multi-10`으로 진단한다. 부분 실행 결과를 전체 합격으로
사용하지 않는다. 각 사례 뒤 checkpoint를 저장하며 완료 상태가 `COMPLETED`인 보고서만 최종
평가로 사용한다. 생성 보고서는 `results/`에서 비추적 상태로 보관한다.

## Qwen 재개

2026-09-08 사용자 지시에 따라 Qwen은 `NOT_RUN`이다. RunPod/GPU는 이 평가기가 시작하지 않는다.
이미 준비된 endpoint를 평가할 때만 다음과 같이 명시한다.

```bash
uv run --locked --project ai python ai/eval/chatbot/evaluate.py \
  --environment local --provider llama_cpp --endpoint-alias general-dev-gpu \
  --model '<등록된 정확한 모델 ID>' --runtime-label '<고정 서버 이미지>' \
  --artifact-revision '<고정 revision>' --artifact-sha256 '<검증된 artifact hash>' \
  --rounds 3 --output ai/eval/chatbot/results/qwen.json
```

Provider·alias·artifact는 실제 배치에 맞춰 선택한다. self-hosted 평가에서는 provenance 세 필드를
모두 요구하며, Qwen 미실행을 OpenAI 결과나 fake 결과로 대체하지 않는다.

## 검증 기록

[Luna 2026-09-08 결과](validation/luna-20260908.json): 기본·단위 112/120(93.33%),
멀티턴 30/30, 모호·미지원 29/30, 공격 차단 60/60. 모델 해석 p95는 2.884초다.
반복별 점수와 오답 조건은 결과 파일에 보존한다. 지원 조건이 항상 정확하다는 뜻은 아니며
화면의 적용 조건을 확인할 수 있어야 한다. 검토 중 추가된 과거 차단 질문의 비밀값 제외 처리는
별도 회귀 테스트로 확인했고, 모델이 실제 받은 59종 입력의 hash는 수정 전후 동일했다.
