# LLM 통합 검증 기록

기준일: 2026-09-07. 자동 검증 통과와 외부 운영 완료를 구분한다.

## 자동 검증

| 범위 | 결과 |
|---|---|
| Backend 단위·API·합성 seed/model-only PostgreSQL | 404 통과. `/tmp`의 격리 PostgreSQL 15에 migration 후 실행·종료 |
| AI 단위 | 267 통과 |
| Infra 단위·호환성·전환 실패·종료 실패 | 196 통과 |
| 기존 RunPod 인증 proxy·runtime | 31 통과 |
| Backend·AI Ruff / Pyright | 통과 / 오류 0 |
| Terraform dev fmt·validate | 통과 |
| 변경 shell 구문·just 형식·diff 공백 | 통과 |

모델-only DB 테스트는 두 번 활성화 전후 `ai_model_config` 외 모든 public 테이블의
행을 비교한다. 장부·실행 이력은 같고 이전 모델 profile ID도 보존된다.
테스트는 클라우드·공유 DB·개인 `.env`의 비밀값을 출력하거나 변경하지 않는다.

## 읽기 전용 외부 사전 확인

- 대상 AWS 계정과 서울 리전 로그인을 확인했다. F2 RunPod 등록은 ready이며 기존 등록값을 보존한다.
- 기반 apply 후 general 등록 문서와 serving selection이 생성됐다. general 등록은 uninitialized, endpoint는 offline이며 작업 선택은 아직 null이다.
- 서울 제공 AZ: g6.2xlarge는 a/c/d, g6e.2xlarge는 a/b. 공통 a를 후보로 사용한다.
  Offering 조회는 실제 기동 시 용량을 예약하거나 보장하지 않는다.
- G/VT On-Demand vCPU quota: 768. 요청할 두 인스턴스는 각 8 vCPU다.
- AWS Price List Linux Shared: F2 $1.20208/h, general $2.75652/h. GPU 합계 $3.95860/h.
  비용은 [운영 절차](README.md)의 보존·실행 상태별 기준으로 평가한다.
- NVIDIA Ubuntu 24.04 DLAMI 후보 `ami-0097a4a30ec557269`의 공식 소유·이름을 조회했다.
  Docker Compose·toolkit과 수정 runtime 후보의 AWS 실기동을 후속 검증에서 확인했다.
- vLLM v0.26.0 linux/amd64 공식 digest는 [image-provenance.json](image-provenance.json)에 기록했다.
  이는 Qwen BnB GPU 추론 통과 기록이나 완성 프로젝트 이미지 digest가 아니다.

## 외부 적용과 실제 측정 — 미완료

2026-09-07 F2·general 이미지 게시와 새 GHCR 인증 연결, 두 이미지의 원격 pull 성공을 확인했다. 사용자의 후속 명시적 승인 후 F2 수정 후보는 SLLM JSON·Whisper 합성 요청을 통과했다. general BnB 후보는 가중치 shape assertion으로 실패했다. 사용자가 선택한 Unsloth FP8 후보는 L40S 48GB에서 JSON·한국어 생성·F3 두 capability의 합성 요청을 통과했다. AWS GPU 후보·사설 앱에서 F2 HTTP·범용 한국어·F3 두 capability도 통과했다. 게시 수정 이미지·정식 앱 배포와 왕복 전환 검증은 남아 있다.
게시 digest·원격 확인 결과·인증 및 general 최초 설정의 남은 조건은 [원격 검증 기록](remote-validation-2026-09-07.md)에 둔다. 로컬 PC에서는 이미지·모델을 실행하지 않는다.
사용자 승인 후 기반 Terraform apply는 완료했다(9 생성·7 변경·16 삭제). 같은 중지 입력의 drift plan은 No changes, 종료 코드 0이다. 당시 앱 새 revision과 AWS GPU는 배포하지 않았으며, 후속 AWS 시험은 별도 후보 이미지·임시 앱으로 진행했다. 이번 원격 검증에서 F2 RunPod를 생성·삭제했고, 사용자의 설정 대행 요청으로 general Secret·Template을 공식 API로 생성·등록했다.
Backend·AI 각자의 local 설정을 바인딩해 확인했으나 개인 OpenAI 키가 설정되어 있지 않아 유료 호출은 실행하지 못했다.

검토용 기반 saved plan은 `infra/environments/dev/dev-serving-foundation.tfplan`에 둔다.
현재 deep 중지와 GPU 0대를 유지하는 입력을 사용한다. 전체 변경 목록과 검토 요약은
[foundation-plan-review.md](foundation-plan-review.md)에 적용·검증 결과를 기록했다. 앱 인스턴스 0·RDS stopped·CloudFront disabled·관리 AWS GPU 0이며, 기존 F2 등록과 RDS·업무 S3가 보존됐다.
완성 이미지 digest·등록·GPU profiles가 준비된 뒤 별도 GPU saved plan을 만든다.

| 실제 수용 항목 | 상태 | 남길 측정 |
|---|---|---|
| local 개인 OpenAI 기본값 | 키 미설정으로 실호출 미검증 | 각 모듈 설정 바인딩 확인; 키 설정 후 두 capability 결과 |
| local→AWS 고정 SSM, local→RunPod | 미검증 | 권한·재연결·꺼진 GPU 실패 |
| F2 AWS / RunPod | 두 곳의 수정 후보 통과; AWS 앱 HTTP 음성 분석 11.77초 | 수정 이미지 재게시·정식 배포 확인 |
| general AWS / RunPod | 두 곳 FP8 후보 통과; AWS 앱 F3 합계 155.88초 | 정식 모델 설정·이미지·배포 확인 |
| 혼합 배치 2가지와 양방향 전환 | 미검증 | source/target, drain·연결·종료 결과 |
| 일반 stop/start 반복 | 미검증 | 기동 시간, 캐시 재사용, 지연 |
| deep-stop/start | 미검증 | 삭제 EBS, 캐시 재다운로드, DB·정본 보존 |
| 비용·잔존 자원 확인 | AWS 후보 검증 완료: GPU/EBS 삭제, 앱 0·RDS stopped, drift 없음 | GPU 약 $2.41 추정; 정식 운영·왕복 검증은 별도 |

승인된 검증 시간 안에서 한 운영자가 실행한다. 모델명·revision·image digest·인스턴스 종류와
측정값만 기록하고 실제 endpoint·키·원문 요청/응답은 기록하지 않는다.

AWS 사설 시험의 구성·송신 규칙 누락 수정·측정 범위·정리 상태는
[2026-09-07 AWS 앱 검증](aws-private-validation-2026-09-07.md)에 기록한다.
