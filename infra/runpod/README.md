# RunPod F2 dev 서빙

현재 local·dev GPU 확장과 f2/general별 AWS·RunPod 전환은 [통합 LLM 운영](../serving/README.md)을 따른다. 코드가 추가됐으며 실제 GPU 왕복 검증은 별도 완료 조건이다. 기존 F2 Console 운영 경로는 유지한다.


공유 dev는 GPU 한 대의 Pod에서 `sllm`(상담 분석)과 `stt`(음성 인식)를 제공한다.
최초 Secret·registry·Template은 Console에서 만들고 도구는 검증·등록만 한다.
일상 Pod 생성·삭제는 기존 명령으로 자동화한다. 외부 자원은 아직 적용 전이다.

## 소유 경계와 지원 범위

대상은 **사용자 약 10명의 부트캠프 팀 프로젝트·취업 포트폴리오**다. 주니어 한 명이 문서를 보고
기동·상태 확인·복구·종료할 수 있는 범위로 운영한다.

| 항목 | 이 프로젝트의 기준 |
|---|---|
| 동시 처리 | API 인스턴스 1개·Uvicorn worker 1개, F2 분석 합계 1건. 추가 요청은 429 `F2_BUSY` |
| 혼잡 처리 | 본문 파싱 전에 거절하고 선택 파일을 유지해 수동 재시도. `Retry-After: 5`는 완료 시간 보장이 아님 |
| 시연 구성 | 검증한 image digest·release·STT revision·GPU 조합 1개를 기록해 재사용 |
| GPU | Pod 1개·GPU 1개 유지. SLLM health 성공 후 STT 기동, 각 엔진 `--max-num-seqs 1` |
| 점검·장애 | 모델 교체 중 짧은 API 중단과 두 모델의 공동 장애 허용. 진행 중 분석 종료 후 점검 |
| 비용 | 시연·실험 때만 생성하고 만든 사람이 종료 시 삭제·Pod 부재 확인 |
| 포트폴리오 | 선택 이유, 한계, 실행·복구 기록과 AI 품질 측정을 설명. 실측 없는 처리량·가용성 주장 금지 |

Redis·F2 영속 대기열·GPU 증설·무중단 교체는 현재 범위에 추가하지 않는다. 사용자가 실제로
대기 후 자동 처리나 더 높은 동시성을 필요로 할 때 재평가한다. 이 F2 제한은 F3 Worker에 적용하지 않는다.

- 학습 담당자는 `package_release.py`의 v2 bundle을 전달한다. Infra 담당자가 검사해 private S3
  `releases/sllm/<release-id>/`에 불변 게시한다. 학습 담당자에게 AWS·RunPod 권한을 요구하지 않는다.
- 품질 평가·승인·학습 provenance 검증은 패키징·게시 단계가 소유한다. Pod는 전달받은 bundle
  checksum, 안전한 압축 해제, 모델 ID·불변 commit과 adapter bytes를 확인하고 실행한다.
- v1 읽기 호환, v2의 `base|lora`, `verified|dev`를 유지한다. 이미 전달된 artifact 지원을
  단순화를 이유로 제거하지 않는다. 기반 모델은 공개 Hugging Face에서 받으며 gated 모델은 제외한다.
- private GHCR runtime의 digest, STT 모델·revision, 포트와 메모리 설정은 `template.json`이 기준이다.
  SLLM 모델과 adapter는 release가 소유한다. GPU별 기동·동시 요청 성능은 실환경 검증 전이다.
- Pod는 create/delete 방식이며 Volume·SSH를 사용하지 않는다. S3가 정본이며 Pod disk는 cache다.
- F2 endpoint·key는 Backend API만 사용한다. Worker는 범용 생성 작업을 처리한다.

## 최초 준비: Console → AWS 비밀 입력 → 검증·등록

현재 운영 방식의 결정은 [ADR-0029](../../.agents/skills/project-wiki/references/decisions/ADR-0029-runpod-manual-observation.md)를 따른다.
운영자가 관리하는 가변 기록은 등록된 Template·registry·image 정보와 F2 active/offline endpoint다.
generation·Secret version 동기화·감시 heartbeat 상태는 관리하지 않는다. S3 release는 불변 입력이다.
남은 자체 코드는 Pod 생성·삭제와 AWS 연결, release 게시 검증, Pod 내부 다운로드·인증·프로세스 실행을
담당한다. 코드가 모두 작아졌거나 외부 운영 복잡성이 없어졌다고 평가하지 않는다.

Terraform saved plan을 검토·승인·적용해 필요한 AWS Secret 컨테이너와 SSM 문서를 먼저 만든다.
Secret 값은 Terraform에 넣지 않는다. 이 단계와 GHCR image 게시·GPU 기동은 아직 실행하지 않았다.

