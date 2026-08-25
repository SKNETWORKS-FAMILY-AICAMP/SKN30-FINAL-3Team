# F3 합성 seed 데이터

이 디렉터리는 F3 파이프라인을 로컬에서 끝까지 돌려 보기 위한 **합성 장부**를 관리한다.

seed 파일은 migration이 아니다. 실행기가 적용 여부를 관리하지 않고, 번호도 `migrate/`와
무관하며, 운영 환경에는 적용하지 않는다. 합성 데이터가 운영 스키마 전진 migration에 딸려
들어가지 않도록 디렉터리를 분리했다.

## 파일

| 파일 | 성격 | 하는 일 |
|---|---|---|
| `001_F3_SYNTHETIC_RESET.sql` | 쓰기 | 합성 사무소 1곳의 데이터만 지운다 |
| `002_F3_SYNTHETIC_SEED.sql` | 쓰기 | 합성 사무소·사용자·AI 설정·장부·상담 로그를 만든다 |
| `003_F3_SYNTHETIC_VERIFY.sql` | 읽기 전용 | 데이터가 의도한 모양인지 29가지를 점검한다 |

## 안전 범위

- 삭제 대상은 `brokerage.name = 'F3_SYNTHETIC 합성중개사무소'` 한 곳뿐이다. 다른 사무소,
  다른 개발 계정과 `seed-sample-ledger`가 만든 데이터는 건드리지 않는다.
- 개인 로컬 합성 DB에서만 사용한다. 운영·공유 DB에 적용하지 않는다.
- 실존 이름·연락처·주소·상담 원문을 변형해 쓰지 않았다. 전부 새로 지어낸 값이다.
- 연락처는 프로젝트가 합성 fixture에 사용하는 `010-0000-XXXX` 테스트 형식만 쓴다.
- API Key, 토큰, 비밀번호를 넣지 않는다. `app_user.password_hash`에 들어가는
  `!development-login-disabled!`는 해시가 아니라 비밀번호 로그인을 막는 고정 표식이다.

## 적용

`docs/db/migrate/`의 migration을 먼저 끝까지 적용한 뒤 실행한다.

`infra/local/.env`의 로컬 DB 설정을 현재 셸에 불러온다. 아래 명령은 그 파일의
`POSTGRES_USER`와 `POSTGRES_DB`를 사용하며 특정 계정·DB 이름을 고정하지 않는다.

```bash
set -a
source infra/local/.env
set +a
```

```bash
docker compose --env-file infra/local/.env -f infra/local/compose.yaml \
  exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < docs/db/seed/001_F3_SYNTHETIC_RESET.sql
```

```bash
docker compose --env-file infra/local/.env -f infra/local/compose.yaml \
  exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < docs/db/seed/002_F3_SYNTHETIC_SEED.sql
```

```bash
docker compose --env-file infra/local/.env -f infra/local/compose.yaml \
  exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < docs/db/seed/003_F3_SYNTHETIC_VERIFY.sql
```

두 파일을 순서대로 돌리면 몇 번을 반복해도 같은 상태가 된다. 검증 결과의 마지막 열이
전부 `PASS`여야 다음 단계로 넘어간다.

`002`의 마지막 출력에 `AUTH_DEVELOPMENT_BROKERAGE_ID`와 케이스별 `anchor_id`가 나온다.
자동 증가 ID는 로컬마다 다르므로 이 문서의 숫자를 그대로 복사하지 않는다.

`backend/.env`에 출력된 값을 넣고 API 서버를 재시작한다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=<002 출력값>
AUTH_DEVELOPMENT_LOGIN_ID=f3_synthetic_dev
```

이후 [Backend 실행 안내](../../../backend/README.md)에 따라 API를 실행하고
`http://127.0.0.1:8000/docs`에서 개발 세션 발급 → F3 실행 접수 → 상태·결과 조회 순서로
확인한다. 인증·CSRF와 F3 경로의 정본은 [API 계약](../../../.agents/skills/project-wiki/references/contracts/api.md)이다.
이 seed는 별도의 `create-development-user`, `seed-sample-ledger`와 AI 모델 설정 등록을 대신한다.

## 실행 결과는 seed하지 않는다

`agent_run`, `negotiation_position_analysis`, `negotiation_position_price`,
`match_evaluation`, `match_candidate_evaluation`과 근거 행은 **넣지 않는다**. 이 행들은
Worker가 직접 만들어야 파이프라인 전체가 검증된다. 결과를 미리 넣으면 무엇이 동작하고
무엇이 안 하는지 구분할 수 없다.

`003`의 `agent_run 수`, `포지션 카드 수`, `판정 결과 수` 검사는 이 원칙이 지켜졌는지
확인하는 항목이다.

## 케이스 구성

양쪽 앵커를 모두 확인할 수 있게 매물 기준 3건과 구입장 기준 2건을 둔다.

