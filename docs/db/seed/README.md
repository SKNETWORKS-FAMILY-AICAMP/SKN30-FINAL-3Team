# F3 합성 seed 데이터

이 디렉터리는 F3 파이프라인을 로컬 또는 공유 dev에서 끝까지 돌려 보기 위한 **합성 장부와 예시 매칭 결과**를 관리한다. 실제 모델 호출 없이 화면과 저장 결과 조회를 확인할 수 있다.

seed 파일은 migration이 아니다. 실행기가 적용 여부를 관리하지 않고, 번호도 `migrate/`와
무관하며, prod에는 적용하지 않는다. 합성 데이터가 운영 스키마 전진 migration에 딸려
들어가지 않도록 디렉터리를 분리했다.

## 파일

| 파일 | 성격 | 하는 일 |
|---|---|---|
| `001_F3_SYNTHETIC_RESET.sql` | 쓰기 | 합성 사무소 1곳의 데이터만 지운다 |
| `002_F3_SYNTHETIC_SEED.sql` | 쓰기 | 합성 사무소·사용자·장부·상담 로그를 만든다 |
| `model-profiles/*.sql` | 쓰기 | 선택한 Provider·모델 설정 두 건을 만든다 |
| `003_F3_SYNTHETIC_VERIFY.sql` | 읽기 전용 | 결과 생성 전 장부와 모델 프로필을 30가지로 점검한다 |
| `backend/src/synthetic_match_results.py` | 쓰기 | 실제 실행·저장 파이프라인에 결정적 예시 생성기를 연결한다 |
| `004_MATCH_RESULTS_VERIFY.sql` | 읽기 전용 | 결과·현재성·예시 출처를 12가지로 점검한다 |

## 모델 프로필

관리 명령은 아래 고정 이름만 허용한다. SQL 경로나 provider·model 문자열은 입력받지 않는다.

| 프로필 | Provider | 모델 | `endpoint_alias` | 사용 상태 |
|---|---|---|---|---|
| `local-openai` | `openai` | `gpt-5.6-luna` | `NULL` | 로컬 개발 기본값 |
| `dev-bedrock-gpt56-luna` | `bedrock` | `global.openai.gpt-5.6-luna` | `general-dev-bedrock` | 공유 dev POC; doctor 후 명시 적용·합성 smoke 검증 |
| `dev-qwen38-vllm-bnb` | `vllm` | `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` | `general-dev-gpu` | 프로필만 구현; GPU runtime 전환 전 적용 금지 |
| `dev-qwen38-llamacpp-gguf` | `llama_cpp` | `unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M` | `general-dev-gpu` | 프로필만 구현; GPU runtime 전환 전 적용 금지 |

두 Qwen 프로필은 모델 revision을 `model_version`에 고정한다. GGUF 프로필은 파일 SHA-256도
함께 기록한다. 프로필마다 `POSITION_CARD`와 `BROKERAGE_JUDGMENT`를 하나씩 만들며 자동 fallback이나
A/B 분배는 하지 않는다.

## 안전 범위

- 삭제 대상은 `brokerage.name = 'F3_SYNTHETIC 합성중개사무소'` 한 곳뿐이다. 다른 사무소,
  다른 개발 계정과 `seed-sample-ledger`가 만든 데이터는 건드리지 않는다.
- 개인 로컬 합성 DB와 `infra/environments/dev`가 소유한 공유 dev에서만 사용한다. prod와 다른
  공유·운영 DB에는 적용하지 않는다.
- 공유 dev 적용은 Bedrock doctor 통과 후 커밋된
  reset·data·`dev-bedrock-gpt56-luna` profile·장부 검증·예시 결과 생성·결과 검증을
  고정 순서로 실행하는 `infra/justfile`의 `dev-seed-f3` 명령만 사용한다.
  이후 합성 smoke를 실행하고, 실패하면 OpenAI key·runtime이 배포된 경우에만
  `dev-seed-f3-openai`로 명시 복구한다. OpenAI가 준비되지 않았다면 Worker를 정지한다.
