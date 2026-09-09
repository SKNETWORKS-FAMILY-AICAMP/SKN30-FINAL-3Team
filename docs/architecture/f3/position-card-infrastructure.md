---
status: 제안
updated: 2026-09-09
---

# F3 카드·판정 개선의 로컬·dev 자원과 검증 제안

[조건부 자동 판정](conditional-auto-judgment.md)과 [이벤트·재사용 설계](position-card-events.md)를 구현하기 위한 제안이다.
실행 단위·서버 분리의 상세 검토는 [Worker 배포 검토](worker-deployment-review.md)를 따른다. 클라우드 자원 생성·배포·모델 호출은 수행하지 않았다.

## 1차 권고: 기존 PostgreSQL과 Worker 활용

| 역할 | 로컬 | 공유 dev | 추가 작업 |
|---|---|---|---|
| 장부·카드·판정·outbox 저장 | 기존 [Compose PostgreSQL 15](../../../infra/local/compose.yaml) | 기존 RDS PostgreSQL 15 | 전진 migration, revision·미처리 이벤트·작업 선점·최신 카드/판정 조회 인덱스 |
| API | 기존 uv/FastAPI 프로세스 | 기존 EC2의 API container | [신규 조회 GET 3개·기존 POST /runs 재사용 확장](expansion-contracts.md) |
| 이벤트 소비·AI 작업 | API와 별도 Worker 프로세스 | [같은 이미지의 Worker container](../../../infra/deploy/compose.dev.yml) | outbox 소비·재시도·우선순위·누락 보정 |
| 모델 | 단위 검증은 fake, 실제 확인은 기존 개인 OpenAI 설정 | 기존 general capability의 검증된 AWS/RunPod 선택 경로 | F3 전용 GPU 추가는 필요하지 않음. 활성 endpoint·용량은 배포 시 확인 |
| 관측 | 구조화 로그·로컬 DB 집계 | 기존 CloudWatch 로그/metric/alarm 경로 | 대기 나이·실패·cache hit·호출수·토큰·지연 추가 |

로컬 기본은 `WORKER_ENABLED=false`다. 기존 [Backend 실행 안내](../../../backend/README.md)에 따라
검토된 합성 데이터에서 `WORKER_ENABLED=true`, `F3_ALLOW_SYNTHETIC_PROTOTYPE=true`로 별도 Worker를 실행한다.
dev Terraform의 [configuration.tf](../../../infra/environments/dev/configuration.tf)는 두 값을 true로 선언하지만 현재 실행 중이라는 증거는 아니다.
API만 실행하면 접수 후 QUEUED에 머무르므로 카드 UI의 장애/대기 검증에 포함한다.

1차 변경에는 새 AWS 서비스가 필수로 필요하지 않다. 기존 EC2·RDS·general 모델 자원을 재사용한다.
사용자 조건처럼 고정 GPU를 같은 시간 켜두면 추가 호출만으로 GPU 임대료가 늘지는 않는다. DB I/O·로그·저장 공간, 포화로 인한 증설/유료 API 사용은 별도다.
API와 Worker는 논리적으로 분리됐지만 같은 EC2·RDS·GPU를 공유하므로 자원 경합까지 없어진 것은 아니다.

