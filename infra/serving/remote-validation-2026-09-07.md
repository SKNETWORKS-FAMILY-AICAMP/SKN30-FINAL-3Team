# 원격 LLM 검증 — 2026-09-07

상태: 원격 사전 점검·F2 Pod 기동 시도 완료, 실제 추론 미통과.
사용자 지시에 따라 PC는 AWS CLI·just·runpodctl 제어에만 사용한다.
로컬 이미지·모델 다운로드 또는 로컬 GPU 추론은 수행하지 않는다.

## 게시와 운영 도구

- 게시 revision: `b1354f5960b0e9885bf8d25d1e921f089876f1e6`.
- F2 workflow `34085785307`, general workflow `34086874322` 모두 success.
- F2 digest: `sha256:03c275889e7372a0367e5ceff961d219414235751807c25a2dc28732523d1567`.
- general digest: `sha256:ec4531f35b46a300e2bcc223e9591b98c6c1aba8d1ef80fee453286d844129af`.
- RunPod REST 기본 Python User-Agent는 Cloudflare 403, 같은 키의
  `runpodctl`과 `skn30-infra/1.0` User-Agent는 정상 응답이었다.
  두 기존 관리 클라이언트에 식별 User-Agent를 추가했다. 관련 회귀 테스트 44개·Ruff 통과.
- F2의 기존 Console Template은 image/name만 갱신하고 등록 plan 검증 후
  SSM schema v2 등록을 완료했다. 최초 자원을 API로 새로 만들지 않았다.

## F2 원격 기동 시도

- 기존 S3 release: `dev-f2-handwritten-v05-qwen3-4b-full-v1`.
- 모델: `Qwen/Qwen3-4B`, revision `1cfa9a7208912126459214e8b04321603b3df60c`, LoRA dev release.
- Secure Cloud RTX 4090 24GB 한 대, 조회·Pod 단가 $0.74/h.
- 검증 Pod는 생성 직후 RunPod에 의해 EXITED로 바뀌었다. 두 endpoint가 준비되기 전이라
  SLLM JSON 생성·Whisper 요청은 통과하지 못했다.
- 시도·정리 경과 25초. 해당 테스트 Pod 삭제와 목록에서의 부재를 확인했다.
- 공유 endpoint·serving selection은 변경하지 않았다. 다른 학습·개인 Pod는 변경하지 않았다.
- 후속 재시험에서 v2 로그를 삭제 전에 수집했다. 아래 결과에 따라 이미지 pull 인증 실패를 확정했다.

## 남은 선행 조건

- 기존 AWS `/runpod/ghcr-registry` 값으로 두 저장소에 pull 인증 토큰을 요청하면 403 denied.
  이 값은 기존 RunPod 운영의 인증 정본이 아니므로 RunPod 인증 실패나 새 토큰 발급 필요를
  뜻하지 않는다. RunPod 기존 registry는 보존하고 AWS 실제 배포 시 별도로 인증을 준비한다.
  값은 채팅·명령 인자·검증 기록에 넣지 않는다.
- 기존 AWS registry Secret은 `username/password`, 새 호스트 코드는 `username/token`을
  사용한다. AWS GPU 생성 전 호환 또는 정규화가 필요하다.
- 사용자가 최초 설정 대행을 요청하여 공식 API로 general Secret을 생성하고 AWS의 기존
  provider Secret에 추가했다. 값은 출력·파일·명령 인자에 남기지 않았다.
  전용 Template `xmi5zb7066`을 게시 digest로 생성하고 plan 검증·SSM schema v2 등록을 완료했다.
  기존 Console 우선 운영은 유지하며 이번 1회 대행을 관리 프레임워크로 추가하지 않았다.
- AWS GPU는 아직 생성하지 않았다. 이미지 인증을 확인한 뒤 검토한 GPU saved plan을 사용한다.
- Backend·AI 전체 연결, 두 capability 구조화 출력, AWS↔RunPod 전환은 아직 미검증이다.

