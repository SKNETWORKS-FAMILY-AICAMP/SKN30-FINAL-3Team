# F2 공백 반복과 출력 길이 종료 재현

- 기준: 2026-09-10, `dev`의 `df5d5ba`, 별도 `fix/ai-f2-runpod-local` 워크트리.
- 대상: `consultation-v3`, RTX 4090 24GB 1대, F2 image
  `sha256:ca2cfefb47e97c4b664b388ff585ae4d512e7ae33d6718fe400dc2ebe486b769`, vLLM 0.11.0.
- 입력: `infra/deploy/scripts/smoke_f2_audio.mp3.b64`의 합성 음성. 실제 상담·DB 쓰기 없음.

## 재현과 원인

AWS API를 통하지 않고 로컬의 실제 `create_f2_runtime` 파이프라인에서 재현했다.
SDK 원본 예외는 `LengthFinishReasonError`, 종료 사유는 `length`였다.
입력 379토큰, 출력 1,024토큰이며, 한 실패 응답의 7,187자 중 6,891자가 후행 공백이었다.
응답은 JSON 닫는 괄호가 완성되지 않았고 전체 JSON 검증도 실패했다. `enable_thinking=False`는
이미 요청에 포함됐으며 `<think>` 태그는 없었다. 기존 예외 변환은 이 SDK 오류를
`ProviderResponseError`로 묶어 앱에서 F2 503으로 보이게 했다.

같은 한도의 성공 응답도 있었고 2,048토큰 단일 실험도 성공했다. 따라서 한도 증가는
근본 해결의 근거가 아니다. 로컬에서도 실패하므로 이 장애를 AWS 네트워크 문제로 단정하지 않는다.

## 수정과 검증 경계

SLLM의 서버 시작 인자에 다음 설정을 추가한다. STT 인자와 F2의 1,024토큰 한도는 유지한다.

```text
--structured-outputs-config {"backend":"xgrammar","disable_any_whitespace":true}
```

vLLM 0.11 V1의 xgrammar 구현은 공백 제한을 서버 설정에서 읽는다. 같은 값을 요청의
`structured_outputs`에만 넣은 실험은 실패했다. 또한 `backend`를 생략하면 CLI 검증에서
공백 제한은 xgrammar/guidance만 지원한다는 오류로 시작하지 못하므로 둘을 함께 지정한다.
JSON 문자열 안의 공백을 삭제하거나 잘린 응답을 성공으로 처리하는 변경은 아니다.

실환경 검증에는 게시된 기존 이미지의 supervisor 시작 인자만 임시로 추가한 테스트 Pod를
사용한다. 공유 Template·SSM endpoint·AWS 앱 설정은 바꾸지 않는다. 이 검증을 새 이미지 게시나
공유 dev 정상 기동 완료로 해석하지 않는다. 영구 적용에는 변경된 supervisor를 포함한 이미지
게시, catalog/pin 갱신과 공유 dev 기동 검증이 필요하다.

- 로컬 검사: RunPod 런타임 테스트 38개와 Ruff 통과.
- 수정 후 로컬: 준비 직후 1회 및 연속 5회 모두 성공. 같은 입력 379토큰·출력 85토큰,
  최초 4.43초, 연속 실행 3.37~3.56초. 모델 품질·동시 처리량 검증은 아니다.
- AWS 배포 이미지 비교: 정상 인증 조건에서 성공, 4.29초, 입력 379·출력 85토큰.
  기존 EC2 `i-015875db5f1cb3c3d`의 배포 이미지를 일회성 컨테이너로 실행했다.
  유지보수 API 환경에는 두 F2 키가 모두 없음을 값 없이 확인했다. 사용자의 명시적 승인 후
  같은 EC2에서 Secret을 읽어 일회성 컨테이너 환경변수로만 전달했다. 파일·출력에 키를 남기지
  않았고 `--rm`으로 컨테이너를 정리했다. 공유 API·Worker 기동이나 DB 변경은 하지 않았다.
- 판정: 같은 합성 요청이 로컬과 AWS에서 수정된 서버를 통해 모두 성공했다. 이번 F2 오류는
  vLLM 구조화 출력 설정으로 좁혀졌다. ALB·전체 앱 HTTP 흐름, general, 다른 입력의 품질은
  이번 비교의 검증 범위가 아니다.
- 검증용 Pod: 삭제 후 관리 Pod 0개, 실행 중인 `brokerage-dev` 컨테이너 0개 확인.
  EC2·RDS는 기존 유지보수 상태로 남아 비용이 발생한다. 기존 이미지에 시작 인자를 추가한 실험이며 신규 이미지
  digest를 게시하거나 공유 선택값에 반영하지 않았다.

공식 구현 근거: [vLLM 0.11 설정](https://docs.vllm.ai/en/v0.11.0/api/vllm/config/structured_outputs.html),
[xgrammar의 서버 설정 사용](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/v1/structured_output/backend_xgrammar.py).
