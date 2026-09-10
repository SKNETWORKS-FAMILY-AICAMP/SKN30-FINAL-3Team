---
status: 결정
updated: 2026-09-03
---

# ADR-0023: SLLM 미평가 dev release 경로

- 상태: 승인됨·코드 구현, S3 dev release 게시 완료·RunPod/Terraform 미적용
- 결정일: 2026-09-03
- 부분 대체: [ADR-0022](ADR-0022-sllm-release-v2-base-only.md)의 모든 신규 release에 대한 평가·승인 필수 조건
- 유지: release v2의 불변 base commit·adapter checksum 결속, private S3 정본, health·rollback·삭제 계약

## 맥락

공유 개발 환경에서 학습 직후 adapter의 기동·연결을 확인하려면 정식 `full` 평가와 승격 승인 전에
배포할 수 있는 명시적 경로가 필요하다. 이를 일반 release와 같은 명령으로 허용하면 미평가 모델이
검증 완료 모델로 오인될 수 있으므로 이름, manifest, 실행 명령에서 구분해야 한다.

## 결정

- `release.json:v2`에 `release_stage=verified|dev`를 둔다. 기존 v2에서 필드가 없으면
  `verified`로 해석해 읽기 호환한다.
- `dev` release ID는 `dev-`로 시작해야 한다. `evaluation`은
  `{status: not-evaluated, dataset_release: ...}`만 기록하고 평가 요약·승인 파일은 bundle에 넣지 않는다.
- `dev`는 평가·승인만 생략한다. LoRA의 학습 metadata, 기반 모델 ID·40자리 commit, adapter config와
  실제 adapter tree checksum 결속 및 base mode의 공개 불변 모델 제한은 유지한다.
- 일반 `runpod-create-plan`과 `runpod-create`는 `dev` release를 거부한다. 운영자는
  `runpod-create-dev-plan`과 확인이 필요한 `runpod-create-dev`를 사용해야 한다.
- 명시적 dev create는 기존 공유 dev endpoint를 active로 전환할 수 있다. 따라서 정식 품질 검증이나
  승격 근거가 아니며, 사용 후 정확한 Pod ID로 삭제하고 offline smoke를 확인한다.
- S3 경로와 불변 게시·cross-hash, 모델명 health, Backend refresh, 실패 시 endpoint 복원과 Pod 삭제는
  verified release와 동일하다. 미평가 상태를 숨기는 별도 우회 bundle이나 수동 Template 변경은 허용하지 않는다.

## 결과

개발자는 평가가 준비되지 않아도 adapter의 패키징·기동·F2 통합을 검증할 수 있다. 대신 결과 품질을
입증하지 않으므로 `dev` bundle은 검증 완료 release나 운영 승격에 사용할 수 없고, 공유 endpoint를
사용하는 동안 팀에 미평가 모델임을 명확히 알려야 한다.