검증 완료 기준은 [validation.md](validation.md)를 따른다. 인프라 조회 성공이나
이미지 게시 성공을 모델 로딩·추론 성공으로 간주하지 않는다.

## 기존 인증 경로 재확인

RunPod 운영 정본은 Console registry이며, 과거 AWS GHCR Secret은 호환용으로 남아 있었다.
그 AWS 값의 403만으로 RunPod 자격증명 실패 또는 토큰 재발급 필요를 판단한 것은 잘못이다.
사용자의 지적에 따라 재발급 요청을 철회했다. 기존 RunPod registry ID를 유지한 재시험에서
Pod의 registry 연결·image digest·필수 환경변수 전달 일치를 확인했지만 다시 즉시 EXITED였다.
인증 교체 없이 원격 종료 로그로 원인을 확인해야 한다. GPU 추론 성공으로 표시하지 않는다.

## 종료 로그로 확인한 원인

- 세 번째 원격 시도에서 RunPod v2 로그를 조회했다. 시스템 로그의
  `error pulling image`와 `denied: denied`가 확인됐다. 컨테이너가 만들어지기 전의
  GHCR pull 인증 실패이며 CUDA·모델·VRAM 문제로 진단하지 않는다.
- 기존 Console registry 연결, 최종 image digest, 필수 환경변수 전달은 Pod 응답에서 일치했다.
- Docker 로그인 저장소의 기존 GHCR 인증도 두 이미지에 대한 token 발급이 403 denied였다.
  같은 기존 토큰으로 GitHub `/user` 조회는 401이었다. 해당 토큰은 현재 유효하지 않으며,
  만료·폐기 중 무엇인지는 이 응답만으로 확정하지 않는다.
- GitHub CLI 로그인은 별도로 유효하지만 scopes는 gist/read:org/repo/workflow이며
  read:packages는 없었다. 이미지 게시 workflow 성공은 기존 pull 토큰의 유효성을 보장하지 않는다.
- 세 번째 시험·로그 수집·정리는 33초였다. 시험 Pod 삭제를 확인했고 공유 endpoint·selection은
  바뀌지 않았다. 기존 학습·개인 Pod는 변경하지 않았다.
- 다음 단계는 유효한 패키지 읽기 자격증명의 안전한 입력·연결이다. 이후 F2·general 원격
  추론 및 AWS 기동을 재개한다. 실제 모델 요청·메모리 검증은 아직 통과하지 못했다.

