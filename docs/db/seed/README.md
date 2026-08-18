# seed — 로컬·데모용 합성 장부 데이터

`migrate/` 와 달리 **migration 실행기가 관리하지 않는다.** 번호는 이 디렉터리 안의 적용 순서일 뿐
`migrate/` 의 번호 체계와 무관하며, 한 번 적용한 뒤에도 다시 적용할 수 있다.

**운영 DB에 적용하지 않는다.** 전부 합성 데이터다.

| 파일 | 내용 |
|---|---|
| `001_F3_CASE_LEDGER.sql` | F3 A군 케이스 검증용 장부. 단지 1 · 세대 20 · 매물 20 · 손님 6 · 인물 37 · 상담로그 188 |
| `002_F3_CASE_PRIVACY_CONSENT.sql` | 구입장 손님 6명에게 개인정보 활용 동의 사실 부여 |
| `VALUES.md` | 시드가 사용한 상태값 어휘 **제안서** |

## 적용

`migrate/001~010` 이 적용된 DB에 순서대로 실행한다.

~~~bash
psql -d brokerage -v ON_ERROR_STOP=1 -1 -f docs/db/seed/001_F3_CASE_LEDGER.sql
psql -d brokerage -v ON_ERROR_STOP=1    -f docs/db/seed/002_F3_CASE_PRIVACY_CONSENT.sql
~~~

`001` 은 `BEGIN`/`COMMIT` 을 담지 않으므로 `-1` 로 단일 transaction 에 감싼다.

시드는 `한들공인중개사사무소` 를 **새로 만든다.** 빈 DB에 넣어야 그 사무소가 `id = 1` 이 되어
`backend/.env` 의 `AUTH_DEVELOPMENT_BROKERAGE_ID=1` 을 고치지 않고 쓸 수 있다.

시드가 만드는 `owner` · `staff1` · `viewer` 계정의 role 값(`BROKER` · `STAFF` · `READONLY`)은
Backend `UserRole`(`OWNER` · `STAFF` · `READ_ONLY`)과 어휘가 다르므로 **로그인 대상이 아니다.**
로그인용 계정은 따로 만든다.

~~~bash
cd backend && uv run python src/manage.py create-development-user \
  --brokerage-name "한들공인중개사사무소" \
  --login-id developer --display-name "Developer" --role OWNER
~~~

## 데이터의 성격

가상 단지 **한들마을 센트럴파크** 기준일 **2026-08-17**. 단지명·동호·인물·금액은 전부 합성이고
실제 공개 정보에서 가져온 것은 제원과 시세 대역뿐이다 — **시세 근거로 쓸 수 없다.**

개인정보는 없다. 이름은 성 1자 + `O` + 이름 1자 마스킹이고 주민번호·주소는 만들지 않았다.
전화번호는 `party_contact` 가 NOT NULL 이라 넣되 **국내 미할당 `010-0XXX-XXXX` 대역만** 써서
실번호 충돌을 원천 차단했다.

상담 로그 188건 중 112건은 합성 상담 로그 CSV의 문장을 그대로 쓴 배경 로그(2025-01 이전)이고,
55건은 A군 판정에 필요한 결정적 진술을 같은 문체로 새로 쓴 케이스 로그(`related_context.case_log = true`)다.

## 상태값 어휘

확정 DDL에는 `status` · `tenancy_status` · `demand_type` · `role` 등에 **CHECK 제약이 하나도 없다.**
따라서 이 시드가 쓰는 값이 사실상 최초 어휘가 된다. [`VALUES.md`](VALUES.md) 는 **제안**이며
확정 전까지 코드에서 상수로만 참조한다. 확정되면 `migrate/` 의 다음 번호 ALTER 로 제약을 추가한다.

Backend 내장 `manage.py seed-sample-ledger` 는 같은 컬럼에 다른 어휘(한글 `입주`·`매수`·`협의`,
`LANDLORD`, `ORGANIZATION`)를 쓴다. 두 시드를 같은 사무소에 함께 적재하지 않는다.

## 생성기

`001` 과 `VALUES.md` 의 원본은 이 저장소 밖 `06_프로토타입_F3플로우/data/` 에 있다
(생성기 `build_ledger.py` · 원본 데이터 `ledger.json`). 데이터를 바꾸려면 생성기를 고쳐
다시 뽑고 이 디렉터리로 복사한다. 여기서 SQL을 직접 손보면 생성기와 어긋난다.

SQL 쪽 검증 쿼리 8종은 같은 위치의 `verify.sql` 에 있다.