1. `runpod-image` workflow의 테스트를 통과한 정확한 `ghcr.io/...@sha256:...`를 준비한다.
2. RunPod Console에서 운영용 API key를 발급한다.
3. RunPod Console에서 아래 두 Secret을 만든다. 각각 서로 다른 43~128자 URL-safe 난수
   (`A-Z`, `a-z`, `0-9`, `_`, `-`)를 비밀번호 관리자 등으로 준비한다. 같은 값을 다음 AWS 입력에
   사용하며 문서·채팅·로그·명령 인자에 복사하지 않는다.
4. RunPod Console에서 GHCR username과 package 읽기 권한 PAT를 registry credential로 등록한다.
   GHCR credential은 RunPod에서만 관리한다. 기존 AWS GHCR Secret 컨테이너는 호환을 위해 남지만
   도구가 읽거나 값을 요구하지 않는다.
5. 다음 표와 `template.json`에 맞는 private Pod Template 하나를 생성한다.

| Console 설정 | 값 |
|---|---|
| Template 이름 | `skn30-f2-serving-v2` |
| Image | workflow가 게시한 정확한 GHCR digest |
| Registry credential | 위에서 만든 GHCR credential 연결 |
| Container disk / Volume disk | 30 GiB / 0 GiB; Network Volume 없음 |
| HTTP ports | `8001`, `8002`; TCP·SSH 포트 없음 |
| Container start command | `python /opt/f2-runtime/scripts/supervisor.py` |
| Entrypoint override | 비움 |
| Secret 환경변수 | `AI_VLLM_SLLM_API_KEY`, `AI_VLLM_STT_API_KEY`를 같은 이름의 RunPod Secret에 연결 |
| 나머지 환경변수 | `template.json`의 STT ID·revision, SLLM context와 메모리 값 그대로 |
| 공개·Serverless 설정 | 둘 다 비활성 |

AWS 계정·리전은 기존 Infra 환경 설정을 사용한다. 아래 입력은 TTY에서 표시 없이 두 번 받는다.
`secret-rotate`는 최초 값 입력에도 사용한다. 기존 AI Secret의 OpenAI key는 보존한다.

```bash
just -f infra/justfile secret-rotate runpod-operator
just -f infra/justfile secret-rotate f2
just -f infra/justfile secret-status
just -f infra/justfile runpod-register-plan <image@digest> <template-id> <registry-id>
just -f infra/justfile runpod-register <image@digest> <template-id> <registry-id>
just -f infra/justfile runpod-doctor
```

등록은 endpoint offline과 공유 Pod 부재를 요구한다. 운영 key와 AWS F2 key의 조회 가능 여부, Template의 Secret 참조,
Template ID·image·registry 연결·포트·환경·Volume 설정을 확인한 뒤 SSM에 완성된 기록을 한 번 쓴다.
RunPod 자원 생성·수정·삭제, 자동 generation 증가, `provisioning` 중간 상태는 없다.
검증 실패 시 기존 등록은 보존되며 Console 설정을 수정하고 같은 명령을 다시 실행한다.
등록 조회만으로 양쪽 F2 Secret **값**의 일치나 private image pull 성공은 확인할 수 없다.
이 두 항목은 첫 Pod 기동과 인증 health에서 확인하며 실패하면 active 전환 전에 Pod를 정리한다.

## 일상 운영

게시 단계는 모델·adapter·평가 정보와 checksum을 검증한다. 동일 release ID의 다른 내용은 거부한다.
기존과 같은 checksum의 부분 게시만 이어서 완료한다.

```bash
just -f infra/justfile sllm-artifact-inspect /handoff/release.tar.gz
just -f infra/justfile sllm-artifact-publish /handoff/release.tar.gz
just -f infra/justfile runpod-create-plan <release-id> <secure-cloud-gpu-id>
just -f infra/justfile runpod-create <release-id> <secure-cloud-gpu-id>
just -f infra/justfile runpod-status
just -f infra/justfile runpod-smoke
```

미평가 `dev-*` bundle에는 일반 create 대신 `runpod-create-dev-plan`과 `runpod-create-dev`를 쓴다.
팀에 미평가 상태를 알린다. 이는 기동·연결 검증이며 품질 승인이나 정식 승격이 아니다.

plan과 create 모두 현재 Console Template을 등록된 digest·설정과 대조한 뒤 S3 cross-hash,
공유 Pod 부재와 Backend API·Worker health를 확인한다. plan은 presign·GPU 생성을 하지 않는다.
create는 1시간 presigned URL을 Pod에 전달한다. 두 `/v1/models`에 각각 `sllm`, `stt`가 확인되면
SSM endpoint를 active로 바꾸고 **API의 F2 환경변수만 갱신해 API만 재생성**한다. 같은 image를 유지하며
Worker·migration 환경파일과 다른 API 설정은 변경하지 않는다. 마지막으로 합성 F2 smoke를 실행한다.