- 실존 이름·연락처·주소·상담 원문을 변형해 쓰지 않았다. 전부 새로 지어낸 값이다.
- 연락처는 프로젝트가 합성 fixture에 사용하는 `010-0000-XXXX` 테스트 형식만 쓴다.
- API Key, 토큰, 비밀번호를 넣지 않는다. `app_user.password_hash`에 들어가는
  `!development-login-disabled!`는 해시가 아니라 비밀번호 로그인을 막는 고정 표식이다.

## 로컬 적용

`docs/db/migrate/`의 migration을 먼저 끝까지 적용하고 API와 Worker를 중지한 뒤 실행한다.
`backend/.env`에는 로컬 PostgreSQL을 가리키는 `DB_URL`이 설정되어 있어야 한다.

`backend/`에서 다음 관리 명령을 실행한다. `--confirm-reset`은 기존 합성 사무소의 장부와 실행
결과를 지우고 재적재한다는 명시적 확인이며, 이 옵션 없이는 실행하지 않는다.

```bash
cd backend
uv run python src/manage.py seed-f3-synthetic --confirm-reset \
  --model-profile local-openai
```

명령은 `APP_ENV=local`이고 `DB_URL` 호스트가 `localhost` 또는 loopback IP일 때만 동작한다.
임의 SQL 경로는 받지 않고, 이 디렉터리의 `001` reset → `002` data → 선택한 model profile →
`003` 장부 검증 → 예시 결과 생성 → `004` 결과 검증을 실행한다. 장부 30개와 결과 12개 검사가
모두 `PASS`여야 성공한다. JSON의 `brokerage_id`, `user_id`, `login_id`는 기존 시드 계정을
유지하며, `matching_results`에 84개 대상·81개 완료 결과와 `model_inference:false`를 출력한다.
장부 ID는 reset마다 달라질 수 있으므로 `seed_key` 또는 API로 조회한다.

## 공유 dev 적용

공유 dev RDS와 app EC2가 실행 중이고 실행자가 `team-db-tunnel` 멤버여야 한다.
기존 `dev-seed-f3`는 **Bedrock 프로필을 선택하는 명령**이다. GPU/Qwen 설정을 유지하는
범용 seed 명령이 아니므로 현재 배포 모델과 다른 경우 그대로 적용하지 않는다. 허용 프로필과
해당 Provider의 doctor·배포 절차를 먼저 맞춘다. 먼저 커밋된
migration을 적용한 뒤 F3 합성 사무소 데이터를 재적재한다.

```bash
cd infra
just db-migrate
just dev-seed-f3
```

`dev-seed-f3`는 다음 경계를 강제한다.

- 개인 `aws login` IAM 사용자와 같은 이름의 PostgreSQL 역할을 사용한다.
- 태그로 제한된 app EC2의 SSM remote-host 터널과 15분 IAM DB 토큰을 프로세스 내부에서만 쓴다.
- 실행 파일을 `001` reset → `002` data → `dev-bedrock-gpt56-luna` profile →
  `003` 장부 검증 → `backend/scripts/seed_match_results.py` 결과 생성·`004` 검증으로
  고정하고 임의 SQL 경로를 받지 않는다.
- `app_owner` 역할로 실행하며 IAM token과 DB URL을 명령행·로그에 출력하지 않는다.
- `003`의 30개 검사와 `004`의 12개 검사, 84개 대상·81개 적격/완료 결과 및
  `model_inference:false`까지 확인해야 완료로 보고한다. 결과 단계가 실패하면 완료를 표시하지 않는다.
- Backend의 `uv`와 잠긴 의존성도 필요하다. 적용 전 `uv sync --locked --project ../backend`로 준비한다.

확인 프롬프트는 기존 `F3_SYNTHETIC 합성중개사무소`의 실행 결과와 장부를 reset한 뒤 다시
적재한다는 사실을 명시한다. 다른 사무소 데이터는 reset 대상이 아니지만, 공유 dev에서 실행 중인
F3 작업이 없을 때만 실행한다.

`002`의 마지막 출력에 `AUTH_DEVELOPMENT_BROKERAGE_ID`와 케이스별 `anchor_id`가 나온다.
자동 증가 ID는 로컬마다 다르므로 이 문서의 숫자를 그대로 복사하지 않는다.

로컬에서는 `backend/.env`에 출력된 값을 넣고 API 서버를 재시작한다.

