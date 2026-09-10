# Qwen 평가·이미지 JSON 기록

이 변경은 PR #107의 JSON 10개를 먼저 분리한 기록이다. 모델 전환·배포·평가 실행 코드와
전체 재현 설명은 후속 #107에서 반영한다. JSON만으로 모델을 활성화하거나 배포하지 않는다.

- AI/HTTP validation JSON은 당시 실행의 점수·hash·반복별 결과를 보존한다.
- `model-profiles.json`은 repository·revision·양자화·가중치 hash를 고정한다.
- `published-images.json`은 게시 이미지별 평가·기동·CPU 검사·실패 범위를 구분한다.
- `model-comparison-evidence-2026-09-08.json`은 평가와 이미지·Pod 기록을 연결한다.
- `image-provenance.json`의 vLLM 0.28은 후속 비교 이미지의 기반 기록이다. 현재 dev의
  Dockerfile을 바꾸거나 배포 완료를 뜻하지 않는다. 기존 0.26 실행 설명과 혼동하지 않는다.

평가 결과는 현재 workflow v3·scorer v2 이전의 역사적 기록이다. 최신 코드의 품질 합격
근거로 재사용하지 않으며, 실패한 모델을 자동 승격하지 않는다. 원본 점수·가중치 hash는
분리 전 PR #107 커밋 `07919c0`과 동일하다. 과거 기록은 현재 원격 자원 상태를 증명하지 않는다.
