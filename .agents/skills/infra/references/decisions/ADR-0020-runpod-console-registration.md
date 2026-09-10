---
status: 구현됨
updated: 2026-09-08
---

# ADR-0020: Console 자원 검증·등록과 API 전용 F2 refresh

> 2026-09-09 부분 대체: 기존 Template의 검토된 API 수정·재검증·SSM 등록은 [ADR-0024](ADR-0024-shared-serving-selection-lifecycle.md)가 소유한다. 최초 Console 자원 준비·Secret/registry 경계는 유지한다.

> 2026-09-07 부분 대체: GPU 배치·local/dev 연결·전원 범위는 [ADR-0022](ADR-0022-dual-cloud-gpu-lifecycle.md)를 따른다. 아래 내용은 기존 결정의 기록이다.

> 후속 [ADR-0021](ADR-0021-runpod-operational-reduction.md)이 자체 감시와 Secret metadata 조회를 제거하고 실패 시 offline 복구를 적용한다.

- 상태: 사용자 Console 방식 선택·코드 구현·등록/원격 후보 검증 확인·팀 병합 검토 대기
- 승인 경계: 사용자 작업 승인과 작성자 외 팀원의 PR 병합 승인은 별개다. 이 문서는 팀 승인 완료를 주장하지 않는다.
- 부분 대체: [ADR-0018](ADR-0018-runpod-bootstrap-secrets-monitoring.md)의 bootstrap·비밀 회전,
  [ADR-0017](ADR-0017-runpod-ephemeral-sllm-serving.md)의 API·Worker 동시 재생성
- 상위 결정: [프로젝트 ADR-0031](../../../project-wiki/references/decisions/ADR-0031-runpod-junior-operations.md)

## 구현

- `runpod-register-plan <image@digest> <template-id> <registry-id>`는 읽기 전용 검증이며
  `runpod-register`는 같은 검증 후 SSM control을 단일 기록으로 교체한다. Terraform 컨테이너가
  존재해야 하고 endpoint offline·공유 Pod 부재가 선행 조건이다. 실패 시 기존 기록은 보존한다.
- control v2는 `schema_version`, `status`, `registry_auth_id`, `template_id`, `image`, `updated_at`
  만 가진다. 기존 v1 기록은 offline 등록 시 전환하며 동일 v2 값은 재기록하지 않는다.
- Template 이름·digest·포트·환경·registry 연결·공개 여부·Volume을 검증한다. 등록 도구에는
  RunPod 자원 생성·삭제 메서드가 없으며 `doctor`와 create 전에도 Template drift를 확인한다.
- F2 key는 Console에 만든 값과 같은 값을 `secret-rotate f2`로 AWS에 입력한다. GHCR PAT는
  Console에서만 교체한다. OpenAI·Discord·RunPod API key 회전 경로는 유지한다.
- `render_env.py --f2-only`는 SSM endpoint와 필요한 F2 key만 읽고 API 환경파일의 F2 항목만
  원자적으로 바꾼다. DB Secret·migration IAM token 생성에 의존하지 않는다.
- `refresh_ai_endpoints.sh` 기본은 API만 재생성한다. `--all`은 일반 Provider key 회전용 전체
  refresh다. 일반 회전 도구는 SSM command 완료를 기다린 뒤 성공을 보고한다.

## 검증·운영 경계

약 10명 부트캠프 시연 범위에서는 Pod 1개·GPU 1개와 API 점검 중단을 허용한다. supervisor는
SLLM의 인증 모델 조회가 성공한 뒤 STT를 시작하며 두 모델 기동 대기에 총 25분을 둔다
(artifact download 시간 별도, 운영 create의 전체 제한은 그대로 적용). 각 vLLM은
`--max-num-seqs 1`로 기동한다. 초기화 실패·timeout·프로세스 종료 시 전체를 종료하고
기존 create 복구 또는 운영자의 delete/recreate를 사용한다. GPU 메모리 비율은 검증된 보장이
아닌 초기값이다. 시연 합격·기록 기준은 runbook에서 관리한다.

단위·shell 회귀 검증으로 등록 실패 무변경, 재실행, Template drift, 비밀값 비출력, F2 API만 재생성,
Worker·migration·다른 API 값 보존, 게시 승인 검증과 runtime 무결성을 확인한다.
이 검증은 실제 GHCR pull, Console Secret 값 일치, GPU 기동·메모리·동시 요청 성공을 대체하지 않는다.
실환경 순서는 [RunPod runbook](../../../../../infra/runpod/README.md)을 따른다.
