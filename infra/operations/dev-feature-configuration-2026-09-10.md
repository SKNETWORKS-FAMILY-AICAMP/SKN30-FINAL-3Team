# dev 기능 설정 재적용 기록 — 2026-09-10

## 대상과 확인된 원인

대상 앱 소스는 최신 dev `a550ae9`다. 해당 소스의 통합 파이프라인은
2026-09-10 14:10 KST에 성공했다. 코드 배포 성공과 기능 설정 활성화는 별개다.

재적용 전 AWS SSM 및 실제 API 컨테이너에 `CHATBOT_ENABLED`가 없었으며,
[Backend 기본값](../../backend/src/core/config.py)은 `false`였다.
[환경변수 렌더러](../deploy/scripts/render_env.py)는 챗봇 비활성 상태에서 API의
`AI_GENERAL_BASE_URL`과 `AI_GENERAL_API_KEY`를 제외한다. 실제 API에서도 두 입력이
미주입된 것을 확인했다. 개발 로그인 사무소는 2이며, 인증된 기능 상태 조회는
`enabled=false`, 현재 대화는 없음이었다. 비밀값과 접속 URL은 기록하지 않는다.

[dev Terraform 설정](../environments/dev/configuration.tf)에 `CHATBOT_ENABLED=true`를
추가하고 설정 재생성·API 및 Worker 재기동을 완료했다. 선택된 기존 GPU는 유지했다.
설정 적용과 실제 기능 검증의 근거는 아래 검증 상태에서 구분한다.

## 함께 확인한 최신 변경의 배포 조건

| 항목 | 코드 감사 결과와 적용 조건 |
|---|---|
| API general 연결 | 렌더러가 활성화 flag에 따라 기존 general endpoint와 Secret 키를 API에 주입한다. 별도 주입 코드 추가는 필요 없다. |
| 챗봇 DB 모델 | [workflow 조립](../../backend/src/chatbot_runtime.py)은 사무소별 활성 `CHATBOT` capability를 요구한다. 기존 F3 설정과 독립이며, 사무소 2의 `2:CHATBOT`을 공식 모델 대상 선택·비교 절차로 확인한다. |
| 모델 호환성 검사 | [기동 검사](../scripts/serving_model_targets.py)는 현재 모델이 없는 대상을 불일치로 판정하지 않는다. 따라서 dev-start 성공만으로 챗봇 DB 설정 완료를 보장하지 않는다. |
| 챗봇 스키마·DB 권한 | migration019가 챗봇 3개 테이블을 생성한다. 배포 후크의 전체 migration과 기존 app_owner 기본 권한을 사용한다. 별도 IAM 추가 근거는 없다. 실제 스키마·runtime 접근은 별도로 검증한다. |
| 최신 F3 #130 | 새 환경변수·migration·IAM 추가 없이 Worker 코드의 30초 lease heartbeat를 사용한다. 최신 앱 이미지와 Worker 재기동이 적용 조건이다. |
| 최신 화면 #125 | 챗봇 전용 VITE flag 없이 Backend 기능 상태를 따른다. 배포의 `VITE_LEDGER_SOURCE=api`를 F3/calendar가 상속하므로 별도 변수 추가는 필요 없다. |
| SSE 전달 | CloudFront의 API 캐시 비활성·viewer 전달, API의 즉시 snapshot·15초 heartbeat·no-store가 구현됐다. ALB idle timeout 60초를 늘려야 한다는 코드상 근거는 없다. 실제 CloudFront 경유 SSE 완료로 확인한다. |
| 선택적 조정값 | 챗봇 요청 제한 기본 60초, heartbeat 기본 15초, 동시 요청 기본 1은 현재 계약과 일치한다. 기본값으로 충족되는 항목은 설정 누락으로 분류하지 않는다. |

근거 정본: [챗봇 Backend](../../.agents/skills/backend/references/chatbot.md),
[HTTP·SSE 계약](../../docs/architecture/chatbot/api-and-stream.md),
[환경변수 관리](../../docs/development/environment-variables.md).
이번 감사 범위에서는 활성화 flag 외 추가 필수 환경변수 누락을 발견하지 못했다.