| 케이스 | 앵커 | `seed_key` | 기대 후보 수 | 무엇을 확인하나 |
|---|---|---|---:|---|
| A | 매물 (매매 28.8억) | `L1` | 3 | 강한·약한·기각 후보가 한 실행에 함께 나온다 |
| B | 구입장 (매수 29억) | `R1` | 2 | 반대 방향 앵커도 같은 파이프라인을 탄다 |
| C | 매물 (월세) | `L5` | 0 | 호환되는 구분의 구입장이 아예 없다 |
| D | 구입장 (매도) | `R8` | 0 | 대응하는 매물 거래 유형이 없는 구분이다 |
| E | 매물 (전세 21.5억) | `L4` | 1 | SQL은 통과하지만 시점이 결정적으로 어긋난다 |

### 케이스 A의 후보 3건

카드화 우선순위는 결정적 SQL 점수로 정해진다. 아래는 실제 backend 점수 함수를 seed
데이터에 돌린 값이다.

| 순위 | `seed_key` | 총점 | 성격 | 기대하는 판정 방향 |
|---:|---|---:|---|---|
| 1 | `R1` | 0.978346 | 예산·평형·단지·시점이 모두 맞는다 | 강한 후보 |
| 2 | `R2` | 0.880070 | 예산이 빠듯하고 입주 시기가 늦다 | 조건이 움직여야 하는 후보 |
| 3 | `R3` | 0.530159 | 44평만 보고 이사 계획이 2년 뒤다 | 기각 후보 |

### 걸러지는 행

같은 사무소에 있지만 후보로 올라오면 안 되는 행을 일부러 섞어 두었다. 조회 조건이 실제로
걸리는지 확인하는 대조군이다.

| `seed_key` | 걸러지는 이유 |
|---|---|
| `R4` | 다른 거래 구분 (전세). 매매 앵커의 반대편이 아니다 |
| `R5` | 예산 하한 미달 |
| `R6` | 다른 단지만 희망한다 |
| `R7` | 종료된 구입장이다 |
| `R8` | 매도 구분은 매물의 반대편이 아니다 |
| `L3` | 예산 상한을 넘는다 |
| `L6` | 종료된 매물이다 |
| `U6` | 매물로 접수되지 않은 세대다 |

## 행 찾기

자동 증가 ID는 로컬마다 다르다. 모든 행은 자기 케이스 키를 갖고 있으므로 그 키로 찾는다.

| 테이블 | 키가 있는 곳 |
|---|---|
| `property_complex` | `extra_info->>'seed_key'` |
| `property_unit` | `custom_fields->>'seed_key'` |
| `property_listing` | `custom_fields->>'seed_key'` |
| `property_requirement` | `custom_fields->>'seed_key'` |
| `party` | `memo = 'seed_key=...'` |

```sql
SELECT id, custom_fields->>'seed_key' AS seed_key, status, sale_price
FROM property_listing
WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소')
ORDER BY seed_key;
```

## 날짜

모든 날짜는 `CURRENT_DATE`와 `now()` 기준 상대값이다. 언제 실행해도 임대차 만기일,
희망 입주일, 의뢰 만료일이 이미 지나 있지 않고 접수일은 과거에 있다. 고정 날짜를 쓰면
몇 달 뒤에 시점 판정이 통째로 무의미해진다.

## 실행 후 확인할 것

모델의 자연어 문장은 팀원끼리 같지 않아도 된다. 고정해서 검증할 대상은 다음이다.

- `status`가 `COMPLETED`인가
- `candidate_selection.total_count`가 위 표의 기대 후보 수와 같은가
- `anchor_card.evidence`에 저장된 상담 로그를 가리키는 근거가 있는가
- `candidates[].match_grade`가 `STRONG`·`WEAK`·`REJECTED` 중 하나인가
- `REJECTED` 후보에 `rejection_reason`이 있는가
- 케이스 C·D가 모델 판정 없이 빈 결과로 `COMPLETED`가 되는가

등급 자체를 정답으로 고정하지 않는다. 케이스 설계는 등급이 나올 **근거**를 상담 로그에
넣어 둔 것이지 모델의 출력을 강제하지 않는다.

## AI 모델 설정

`002`가 `POSITION_CARD`와 `BROKERAGE_JUDGMENT` capability의 활성 설정을 함께 만든다.
기본값은 `provider = 'openai'`, `model_name = 'gpt-4o-mini'`다.

다른 모델을 쓰려면 seed 적용 후 값을 바꾼다. 구조화 출력을 지원하는 모델이어야 한다.

```sql
UPDATE ai_model_config
SET provider = 'vllm', model_name = '<로컬 모델명>'
WHERE brokerage_id = (SELECT id FROM brokerage WHERE name = 'F3_SYNTHETIC 합성중개사무소');
```

API Key는 SQL에 넣지 않는다. `ai/.env`에 둔다.
