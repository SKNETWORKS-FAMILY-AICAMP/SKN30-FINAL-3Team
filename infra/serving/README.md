# F2·범용 모델 이미지 게시

이 변경은 GPU 배포에 앞서 실행 이미지를 준비한다. 전원·연결 전환 도구와 Terraform은 별도 변경이다.
기존 F2 모델 release·Whisper revision을 유지한다. 모델 재학습·release 재게시가 아니다.

## 이미지와 실행 계약

- F2: 기존 `infra/runpod/Dockerfile`과 vLLM 버전을 유지한다. SLLM 준비 후 Whisper를 시작하며
  각 엔진의 동시 sequence를 1로 제한한다. 기존 RunPod 원격 모델 경로가 기본이다.
- AWS F2 준비: 호스트가 검증한 release를 `/opt/f2-models/<release>`에 제공하고
  `F2_LOCAL_MODELS=1`일 때 `/models/sllm`·`/models/stt`를 읽기 전용으로 마운트한다.
  캐시는 bundle SHA256과 manifest 영수증을 확인하며 검증된 캐시에는 다운로드 URL이 필요 없다.
  캐시 영수증이 없는 기존 디렉터리는 명시적으로 재생성한다. 기존 평가·승격 검증도 유지한다.
- general: `general.Dockerfile`의 별도 고정 vLLM 기반 이미지로 Qwen BnB를 실행한다.
  모델·revision은 `general_runtime.py`에 고정한다. 8K, 동시 1건, 텍스트 전용으로 시작한다.
  RunPod는 고정 revision을 다운로드하고 AWS는 `/models/general`을 제공한다.
- 서비스 키는 환경변수로만 주입한다. 일반 모델은 인증된 models·chat·디스크 상태 경로만 공개한다.
  실제 개인정보를 smoke 입력에 사용하지 않는다.

## 게시와 배포의 경계

1. `dev` 대상 PR을 검토·병합한다. 새 수동 workflow가 GitHub에서 인식되려면 저장소의
   기본 브랜치에도 workflow가 있어야 하므로 기존 릴리스 PR 절차로 반영 여부를 확인한다.
2. 수동 `Publish RunPod F2 Serving Image`와 `Publish General Serving Image`에서 검토한
   Git ref를 지정한다. Push나 PR 생성 자체는 이미지 게시를 실행하지 않는다.
3. 성공한 workflow의 최종 이미지 digest와 resolved Template artifact를 보존한다.
   기반 vLLM digest와 프로젝트 최종 이미지 digest를 혼동하지 않는다.
4. GPU 호환성·합성 추론 검증 후 별도 배포 절차에서 최종 digest를 등록한다.
   기존 F2 이미지 digest는 복구용으로 보존한다. 게시만으로 활성 endpoint·DB 모델을 바꾸지 않는다.

`image-provenance.json`의 GPU 호환성은 아직 미검증이다. CI의 Python 테스트와 이미지 빌드는
GPU 모델 로딩·한국어 생성·구조화 출력·VRAM 검증을 대체하지 않는다.
이 PR은 GPU를 생성하지 않는다. 수동 게시 시 GitHub Actions 실행 및 GHCR 저장 비용이 발생할 수 있다.
운영 소유자는 지정 Infra 운영자이며 GPU 비용 승인은 실제 배포 단계에서 수행한다.

## 로컬 검증

workflow와 같은 `ruff==0.14.10`, `aiohttp==3.14.3`, `multidict==6.7.1` 환경에서 실행한다.

```bash
ruff check infra/runpod/scripts infra/runpod/tests infra/serving
python -m unittest discover -s infra/runpod/tests -v
python -m unittest discover -s infra/serving/tests -v
```