## 설정 적용과 실행 소스 검증

- Terraform 변경은 챗봇 flag parameter 생성과 앱 IAM의 해당 parameter 참조 갱신이었다.
  적용 후 동일 구성의 drift plan은 변경 0건이다.
- 환경변수 렌더러 관련 테스트 19개와 Terraform validate가 통과했다.
- 앱 drain 후 공식 dev-start가 exit 0으로 완료됐다. 사무소 2의 `2:CHATBOT`은 기존
  모델 없음에서 `vllm`, `Qwen/Qwen3.8-27B-FP8`, alias `general-dev-gpu`, 고정 모델 revision
  `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`로 적용했다. 기존 F3 및 사무소 1 설정은 유지했다.
- API·Worker는 healthy, API의 `CHATBOT_ENABLED=true`와 general URL·키 존재를 확인했다.
  비밀값은 출력하지 않았다. ALB target도 healthy다.
- 실행 중인 앱 컨테이너는 최신 dev `a550ae9`의 ECR 이미지 digest
  `sha256:3ad4eddf50ac4d3581f24df89876d945d4169158b4fc7ae12cc25542007a637e`와 일치한다.
  APPLIED는 complete이며 앱 revision은 `d-COUMBJ6QK`, 산출물 hash는
  `76c46e8b5249f2009e38c607f4cd138baf7b77f56f439457d28ab00ad7ae418f`다.

## CloudFront 경유 실제 챗봇 검증

인증된 개발 로그인으로 챗봇 기능 활성화 응답 `enabled=true`를 확인한 뒤 합성 질문을
실행했다. SSE의 snapshot·completed를 수신했고, 완료 결과는 후속 GET 및 최종 상태
재구독 결과와 일치했다. DB 진단에서 모델 호출 1회와 선택 모델의 정합성을 확인했다.

첫 검증 실행의 snapshot 수신은 229ms, 완료는 49,184ms였다. 이 값은 단일 실행의
관측값이며 반복 성능 기준이나 지연 원인 분석 결과가 아니다. 검증 전 기존 대화가 없었음을
확인했으며, 검증에서 만든 대화는 삭제하고 해당 로그인 세션도 폐기했다.

## 전체 서비스 검증

공식 `dev-verify`가 exit 0으로 완료됐다.

| 대상 | 확인 시각 (UTC) | 추론 관측 | VRAM 관측 | 결과 |
|---|---|---|---|---|
| F2 | 2026-09-10 05:30:33 | SLLM 2.218초, STT 2.019초 | 21,561 / 24,564 MiB, 각각 5 samples | identity·추론·앱 smoke 통과 |
| general | 2026-09-10 05:32:36 | 3.084초 | 39,099 / 46,068 MiB, 6 samples | 식별값 일치·추론·앱 smoke 통과 |

기존 GPU를 유지한 검증이다. 원격 hardware 식별에서 사용할 수 없는 필드의 범위와
보완 확인 근거는 [서빙 이미지 적용 기록](../serving/image-rollout-validation-2026-09-10.md)을
따른다. 추론 성공을 새로운 품질 평가 통과로 간주하지 않는다.

다른 검증이 없는 상태에서 챗봇을 단독으로 한 차례 더 실행했다. snapshot은 222ms,
완료는 10,100ms였으며 snapshot·completed 수신, 후속 GET·최종 상태 재구독 일치,
모델 호출 1회와 같은 Qwen3.8 FP8 provider route를 확인했다. 기존 대화가 없는 상태에서
검증했고, 생성한 대화 삭제와 검증 로그인 세션 폐기를 완료했다.

두 실행의 완료 관측값은 49.184초와 10.100초다. 첫 실행의 긴 지연은 단독 추가 측정에서
재현되지 않았지만 원인은 확정하지 않았다. 두 관측값을 반복 성능 기준이나 지연 원인의
증거로 확대 해석하지 않는다.
