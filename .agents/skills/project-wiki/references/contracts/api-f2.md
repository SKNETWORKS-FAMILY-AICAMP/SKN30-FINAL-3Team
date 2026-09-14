---
status: 결정
updated: 2026-09-08
---

# F2 음성 분석 HTTP 계약

인증·공통 오류 및 F2 오류 코드는 [API 공통 계약](api-common.md)을 함께 읽는다.

## F2 음성 분석 계약 (구현됨 · 1차 연동)

| Method | Path | 인증 | 동작 |
|---|---|---|---|
| POST | /api/v1/f2/analyses | 세션·CSRF | 음성을 RunPod `stt`로 전사하고 `sllm`으로 분석해 검토용 제안을 동기 반환 |

요청은 `multipart/form-data`이며 `audio`, 선택적인 `current_ledger_type`·`current_fields`,
`privacy_confirmed`를 받는다. `audio`는 비어 있지 않은 WAV·MP3·M4A이고 현재 상한은 25 MiB다.
신규 음성 접수는 현재 장부가 없으므로 `current_ledger_type`과 `current_fields`를 생략한다. 기존 장부
상세에서 분석할 때만 `current_ledger_type`에 `매물장` 또는 `구입장`을 보내고, `current_fields`에는
필드명에서 문자열 또는 null로 가는 JSON 객체를 보낸다. 이전 Frontend의 `ledger_type` 입력은
전환 기간 하위 호환으로 받되 신규 호출에서는 사용하지 않는다. `privacy_confirmed`가 true가 아니면
422로 거절한다. Backend는 세션에서 사용자 문맥을 검증하지만 사용자·사무소 식별자는 모델에 보내지
않는다.

응답의 상담 유형은 `매도의뢰`, `매수문의`, `기타상담` 중 하나다. `ledger_type`은 상담 유형에서
결정된 추천 대상 장부로, 매도의뢰는 `매물장`, 매수문의는 `구입장`, 기타상담은 null이다. 모델은
STT 텍스트를 한 번 분석해 상담 유형과 그 유형에 맞는 필드를 함께 추출하며 현재 장부값으로 분류를
유도하지 않는다. `기타상담`은 공동중개·단순문의와 불명확하거나 혼합된 상담을 합친 값이며 장부
필드 제안을 반환하지 않는다. 기존 상세에서 `current_ledger_type`과 추천 `ledger_type`이 다르면
`ledger_mismatch`를 true로 반환하고 필드 제안을 억제한다. 그 밖에 필드별 현재값·제안값·상태·근거·기본 선택 여부, 불확실성,
상담 로그 초안과 서버가 확인한 주의 문구 확인 시각을 반환한다. 전사 전문, 모델 진단, 요청자와
Provider 오류 원문은 반환하지 않는다. 제안 응답만으로 장부를 저장하지 않으며 Frontend가 선택한 값을
부모 상세의 미저장 draft에 반영한다.

이 경로는 RunPod base model 연결을 검증하는 1차 동기 수직 슬라이스다. 영속 작업, Worker 재개,
SSE 단계 알림, 전사 재사용 재시도와 승인 감사 저장은 아직 구현하지 않았으며
`docs/architecture/f2/online-runtime.md`의 제안 구조를 대체하지 않는다. Backend와 RunPod 양쪽의 임시
음성은 해당 처리가 실제 종료될 때 삭제하고 애플리케이션 로그에는 음성·전사·제안 원문을 기록하지 않는다.
클라이언트 취소만으로 이미 실행 중인 STT thread가 종료되지는 않으므로 Backend 임시 파일은
pipeline 종료까지 유지한 뒤 삭제한다. 취소된 결과를 별도 저장하거나 재조회하는 기능은 없다.

동시 제한·취소 정리는 사용자가 구현을 승인한 [ADR-0031](../decisions/ADR-0031-runpod-junior-operations.md)의 PR 계약 변경이다. 팀 병합 승인은 별도로 필요하며 정식 dev 앱 배포 완료를 뜻하지 않는다.

약 10명 시연 기준으로 API 인스턴스 1개·Uvicorn worker 1개에서 F2 분석은 동시에 1건만 허용한다.
추가 요청은 큐에 쌓지 않고 429 `F2_BUSY`, `Retry-After: 5`와 공통 오류 봉투를 반환한다.
혼잡 검사는 multipart 본문 파싱·인증 의존성 실행 전에 수행하므로 혼잡 중에는 인증 오류보다
429가 먼저 올 수 있다. 슬롯을 얻은 요청에는 기존 세션·CSRF·입력 검증을 모두 적용한다.
Frontend는 선택 파일을 유지하고 잠시 후 수동 재시도를 안내한다. 5초 뒤 성공이나 공정한 순서를
보장하지 않으며 자동 재시도는 하지 않는다. API 프로세스/인스턴스 증설 전에는 이 제한을 재설계한다.

F2 route는 별도 사용자 기능 플래그 없이 항상 공개한다. Infra endpoint set이 `active`일 때만
Backend가 `AI_VLLM_SLLM_BASE_URL`과 `AI_VLLM_STT_BASE_URL`로 pipeline을 초기화한다. `offline`이면
Backend는 정상 기동하고 분석 요청만 503 `F2_UNAVAILABLE`로 종료한다. `active`인데 URL이 없으면
부분 활성화를 허용하지 않고 애플리케이션 시작을 설정 오류로 실패시킨다.