```dotenv
AUTH_DEVELOPMENT_ENABLED=true
AUTH_DEVELOPMENT_BROKERAGE_ID=<brokerage_id 출력값>
AUTH_DEVELOPMENT_LOGIN_ID=f3_synthetic_dev
```

이후 [Backend 실행 안내](../../../backend/README.md)에 따라 API를 실행하고
`http://127.0.0.1:8000/docs`에서 개발 세션 발급 → 저장 결과 목록·상세 조회 순서로
확인한다. 인증·CSRF와 F3 경로의 정본은 [API 계약](../../../.agents/skills/project-wiki/references/contracts/api.md)이다.
이 seed는 별도의 `create-development-user`, `seed-sample-ledger`와 AI 모델 설정 등록을 대신한다.

공유 dev에서는 `002`가 출력한 `brokerage_id`와 `f3_synthetic_dev`를 ignored
`infra/environments/dev/dev.tfvars`의 `development_auth`에 반영하고, 검토한 Terraform plan을
적용한 다음 애플리케이션을 다시 배포한다. seed 명령은 Terraform 설정이나 실행 중인 프로세스를
자동으로 변경하지 않는다.

## 예시 결과와 실제 모델 검증

기본 명령은 `agent_run`, 포지션 카드·가격·근거, `match_evaluation`, 후보 판정·근거와
`match_target_state`를 채운다. 매물 36건·구입장 48건 중 적격 81건에 완료 결과를 만들고,
종료된 `L6`·`R7`과 미지원 거래 `R8`은 판정하지 않는다. 후보가 없는 적격 대상은 후보 0건의
완료 결과를 갖는다. 다수 후보는 기존 SQL 순서와 상위 5건 정책을 따르며 나머지는 미판정이다.

생성기는 AI 공개 DTO와 실제 Backend 접수·후보 선택·저장 파이프라인을 사용한다.
외부 모델 호출·토큰 사용은 없으며 활성 Provider 설정을 테스트 Provider로 바꾸지 않는다.
실행 입력·출력의 `synthetic_fixture`에 `DETERMINISTIC_MATCH_SEED`, `version:v2`,
`model_inference:false`를 저장한다. 공개 API는 `is_synthetic_fixture`만 제공하고 화면에는
**시드 예시 결과 — 실제 모델 추론 결과가 아닙니다.**를 표시한다. 고정 규칙으로 만든 등급은
화면·저장 경계 검증용이며 실제 모델 품질을 보장하지 않는다. 예시 카드·판정은 전용
prompt/workflow 버전으로 캐시를 분리해 후속 실제 모델 실행이 예시 카드를 재사용하지 않게 한다.
예시 등급은 표기 가격·예산 차이(10% 이내 부족은 약함)와 1년 초과 희망 입주일 등을
사용하는 표시 규칙이다. 실제 중개 판정 정책으로 적용하지 않는다.

`match_target_state`를 먼저 제거한 뒤 결과·장부를 삭제하고, 장부 삭제 트리거가 만든
`match_change_outbox`와 `match_source_revision`을 마지막에 정리한다. 결과 생성 후에도 해당
합성 사무소의 이벤트·예약만 정리한다. 다른 사무소 실행을 선점하지 않는다.
완료 결과의 현재성은 운영과 동일한 입력 revision·모델 설정·UTC 날짜 기준을 따른다.
다음 날이나 장부 수정 후에는 이전 결과가 되며, 새 모델 판정이 완료되면 예시 표시가 사라진다.

실제 모델과 Worker의 실행을 확인할 때는 결과가 없는 원장을 별도로 준비한다.

```bash
cd backend
uv run python src/manage.py seed-f3-synthetic --confirm-reset \
  --model-profile local-openai --ledger-only
```

이 경우 `003`의 결과 0건 검증까지만 수행한다. API·Worker를 실행하고 실제 판정을 요청한다.
공유 dev의 기본 명령은 예시 결과까지 생성하므로, 모델 smoke는 기존 `just ai-smoke general` 등
현재 활성 Provider의 운영 절차로 별도 검증한다. 시드 결과 조회 성공을 모델 smoke 성공으로
기록하지 않는다.

## 케이스 구성