```bash
just -f infra/justfile runpod-delete <정확한-pod-id>
just -f infra/justfile runpod-offline-smoke
```

삭제 전 진행 중인 F2 요청이 끝났는지 확인한다. offline 전환·API 재생성 뒤 Pod를 삭제하며
이후 F2는 503 `F2_UNAVAILABLE`을 반환한다. 다음 생성 시 기반 모델·STT weight를 다시 받는다.
자동 중지는 없으므로 생성한 운영자가 작업 종료 시 삭제를 책임진다.

## 이미지 변경과 비밀 회전

- **이미지 변경:** Pod 삭제·offline 확인 → Console의 같은 Template image를 새 digest로 변경 →
  `register-plan → register → doctor` → release create·smoke. 이전 digest로 되돌릴 때도 같은 순서다.
- **F2 key:** offline·Pod 부재 확인 → Console 두 Secret 값을 교체 → `secret-rotate f2`에 같은 값 입력 →
  다음 create의 인증 health·smoke. Secret version 동기화 상태를 따로 저장하지 않는다.
- **GHCR PAT:** offline·Pod 부재 확인 → Console registry credential 교체·Template 연결 확인 →
  `register-plan → register → doctor`. 새 registry ID이면 그 ID로 등록한다. AWS에 PAT를 복제하지 않는다.
- **RunPod API key:** 새 key 발급 → 해당 `secret-rotate` → 운영 조회 성공 확인 →
  Console에서 이전 key 비활성화. 기존 key를 먼저 폐기하지 않는다.
- **OpenAI key:** `secret-rotate openai`는 전체 환경 refresh(`--all`) 완료를 기다린다.
  이 경로만 API·Worker를 함께 재생성하므로 실행 중인 Worker 작업 종료 후 수행한다.
- Discord key는 기존 `secret-rotate delivery-discord|alarm-discord`를 사용한다.

## 실패 시 복구

| 실패 지점 | 자동 처리 | 운영자 다음 행동 |
|---|---|---|
| Console 등록 검증 | SSM 등록 유지, 외부 자원 변경 없음 | 오류 필드 수정 후 register-plan 재실행 |
| 모델 download·health 또는 F2 smoke | offline 전환·refresh와 새 Pod 삭제 시도 | status로 Pod 부재와 endpoint 확인 후 원인 수정 |
| offline 전환의 API refresh | offline 유지, Pod 유지 | status·reconcile로 의도값 확인 후 삭제 재시도 |
| offline 정리 또는 삭제도 실패 | `runpod-reconcile-required`, 완료로 보고하지 않음 | 아래 수동 조정 순서 |

`runpod-status → runpod-reconcile`로 SSM 의도값과 실제 Pod를 확인한다. reconcile 기본은 읽기 전용이며
Pod가 없을 때 `runpod-reconcile-apply`로 offline을 적용한다. 이미 offline이어도 API refresh와
offline smoke를 재실행하여 이전 refresh 실패를 복구한다.
다른 Pod·복수 Pod·health 실패·RunPod API 장애는 추측해서 변경하지 않는다. offline orphan은 정확한 ID의
`runpod-delete`로 삭제한다. 마지막으로 해당 active/offline smoke를 확인한다.

전용 감시 Lambda·EventBridge·RunPod 경보는 제거했다. 방치 시간·상태 불일치 자동 알림은 없다.
생성한 운영자가 시작 시 `status → smoke`, 종료 시 `delete → status → offline-smoke`를 수행하고
Console에서 Pod 부재와 사용액을 확인한다. 한 번에 한 명만 운영 명령을 실행한다.
기존 Backend·AI 오류 알림은 유지한다. GPU 메모리 부족은 SLLM·STT가 함께 중단될 수 있으므로
Console에서 프로세스명과 오류를 확인하고 검증한 image·모델 조합으로 재생성한다.
등록 도구는 Secret 목록을 별도 조회하지 않는다. Console에서 두 이름과 값을 확인하고
최초 Pod 인증 health가 성공하는지 확인한다. 외부 apply 전 saved plan에서 제거 대상 자원을 검토한다.

## 최초 실환경 검증과 기존 코드 전환

시연 합격 조건은 아래 표다. 현재 모의 테스트 결과를 실제 RunPod 성능 검증으로 해석하지 않는다.