outbox 소비는 느린 AI 작업 뒤에만 실행하지 않는다. 작은 별도 consumer 프로세스 또는 같은 이미지의 별도 역할로 돌려
이벤트 접수·병합을 계속 처리한다. 소비는 DB 작업만 하고 모델은 기존 Worker가 수행한다.
Worker 증설 전에 사용자 판정 요청을 backfill·자동 카드 생성보다 우선하고, 대기 작업에 aging을 적용해 기아를 막는다.
현재 최대 5개 후보 병렬 호출과 챗봇의 general GPU 공유 부하를 감안해 전체 모델 동시성 예산을 제한한다. F2 GPU는 ADR-0030 기준 별도이며 앱·RDS 부하는 공유한다.
PostgreSQL의 queue consumer 용도에서 `SKIP LOCKED`를 사용할 수 있다: [PostgreSQL 15 문서](https://www.postgresql.org/docs/15/sql-select.html).

## 조건부 확장: SQS·DLQ

현재 프로젝트의 SQS 도입은 [OQ-009](../../../.agents/skills/project-wiki/references/open-questions.md)의 조건부 범위다.
DB polling 부하, 오래된 작업 대기, 지연 재시도·독립 확장 필요가 측정될 때 도입을 검토한다.

| 자원·계약 | 제안 |
|---|---|
| 작업 큐 | Amazon SQS Standard + DLQ. 초기에는 1개 작업 큐로 시작하고 카드/판정 지연 격리가 필요하면 각각 분리 |
| 생산 | DB outbox relay가 event_id/job_id와 내부 참조만 발행. DB 상태가 정본 |
| 소비 | DB 작업을 멱등 선점하고 완료 commit 후 메시지 삭제. 중복·역순 메시지는 revision으로 걸러냄 |
| 실패 | SQS visibility와 DB lease의 만료·연장 정책을 맞추고 재시도 예산의 소유자를 하나로 정함. 무조건 3×3 재시도하지 않음 |
| IAM·암호화 | relay SendMessage, consumer Receive/Delete/ChangeVisibility/GetAttributes만 해당 큐에 허용. 큐 암호화·DLQ 보존/재처리 권한 정의 |
| 네트워크 | 현재 dev public egress 경로 재사용 여부 확인. 큐 때문에 NAT를 추가하지 않음. private 전환 시 endpoint/egress 재검토 |
| 관측 | 가장 오래된 메시지 나이·visible/in-flight·DLQ 적재 alarm, 원문 없는 job/event 상관관계 |
| 로컬 검증 | 1차는 PostgreSQL 소비 경로 유지. SQS 도입 시 fake adapter로 단위 검증하고 별도 dev 테스트 큐에서 실제 중복·visibility·DLQ 계약 검사 |
| 비용 | 큐 요청·payload 단위·CloudWatch·선택 KMS/endpoint 비용을 당시 서울 리전 가격으로 산정. 모델 및 Worker 증설 비용 별도 |

Standard는 중복·역순 전달을 허용하므로 DB 멱등성과 fencing을 유지해야 한다.
long polling은 빈 수신을 줄이지만 DB outbox와 완료 결과 캐시를 대신하지 않는다.
[SQS Standard](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html), [long polling](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/best-practices-using-appropriate-polling-mode.html).
불필요한 사전 계산·중복 호출은 고정 GPU의 처리 용량을 소모한다. 이번 요청만으로 Redis·Celery·Kafka·ECS·Lambda는 필수 자원이 아니다.

## 측정 계획

현재 저장 p95와 토큰 비용은 미측정이다. 기존 코드만으로 “부하 없음”이나 절감 시간을 수치로 보장하지 않는다.
격리된 합성 DB에서 동일 입력·동시성으로 다음 구간을 나눠 측정한다.

| 항목 | 측정 방법 |
|---|---|
| 저장 응답 부하 | 메모 수정, 가격 수정, 신규, 같은 값 재저장 각각 반복. F1 commit 시간·F3 접수 시간·전체 HTTP p50/p95/p99 분리 |
| DB 경합 | 같은 앵커/서로 다른 앵커의 동시 저장·판정 요청. advisory lock 대기·pool 대기·오류·query 수 확인 |
| 카드 처리 | cold/warm cache, 상담 로그 양별 DB 시간·Provider 호출/토큰·전체 wall time 비교 |
| 반복 판정 | 같은 입력으로 완료 뒤 새 POST, GET 반복, 새 브라우저 재진입의 모델 호출 수 비교 |
| 공유 자원 | API 저장 + Worker backlog + F2/챗봇 동시 실행 시 CPU·메모리·RDS 연결·GPU 대기 측정 |
| 내구성 | 저장 commit 직후 중단, 소비 중단, 중복/역순 이벤트, 모델 성공 후 저장 전 중단, lease 만료 재선점 주입 |
| 최신성 | 상담 변경·새 후보 등록·후보 삭제·날짜/모델 변경·빠른 연속 수정에서 오래된 결과의 CURRENT 승격이 0건인지 확인 |

repair 실패·최종 저장 실패 때 쓴 토큰도 별도 계측하고 후보 병렬 호출 지연 합을 전체 wall time으로 해석하지 않는다.
현재 lease는 전체 실행 300초·heartbeat 없음이므로 단계별 지연과 재시도 합이 이를 넘는지 확인한다.
넘는다면 단계별 선점/lease 연장과 Provider timeout을 함께 설계해야 하며 큐 교체만으로 해결되지 않는다.
SLA·경보 임계값·큐 전환 조건은 이 측정 뒤 합의한다. 후보 기존 요구의 “5초”를 검증 없이 달성했다고 선언하지 않는다.

## 구현 순서

1. 조건부 자동 판정·결과 목록 요구사항, 최신성·실패 의미와 ADR-0018 후속 변경 합의.
2. 입력 revision·outbox·명시적 실행 범위·조건 gate·변경 병합과 기존 데이터 보정.
3. 판정 identity·완료 재사용·자동 전체 흐름·GPU 동시성/우선순위, 새 후보 유입·누락/경합 검증.
4. 결과 목록·상세 API/UI, 카드 근거 펼침, 준비된 결과 비율·실제 사용자 대기와 공유 모델 지연 검증.
5. 측정 후 별도 CPU Worker 서버·SQS·용량 확장을 선택. 독립 카드 제품 기능은 실사용 수요에 따라 추가.

DB 변경은 기존 [SQL 관리 규칙](../../db/README.md), dev 자원 변경은 Terraform 검토·승인·apply 절차를 따른다.
