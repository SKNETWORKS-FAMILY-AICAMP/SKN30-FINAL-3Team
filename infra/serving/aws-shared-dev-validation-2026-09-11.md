# AWS GPU 공유 dev 기동 검증

- 기준일: 2026-09-11
- 선택 ID: `0e4c2811-dcfa-4a7b-913d-b6e925bf4210`
- 판정: **F2와 general을 AWS GPU로 기동했고 직접 추론, 앱 경유 합성 요청, 모델 identity와 GPU 계측을 확인했다.**
- 한계: 연결·기동 검증이며 모델 품질 평가, 동시 부하 시험, 확정 청구액 검증은 아니다.

## 실행 구성과 최종 상태

| 작업 | AWS 자원 | 모델·이미지 | 최종 검증 |
|---|---|---|---|
| F2 | `i-0f9e1198c00589d96`, `g6.2xlarge`, L4 24GB, gp3 160GiB | `consultation-v3`, Qwen3-4B + Whisper-large-v3-turbo, F2 digest `4566d0…262628` | SLLM/STT 직접 추론·앱 요청·identity·GPU 계측 통과 |
| general | `i-04fb30024d72be7a0`, `g6e.2xlarge`, L40S 48GB, gp3 160GiB | `qwen38-27b-fp8`, revision `017b9c7…ca20a`, general digest `7d9598…ceeb08` | 직접 추론·앱 요청·identity·GPU 계측 통과 |

최종 `dev-status`에서 앱 ASG desired 1, 앱 target healthy, RDS available, 앱과 두 GPU의 SSM Online,
두 GPU endpoint active·model ready를 확인했다. 관리 RunPod Pod는 0개다. 앱 revision은 CodeDeploy
`d-DPW21MWQK`, 저장 revision SHA-256은 `9ae0db…f69`다.

`dev-start`의 DB 미리보기에서 사무소 2의 `POSITION_CARD`, `BROKERAGE_JUDGMENT`, `CHATBOT`이
모두 선택한 general 모델과 호환되고 `pending_work`가 0임을 확인했다. 이전 stop 시 남은 F3 실행은
같은 모델로 재개·정착됐으므로 실제 시드 데이터는 줄이지 않았다. general 앱 합성 단계가 한 실행에서
약 5분 걸렸지만 300초 provider timeout을 넘지 않고 완료됐고, 이후 공식 직접 추론은 1.185초였다.

## 직접 검증 측정

| 대상 | 확인 시각 (UTC) | 직접 추론 응답시간 | 관측 VRAM peak / total | 표본 | 결과 |
|---|---|---:|---:|---:|---|
| F2 SLLM | 2026-09-11 08:50:51 | 0.283초 | 19,840 / 23,034 MiB | 3 | 모든 identity 및 앱 요청 통과 |
| F2 STT | 2026-09-11 08:50:51 | 0.084초 | 19,840 / 23,034 MiB | 2 | 모든 identity 및 앱 요청 통과 |
| general | 2026-09-11 08:47:03 | 1.185초 | 39,161 / 46,068 MiB | 6 | 모든 identity 및 앱 요청 통과 |

F2 두 엔진은 같은 device를 사용하므로 VRAM 값을 합산하지 않는다. 값은 검증 중 표본의 관측 최고값이며
절대 최대나 프로세스별 사용량이 아니다.

## 발견한 문제와 반영

1. EC2 user-data의 base64 크기가 25,600 bytes를 넘었다. host bootstrap을 private data-model S3의
   hash 고정 tar.gz로 옮기고 Instance Role의 정확한 object 읽기와 SHA-256 확인을 적용했다.
2. 정지한 EC2의 자동 공인 IPv4 refresh가 Terraform 교체로 해석돼 root EBS 모델 캐시를 삭제했다.
   해당 일시 속성을 lifecycle에서 제외했고, 같은 인스턴스와 160GiB EBS를 재사용하는 plan이
   `terraform_changes: []`임을 확인했다.
3. `/cache/huggingface`가 없는 AWS 직접 snapshot 구성에서 `/ops/status`가 HTTP 500을 반환했다.
   bootstrap이 경로를 항상 만들도록 수정하고 현재 호스트에도 적용해 두 endpoint 모두 HTTP 200,
   identity와 GPU sample을 확인했다.
4. F2 STT의 로컬 실행 경로 `/models/stt`가 안전 identity 필터에서 제거됐다. 다음 이미지의 supervisor는
   논리 모델 ID를 사용하도록 수정했다. 현재 immutable 이미지에는 host의 `config.json`과 정확한
   `.serving-revision` marker를 확인한 경우에만 누락 identity를 보완하는 probe를 적용했다.
5. stop 중 남은 F3가 있으면 같은 모델을 다시 시작할 수 없던 교착을 해소했다. DB 변경을 선택하지 않고
   모든 활성 설정이 호환될 때만 pending 실행의 동일 모델 재개를 허용하며, 실제 모델 변경은 pending이
   하나라도 있으면 계속 차단한다.

진단 과정에서 노출 가능성이 생긴 F2 SLLM/general provider key 두 개는 Secrets Manager 새 버전으로
즉시 회전하고 GPU와 앱을 정상 drain·재기동했다. 비밀값은 저장소와 이 기록에 남기지 않았다.

## 알림과 비용

사용자 요청에 따라 CloudWatch metric alarm 8개는 유지하고 `cloudwatch-alarms` SNS의 Discord Lambda
구독은 0개로 확인했다. 별도 `runtime-alerts` 배포 알림 구독 1개는 유지한다. 콘솔 관측은 유지되지만
CloudWatch alarm의 Discord 전달만 비활성이다.

2026-09-01 서울 On-Demand 조회값은 F2 `$1.20208/h`, general `$2.75652/h`, 합계 `$3.95860/h`다.
2시간 계산은 `$7.9172`이며 EBS·IPv4·앱·RDS·edge·세금은 별도다. `--hours 2`는 자동 종료 타이머가
아니므로 사용 후 `just -f infra/justfile dev-stop`이 필요하다.