로그 조회 경로 근거: [RunPod 공식 CLI 설명](https://github.com/runpod/runpodctl/blob/main/AGENTS.md).
원문 로그 대신 비밀값과 URL을 가린 결과만 확인했다.

## GHCR 입력 갱신 재검증

사용자가 알려준 Secret version `764d6bd3-1018-4b0f-af6c-3041b4fa152c`가 AWSCURRENT임을 확인했다.
하지만 그 값으로 GitHub `/user` 요청은 urllib·GitHub CLI·캐시 회피 요청 모두 401이었다.
두 GHCR 저장소 pull token 요청도 403 denied였다. 저장 완료 이벤트는 실제 인증 통과를 뜻하지 않는다.
이 단계에서는 RunPod registry 교체나 새 GPU 생성을 수행하지 않았다.


## 새 GHCR 인증과 런타임 실검증

- Secret version `da6ff41d-a400-4e46-854f-f0c7bb2ee45d`로 두 이미지의 pull token과
  linux/amd64 manifest 조회가 200이었다. Secret 값은 출력·파일·명령 인자에 남기지 않았다.
- 새 RunPod registry `cmtqv6zpz0030taihxioy9eix`를 생성하고 F2·general Template과
  SSM 등록값의 연결을 갱신했다. 기존 registry는 다른 사용처를 고려해 삭제하지 않았다.
- 두 게시 이미지 모두 RunPod에서 실제 pull 및 컨테이너 시작까지 성공했다.
  모델 추론은 아래 런타임 오류로 아직 통과하지 못했다.

| 시험 | 확인된 실패 | 조치·후속 검증 |
|---|---|---|
| 게시 F2 / RTX 4090 24GB | vLLM 0.11.0이 `--default-chat-template-kwargs`를 거부 | 고정 tokenizer의 chat template에 비사고 설정을 적용하고 지원되는 `--chat-template` 사용 |
| 게시 general / L40S 48GB | `exec python failed: No such file or directory` | 이미지 CMD·Template·AWS 모델 다운로드를 `python3`으로 통일 |
| F2 옵션 수정 후보 | 기본 이미지가 켠 HF transfer의 패키지가 설치되어 있지 않음 | `HF_HUB_ENABLE_HF_TRANSFER=0`; 선택적 패키지를 추가하지 않음 |
| general python3 후보 | vLLM 0.26.0이 `--disable-log-requests`를 거부 | 지원되는 `--no-enable-log-requests` 사용 |

네 시험 Pod의 실행·정리 경과는 각각 약 192·377·190·169초였다.
현재 조회 단가는 F2 $0.74/h, general $1.09/h였다. 시간 기반 계산 약 $0.24이며
스토리지·실제 청구 반올림을 포함한 확정 청구액은 아니다.
RunPod가 컨테이너 종료 뒤에도 desiredStatus를 RUNNING으로 유지하며 재시작하는 것을 확인했다.
따라서 fatal 로그 확인 후 운영자가 조기 삭제했고, 시험 harness의 중복 삭제 실패 기록과
별도로 목록에서 실제 삭제를 재확인했다. 공유 endpoint·selection과 다른 사용자의 Pod는 보존했다.

수정본에는 두 이미지의 실제 설치 vLLM CLI parser로 시작 인자를 확인하는 Docker build 검증을
추가했다. F2 관련 21개 단위 테스트와 변경 Python Ruff는 통과했다. 이미지 빌드와 수정본의
GPU 추론 성공은 아직 확인하지 않았다. 로컬에 모델·이미지를 다운로드하거나 실행하지 않았다.

후속 후보 실행은 자동 승인 검토에서 차단됐다. 전체 런타임 소스 전송과, 이후 축소한 옵션
패치 전송 모두 원격 코드 전송·실행의 목적지·payload에 대한 명시적 승인이 필요하다는 이유였다.
차단 뒤 해당 실행을 우회하지 않았다. 재시험 대상은 이 프로젝트의 임시 RunPod RTX 4090/L40S이며,
변경 내용은 위 네 항목이다. 승인 후 후보 추론을 검증하고, 이미지 재게시·새 digest 등록 후
게시 이미지 자체를 다시 검증해야 한다. AWS GPU는 계속 미생성이다.

CLI 근거: [vLLM 0.11.0](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/entrypoints/openai/cli_args.py),
[vLLM 0.26.0](https://github.com/vllm-project/vllm/blob/v0.26.0/vllm/entrypoints/openai/cli_args.py).


## 승인 후 후보 검증

사용자가 수정 코드의 원격 전송·실행을 명시적으로 승인하여 재시험했다.

- **F2 수정 후보 통과**: RTX 4090 24GB에서 기존 Qwen3-4B LoRA release와 Whisper를
  순차 기동했다. Qwen 모델 로딩 로그는 7.6168GiB였고, 생성부터 두 엔진 ready까지 약 214초였다.
  외부 HTTPS에서 SLLM JSON 생성과 1초 무음 WAV 전사 응답 계약을 모두 확인했다.
  이 요청 묶음은 약 8초였으며 음성 인식 정확도 평가를 대신하지 않는다.
  `/ops/status`의 남은 디스크는 22,322,003,968 bytes였다. 총 VRAM 최고점은 미측정이다.
- 기존 urllib 기본 User-Agent는 같은 주소·키의 모델 조회에서 403, 명시한
  `skn30-infra/1.0`은 200이었다. 통합 probe와 기존 runpod 모델 조회에 이를 반영했다.
  먼저 시작된 제어 프로세스는 구형 probe를 사용해 별도 검증 클라이언트로 합성 추론을 마친 후
  삭제를 요청했다. 제어 프로세스의 중단 결과를 추론 실패로 해석하지 않는다.
- **general BnB 후보 실패**: L40S 48GB에서 시작 옵션은 통과했으나
  `qwen3_5.py`에서 `linear.py:816`의 `param_data.shape == loaded_weight.shape`
  assertion으로 가중치 로딩이 실패했다. 현재 vLLM 0.26.0과 해당 고정 BnB checkpoint 조합의
  호환성 미통과이며, BnB 일반 또는 모든 vLLM 버전의 불가능을 뜻하지 않는다.
- 위 F2·general 시험 Pod 삭제, 공유 endpoint offline·selection 보존을 확인했다.
  실행·정리 경과는 F2 440초, general 668초였다. 다른 사용자의 Pod는 변경하지 않았다.
- 변경 검증: F2 runtime 21개, general 기존 startup/HTTP 6개, serving 25개,
  기존 RunPod 관리 29개 테스트 통과. 모델·이미지는 로컬 PC에서 실행하지 않았다.

사용자는 후속 후보로 **Unsloth FP8 검증**을 선택했다. 대상은
`unsloth/Qwen3.8-27B-FP8`, revision `d51e38f6f2b5877bb91e06ba231e41ffc63bde6f`,
가중치 metadata 합계 28.75GiB다. 같은 L40S 48GB에서 8K·동시 요청 1건으로 시험한다.
공유 dev 모델 정본과 endpoint는 아직 변경하지 않았다. 후보 검증 성공 후 이미지 재게시와
게시 이미지 재검증이 필요하다.


## Unsloth FP8 후보 결과 — 통과

- 고정 모델 `unsloth/Qwen3.8-27B-FP8` /
  `d51e38f6f2b5877bb91e06ba231e41ffc63bde6f`, vLLM 0.26.0,
  L40S 48GB, FP8/auto load, 8K, 동시 처리 1건, eager·비사고 모드로 검증했다.
- 원격 가중치 로딩 성공. 로그상 모델 로딩 메모리 27.64GiB, 생성부터 API ready 약 331초.
  이 값은 모델 로딩 메모리이며 전체 VRAM 최고점은 아니다.
- 외부 인증 HTTPS로 JSON `{ok:true}` 생성, 한국어 문장 생성,
  AI 공개 워크플로의 포지션 카드 생성(매물·수요 각 1건)과 중개 판정 1건을 통과했다.
  실제 DB·개인정보는 사용하지 않았다. AI 클라이언트에 명시적 설정을 주입해 개인 `.env`를 읽지 않았다.
- 한국어 문장 및 F3 두 capability의 합성 요청 묶음은 총 134초였다. 개별 요청 지연이나
  동시 사용자 성능을 측정한 값은 아니다. 검증 클라이언트 timeout은 180초였다.
  dev의 기존 timeout과 실제 화면 대기 경험은 앱 통합 시 추가 확인해야 한다.
- 첫 추론에서 Triton JIT warmup이 확인됐다. 요청 중 샘플 로그의 생성 처리율은 약 11tokens/s였다.
  이를 일반 서비스 성능이나 부하 시험 통과로 간주하지 않는다.
- `/ops/status` 남은 디스크: 54,777,868,288 bytes.
  전체 시험·정리 489초, Pod 삭제와 공유 endpoint·selection 보존 확인.
- 결과는 게시 이미지에 승인된 후보 runtime을 임시 적용한 시험이다. 게시 digest의 원래 runtime이
  이 결과를 자동으로 갖는 것은 아니다. 저장소의 공유 general 모델 정본·DB는 아직 BnB 설정을
  보존한다. FP8 모델 설정을 코드·계약에 일관되게 반영하고 수정 이미지 재게시·새 digest 등록 후
  게시 이미지 자체를 다시 검증해야 한다.

F2 수정 후보와 general FP8 후보의 **RunPod 직접 추론 검증은 통과**했다.
AWS GPU 배포, 앱 Backend 경유 요청, 혼합 배치, AWS↔RunPod 왕복, stop/deep-stop 복원은 미완료다.