| 검증 | 합격 조건 | 현재 증거 |
|---|---|---|
| 혼잡 | 겹치는 분석 10건 중 1건 실행·9건 429, 그동안 일반 health 응답 | 합성 pipeline API 테스트 |
| 실패·취소 | 실패 뒤 재시도 가능, 취소된 실행이 끝날 때 파일·슬롯 정리, 혼잡 요청 본문 미소비 | API 회귀 테스트 |
| 기동·공동 종료 | SLLM health 뒤 STT 기동, timeout·프로세스 종료 시 시작한 서비스 정리 | supervisor 모의 테스트 |
| 실제 GPU | 두 모델 기동·합성 F2 분석 완료, 지원할 음성 길이에서 OOM 없음 | 미실행 |
| 실제 복구 | create·smoke·delete·offline-smoke 후 같은 조합으로 재기동 성공 | 미실행 |

실환경 기록에는 실행 날짜, 코드 revision, image digest, release ID, STT commit, GPU 종류·VRAM,
합성 음성 길이, cold start·분석·복구 소요 시간, 최대 메모리 사용량, 429 건수와 최종 Pod 부재 여부를
남긴다. 원본 음성·전사·제안·키·presigned URL은 기록하지 않는다. OOM이면 먼저 GPU 메모리와
모델 조합을 다시 검토하며 비율 변경만으로 해결됐다고 가정하지 않는다. 합격한 한 조합을 시연에 고정한다.

현재 `dev-f2-handwritten-v05-qwen3-4b-full-v1`은 S3 게시 완료이며 RunPod·이번 변경은 외부 미적용이다.
먼저 새 runtime image 게시와 위 Console 등록을 완료하고, `--f2-only` renderer가 포함된 Backend
revision을 배포한다. 오래된 Backend revision은 Worker도 재시작하므로 새 운영 명령보다 먼저 교체한다.

최초 검증은 `create-dev-plan → create-dev → status → smoke → delete → offline-smoke`다.
기동 소요 시간, 선택 GPU, 음성·분석 동시 요청 결과, 메모리 부족 여부를 안전한 메타데이터로 기록한다.
실제 GPU 검증 전에는 현재 메모리 비율이나 임의 GPU를 검증 완료 조합이라고 표현하지 않는다.
기존 control v1은 offline 상태에서 register하면 v2 단일 기록으로 교체한다. 기존 RunPod 자원을 도구가
삭제하지 않으므로 Console에서 기존 Template을 재사용할 때 이름·설정을 위 표에 맞춘다.

공식 참고: [Template 설정](https://docs.runpod.io/pods/templates/manage-templates),
[vLLM 0.11.0 엔진 설정](https://docs.vllm.ai/en/v0.11.0/cli/serve.html),
[Secret 관리](https://docs.runpod.io/pods/templates/secrets),
[Template ID 조회](https://docs.runpod.io/api-reference/templates/GET/templates/templateId).

## 게시·캐시 검증의 신뢰 경계

품질 판정은 `manage_sllm_artifact.py inspect/publish`에서 수행한다. 평가·승인 문서의 checksum뿐
아니라 승인 상태·선택 모델·dataset provenance를 검사하고, CLI는 inspect 성공 뒤에만 publish한다.
등록된 S3 객체는 bundle/manifest SHA256을 양방향으로 결속하며 create는 이를 확인한 후
bundle SHA256을 runtime에 전달한다. runtime은 다운로드 bytes와 안전한 압축 해제·모델 commit·
adapter bytes를 검증한다. 평가 정책의 재해석은 하지 않는다.

이 경계는 승인된 게시 도구와 S3 쓰기 권한을 신뢰한다. S3 객체와 metadata를 모두 임의로 쓰거나
runtime 입력과 캐시 영수증까지 수정할 수 있는 운영자를 암호학적으로 차단하는 구조가 아니다.
수동 S3 업로드는 지원하지 않는다. `verified`의 품질 승인을 checksum 일치만으로 주장하지 않는다.
미평가 모델은 기존 명시적 dev release 경로만 사용한다.

캐시 생성 시 전체 release 파일의 경로·내용 SHA256을 영수증에 기록하고, 재사용 전 다시 계산한다.
평가/승인 문서·adapter의 변경, 파일 누락·추가·symlink 및 구형 영수증은 기동을 거절한다.
실행 중인 서버의 캐시는 변경하지 않는다. RunPod는 삭제·재생성하고, AWS는 앱 drain/GPU 정지 후
해당 disposable release 캐시를 재생성해 정본을 재다운로드한다. S3 release 정본은 삭제하지 않는다.
전체 host/영수증 동시 변조나 검증 뒤 실행 중 변조를 방어하는 attestation은 제공하지 않는다.

Console Secret과 AWS Secret은 운영자가 같은 값을 입력한다. 등록 성공은 Secret 값 일치의 증거가
아니며, 최초 기동 시 인증 health/smoke 통과 전에는 endpoint를 active로 게시하지 않는다.
회전은 offline·Pod 부재에서 수행하고 Console과 AWS 양쪽 변경 후 다시 기동·검증한다.