작은 회귀 케이스 A~E에 대량 케이스 F~I를 더한다. 전체 데이터는 단지 5개, 세대 36개,
인물 87명, 매물 36건, 구입장 48건, 상담 로그 169건이다. 이 중 대량 확장분은 매물 30건과
구입장 40건이며, 별도 합성 단지에 격리해 기존 A~E의 후보 수를 바꾸지 않는다.

| 케이스 | 앵커 | `seed_key` | 기대 후보 수 | 무엇을 확인하나 |
|---|---|---|---:|---|
| A | 매물 (매매 28.8억) | `L1` | 3 | 강한·약한·기각 후보가 한 실행에 함께 나온다 |
| B | 구입장 (매수 29억) | `R1` | 2 | 반대 방향 앵커도 같은 파이프라인을 탄다 |
| C | 매물 (월세) | `L5` | 0 | 해당 단지를 희망하는 월세 구입장이 없다 |
| D | 구입장 (매도) | `R8` | 0 | 대응하는 매물 거래 유형이 없는 구분이다 |
| E | 매물 (전세 21.5억) | `L4` | 1 | SQL은 통과하지만 시점이 결정적으로 어긋난다 |
| F | 매물 (대량 매매) | `BL01` | 19 | 전체 후보 19건 중 상위 5건만 카드화한다 |
| G | 구입장 (대량 매수) | `BR01` | 12 | 반대 방향에서도 다수 매물을 안정적으로 찾는다 |
| H | 매물 (대량 전세) | `BL13` | 12 | 전세 보증금 가격 축으로 후보를 찾는다 |
| I | 매물 (대량 월세) | `BL23` | 10 | 월세 보증금·월 차임 가격 축을 보존한다 |

### 대량 케이스 분포

| 단지 `seed_key` | 거래 유형 | 매물 | 구입장 | 장부 키 범위 |
|---|---|---:|---:|---|
| `C3` | 매매·매수 | 12 | 18 | `BL01`~`BL12`, `BR01`~`BR18` |
| `C4` | 전세 | 10 | 12 | `BL13`~`BL22`, `BR19`~`BR30` |
| `C5` | 월세 | 8 | 10 | `BL23`~`BL30`, `BR31`~`BR40` |

대량 행은 `custom_fields.dataset = "BULK"` 또는 단지의 `extra_info.dataset = "BULK"`로도
구분할 수 있다. 각 매물·구입장에는 합성 상담 로그가 2건씩 있으며, 번호에 따라 가격 유연성,
입주 시점과 연락 가능성 표현이 달라진다.

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
- 케이스 F에서 `candidate_selection.total_count=19`이고 `selected_for_cards=true`가 5건인가
- `anchor_card.evidence`에 저장된 상담 로그를 가리키는 근거가 있는가
- `candidates[].match_grade`가 `STRONG`·`WEAK`·`REJECTED` 중 하나인가
- `REJECTED` 후보에 `rejection_reason`이 있는가
- 케이스 C는 빈 결과로 `COMPLETED`, D는 `INSUFFICIENT_INPUT`이며 실행이 생성되지 않는가

실제 모델 검증에서는 등급 자체를 정답으로 고정하지 않는다. 기본 시드는 화면 확인을 위해 결정적 예시 등급을 제공한다. 케이스 설계는 등급이 나올 **근거**를 상담 로그에
넣어 둔 것이지 모델의 출력을 강제하지 않는다.

## AI 모델 설정

`002`는 합성 장부만 만들고 관리 명령이 선택한 정적 프로필 SQL이
`POSITION_CARD`와 `BROKERAGE_JUDGMENT` 설정을 만든다. 임의 `UPDATE`, provider·model
문자열, SQL 경로로 모델을 바꾸지 않는다. 새 모델은 provenance를 검토한 후
allowlist 프로필과 검증 쿼리를 함께 추가한다.

API key나 클라우드 자격 증명은 SQL에 넣지 않는다. Bedrock 활성 환경 정책은
[ADR-0027](../../../.agents/skills/project-wiki/references/decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md),
Qwen provenance와 비활성 비교 경로는
[ADR-0026](../../../.agents/skills/project-wiki/references/decisions/ADR-0026-general-ai-provider-and-model-profiles.md)를
따른다.
