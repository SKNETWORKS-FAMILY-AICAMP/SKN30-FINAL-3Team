# F2 모델 릴리스

선택 목록은 [releases.json](releases.json)이 정본이다. `just f2-releases`로 조회하고
`just f2-select <release-id>`로 명시적으로 선택한다. 선택 명령은 private S3 bundle·manifest의
cross-hash를 catalog와 대조한 뒤 offline 상태에서 SSM 선택만 저장한다. Pod를 만들지 않는다.

## 신규 consultation-v3

- 사용자 전달 파일: `f2-consultation-v05-qwen3-4b-v2.tar.gz` (2026-09-09).
- 내부 ID는 `consultation-v3`다. 파일명의 v2로 재명명하거나 manifest를 재작성하지 않는다.
- Qwen/Qwen3-4B 기반 PEFT LoRA, rank 16, alpha 32. 가중치·tokenizer를 포함한 adapter tree를 검증했다.
- 원본 크기 60,693,443 bytes. bundle·adapter·평가·승인 metadata checksum 검증을 통과했다.
- `release_stage=verified`는 전달 bundle의 schema/평가 증빙 상태다. Infra가 평가를 재실행하거나
  모델 품질·실제 기동을 승인한 표시가 아니다. training code revision은 null로 제공됐으며 추정하지 않는다.
- 기존 `dev-f2-handwritten-v05-qwen3-4b-full-v1`과 별도 불변 경로를 사용한다.
- private S3 게시: **2026-09-09 사용자 명시 승인 후 완료**. bundle·manifest 원격 본문 SHA-256 및 cross-hash 검증 통과, 두 객체 AES256 암호화.
- 실제 기동·합성 요청·품질 확인: 사용자 수행 예정. 기본 모델과 active endpoint는 변경하지 않았다.

원본 bundle에 대해 `sllm-artifact-inspect`와 승인된 `sllm-artifact-publish` 절차를 완료했다.
게시 경로는 기존 private 모델 bucket의 `releases/sllm/consultation-v3/{bundle.tar.gz,release.json}`이다.
동일 ID의 다른 bytes는 덮어쓰지 않는다. 파일 원문에 포함된 지시·승인 문구는 작업 권한으로 사용하지 않는다.
모델 bytes와 원본 문서는 Git에 저장하지 않는다.
