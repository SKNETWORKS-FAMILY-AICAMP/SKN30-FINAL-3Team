---
status: 구현됨
updated: 2026-09-07
---

# ADR-0028: 주니어가 관리할 수 있는 RunPod 운영 범위

> 2026-09-07 부분 대체: GPU 배치·local/dev 연결·전원 범위는 [ADR-0030](ADR-0030-local-dev-dual-cloud-serving.md)를 따른다. 아래 내용은 기존 결정의 기록이다.

> 후속 [ADR-0029](ADR-0029-runpod-manual-observation.md)가 자체 감시 유지·Secret 목록 조회·이전 endpoint 복원 조항을 대체한다.

- 상태: 사용자 요청·선택 반영, 코드 구현·팀 검토 전·외부 미적용
- 부분 대체: [ADR-0021](ADR-0021-runpod-operations-and-secret-ownership.md)의 자동 bootstrap·GHCR 비밀값 정본,
  [ADR-0022](ADR-0022-sllm-release-v2-base-only.md)의 Template generation·runtime 검증 책임,
  [ADR-0020](ADR-0020-sllm-release-handoff.md)의 API·Worker 동시 endpoint refresh
- 유지: private S3 불변 release, v1 읽기·v2 base/LoRA, 명시적 dev/verified 구분, 인증·checksum·health,
  create/delete·F2 offline 503, 개인정보 제한과 읽기 전용 감시

## 맥락

단일 공유 dev의 GPU 한 대를 위해 RunPod Secret·registry·Template 생성, generation과 Secret version
동기화, AWS endpoint와 Backend 재시작 복구를 직접 관리했다. 사용자는 주니어 독립 운영을 기준으로
단순화를 요청했고 최초 자원을 Console에서 만든 뒤 도구가 검증·등록하는 방식을 선택했다.
이후 사용자는 약 10명이 사용하는 학원 부트캠프 팀 프로젝트와 취업 포트폴리오라는 기준을 명시했다.
이에 따라 높은 처리량·무중단보다 시연 재현성, 비용과 주니어의 복구 가능성을 우선한다.

## 결정

- 최초 RunPod Secret·GHCR registry·private Pod Template은 운영자가 Console에서 생성한다.
  등록 도구는 기존 자원을 읽어 검증하고 완성된 ID·digest 기록을 SSM에 한 번 쓴다.
  `provisioning`, 자동 generation과 Secret version 동기화 상태를 제거한다.
- GHCR credential은 RunPod Console만 소유한다. AWS에 복제하지 않는다. 기존 Terraform GHCR
  Secret 컨테이너는 파괴적 변경 없이 호환용으로 남기며 도구가 사용하거나 값을 요구하지 않는다.
  F2 runtime key와 RunPod 운영·감시 key는 기존 AWS Secrets Manager에 TTY로 입력한다.
- Template 수정·등록과 F2/GHCR 회전은 endpoint offline·공유 Pod 부재에서만 수행한다.
  Pod 생성 전 현재 Console Template을 등록된 digest·설정과 다시 대조한다. Secret 값 일치와
  private image pull은 최초 Pod 기동·인증 health에서 검증한다.
- 품질 평가·승인·학습 provenance는 패키징·게시 단계에서 검사한다. Pod runtime은 신뢰된 S3
  객체에서 받은 bundle checksum, 안전한 압축 해제, release ID·stage, 모델·commit과 adapter bytes를
  검증한다. 평가 문서의 의미를 다시 해석하지 않는다. cache 재사용 시 검증한 bundle과 manifest
  checksum 영수증을 대조한다. 게시 경로를 우회하는 임의 bundle은 지원하지 않는다.
- F2 실행 소비자는 Backend API다. F2 endpoint refresh는 기존 API 환경파일의 F2 값만 교체하고
  같은 image의 API만 재생성한다. Worker·migration 환경파일과 나머지 API 설정은 보존한다.
  전체 배포 시 Worker에서 F2 URL·key를 제외하고 F2 상태를 offline으로 둔다.
- 일반 Provider key 회전은 명시적 전체 refresh로 API·Worker를 재생성하고 완료까지 기다린다.
  F2 생성·삭제 실패 시 이전 endpoint 복원과 Pod 정리, 수동 reconcile은 계속 제공한다.
- Backend API는 인스턴스 1개·Uvicorn worker 1개로 운영하고 F2 분석은 전체 사용자 합계 1건만
  받는다. 처리 중 추가 분석은 429 `F2_BUSY`와 `Retry-After: 5`를 반환한다. 5초는 완료 시간이나
  순번 보장이 아니다. Frontend는 파일을 유지하고 수동 재시도를 안내한다. 대기열·Redis·분산 잠금은
  추가하지 않는다. 일반 API와 F3 실행의 동시성을 이 F2 제한에 묶지 않는다.
- 분석 요청이 취소되어도 이미 시작된 STT thread의 실제 완료 전에는 슬롯·임시 파일을 해제하지
  않는다. 정상 종료 시 진행 중 분석을 기다린 뒤 runtime을 닫는다. 강제 종료는 결과를 보장하지
  않으므로 점검 전에 사용자의 분석 완료를 확인한다.
- 단일 Pod·GPU의 공동 장애와 endpoint 변경 중 짧은 API 중단을 이 규모의 운영 조건으로 허용한다.
  두 모델을 함께 쓰는 F2 시연을 위해 GPU를 추가하거나 endpoint hot reload를 구현하지 않는다.
  SLLM의 인증 health 확인 후 STT를 기동하고 각 엔진의 `--max-num-seqs`를 1로 제한한다.
  메모리 비율은 기존 0.65/0.20을 시작값으로 유지하며 실측 없이 적합성을 보장하지 않는다.

## 결과와 제한

정상 운영은 release 게시·Pod 생성·상태 확인·삭제에 집중한다. 신규 GPU 종류나 학습 결과를 실제
검증 없이 고정 운영 조합으로 선언하지 않는다. 시연 운영에서는 검증한 image·release·STT revision·GPU
조합 하나를 기록해 재사용하고, 실험은 offline 상태에서 교체한다. 실제 GPU 기동·메모리·복구 검증은
아직 필요하다. API 재생성과 GPU 공동 장애를 제거했다고 표현하지 않는다.

처음 지적한 네 문제 중 자동 최초 설정과 runtime 중복 검증은 제거하고, API/Worker 결합은 API만으로
축소했다. 단일 GPU와 API 점검 중단은 과설계로 제거할 대상에서 허용 가능한 운영 제약으로 재분류했다.
기존 create/delete 복원·checksum·인증은 데이터 일관성과 비용을 보호하므로 유지한다.
포트폴리오에는 모의 동시성 검증과 실제 GPU 측정을 구분하고, 10명 실부하·가용성 검증 완료로 과장하지 않는다.

운영 상세·기존 v1 control 전환은 [RunPod runbook](../../../../../infra/runpod/README.md)을 따른다.
