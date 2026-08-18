# 상태값 어휘 제안서

확정 DDL(001~009)에는 **enum CHECK 제약이 하나도 없다.** `status` · `tenancy_status` ·
`lifecycle_status` · `counterparty_role` · `demand_type` · `classification` 등이 전부 자유
VARCHAR 이고, `docs/db/README.md`도 「업무 상태값의 최종 목록과 상태 전이 규칙」을 **아직 확정하지
않은 사항**으로 남겨 두었다.

따라서 시드가 쓰는 값이 사실상 최초 어휘가 된다. 아래는 **제안**이며 확정 전에는 코드에서
상수로만 참조해야 한다. 확정되면 다음 번호의 ALTER migration 에서 CHECK 제약을 추가한다.

| 대상 컬럼 | 확정 필요 | 비고 |
|---|---|---|
| `property_unit.lifecycle_status` | 필요 | 임대차 상태와 별개의 업무 상태 (테이블 코멘트) |
| `property_unit.tenancy_status` | 필요 | |
| `property_listing.status` | 필요 | 상태 전이 규칙까지 |
| `property_requirement.status` | 필요 | |
| `property_requirement.demand_type` | 필요 | 코멘트가 「매수·매도·전세·월세」로 4종 시사 |
| `property_requirement.classification` | 사무소 자유 | 코멘트가 「중개사무소가 정의하는」이라 명시 |
| `property_requirement.workflow_stage` | 사무소 자유 | 코멘트가 「자유 입력」이라 명시 |
| `property_unit_party_relation.role` | 필요 | `counterparty_role` 과 반드시 같은 어휘여야 조인된다 |
| `client_interaction.counterparty_role` | 필요 | 위와 동일 |
| `party_contact.contactability_status` | 필요 | 기본값이 `UNKNOWN` 으로 DDL에 박혀 있다 |
| `party.party_type` | 필요 | 009가 공동중개 업소를 party 로 넣게 만들었다 |
| `property_listing.handover_condition` | 제안 | VARCHAR(100) 자유 텍스트라 코드값·원문 중 택 |

## 시드가 사용한 값


### `property_unit.lifecycle_status`

| 업무 표기 | 저장 값 |
|---|---|
| 정상 | `NORMAL` |
| 매물중 | `LISTED` |
| 거래완료 | `CLOSED` |
| 휴면 | `DORMANT` |

### `property_unit.tenancy_status`

| 업무 표기 | 저장 값 |
|---|---|
| 자가 | `SELF_OCCUPIED` |
| 임차 | `LEASED` |
| 공실 | `VACANT` |
| 불명 | `UNKNOWN` |

### `property_listing.status`

| 업무 표기 | 저장 값 |
|---|---|
| 접수 | `RECEIVED` |
| 광고중 | `ADVERTISING` |
| 보류 | `ON_HOLD` |
| 계약 | `CONTRACTED` |
| 종료 | `CLOSED` |

### `property_requirement.status`

| 업무 표기 | 저장 값 |
|---|---|
| 진행 | `ACTIVE` |
| 보류 | `ON_HOLD` |
| 종료 | `CLOSED` |

### `property_requirement.demand_type`

| 업무 표기 | 저장 값 |
|---|---|
| 매수 | `BUY` |
| 매도 | `SELL` |
| 전세 | `JEONSE` |
| 월세 | `MONTHLY_RENT` |

### `party.party_type`

| 업무 표기 | 저장 값 |
|---|---|
| 인물 | `PERSON` |
| 공동중개업소 | `CO_BROKER_OFFICE` |

### `property_unit_party_relation.role / client_interaction.counterparty_role`

| 업무 표기 | 저장 값 |
|---|---|
| 주 | `OWNER_SIDE` |
| 세 | `TENANT` |
| 중 | `CO_BROKER` |
| 기 | `OTHER` |
| 손 | `BUYER` |

### `party_contact.contactability_status`

| 업무 표기 | 저장 값 |
|---|---|
| 양호 | `OK` |
| 주의 | `CAUTION` |
| 불가 | `UNREACHABLE` |
| 불명 | `UNKNOWN` |
| 수신거부 | `DO_NOT_CONTACT` |

### `client_interaction.interaction_channel`

| 업무 표기 | 저장 값 |
|---|---|
| 통화 | `CALL` |
| 문자 | `SMS` |
| 방문 | `VISIT` |
| 기타 | `OTHER` |

### `client_interaction.communication_direction`

| 업무 표기 | 저장 값 |
|---|---|
| 수신 | `INBOUND` |
| 발신 | `OUTBOUND` |

### `client_interaction.interaction_result`

| 업무 표기 | 저장 값 |
|---|---|
| 성공 | `CONNECTED` |
| 부재 | `NO_ANSWER` |
| 불통 | `UNREACHABLE` |
| 기타 | `OTHER` |

### `property_listing.handover_condition`

| 업무 표기 | 저장 값 |
|---|---|
| 즉시명도 | `IMMEDIATE` |
| 잔금시명도 | `ON_SETTLEMENT` |
| 임차만기후명도 | `AFTER_TENANCY_EXPIRY` |
| 선행매수후협의 | `PENDING_PRIOR_PURCHASE` |
| 협의 | `NEGOTIABLE` |

### 자유 입력 (사무소가 정의 — 확정 대상 아님)

`property_requirement.classification` — 시드 사용값: `실입주-갈아타기`, `투자`, `신규`, `실입주-확장`, `실입주-전세만기`, `실입주-전세만기`

`property_requirement.workflow_stage` — 시드 사용값: `조건확정`, `상담중`, `상담중`, `임장예정`, `조건확정`, `보류`

## 화자 ①②③ 의 어휘가 특히 중요한 이유

002 테이블 코멘트가 못을 박았다 — *「role_index는 상담 로그 ①②③ 인물 인덱스의 기준이다」*.
즉 화자 인덱스는 로그 텍스트에서 파싱하는 값이 아니라 `property_unit_party_relation` 이 원천이고,
`client_interaction.counterparty_role` · `counterparty_index` 가 그 관계를 가리킨다.

이 시드는 그렇게 넣었다. 따라서 **`role` 어휘가 두 테이블에서 어긋나면 화자 판정이 통째로 깨진다.**
어휘 확정 시 이 두 컬럼을 반드시 같은 목록으로 묶어야 한다.

```sql
-- 화자별 최신 진술 — role/role_index 조인으로 뽑는다 (로그 파싱 없음)
SELECT r.role, r.role_index, p.name, max(ci.interaction_at) AS last_at
FROM client_interaction ci
JOIN property_unit u
  ON u.brokerage_id = ci.brokerage_id AND u.id = ci.unit_id
JOIN property_unit_party_relation r
  ON r.brokerage_id = ci.brokerage_id AND r.unit_id = ci.unit_id
 AND r.role = ci.counterparty_role AND r.role_index = ci.counterparty_index
 AND r.valid_to IS NULL
JOIN party p ON p.brokerage_id = r.brokerage_id AND p.id = r.party_id
WHERE u.custom_fields ->> 'unit_id' = 'M01' AND ci.is_voided = FALSE
GROUP BY 1, 2, 3
ORDER BY last_at DESC;
```

## 귀속되지 않은 화자

배경 로그(합성 CSV 원문)에는 관계로 확정할 수 없는 화자가 남아 있다. 구표기 `ⓐⓑ`(C-1-2)와
인덱스 공란(C-1-3)이 아직 미해결이기 때문이다. 시드는 이 로그의
`related_context.speaker_resolved` 를 `false` 로 두고, 세대별 목록을
`property_unit.custom_fields.unresolved_speakers` 에 남긴다 — 지우지 않고 드러낸다.

| 세대 | 귀속 안 된 화자 |
|---|---|
| M01 | 세②, 중ⓐ |
| M02 | 주② |
| M03 | 주③, 중③ |
| M04 | 주②, 주ⓑ |
| M05 | 중① |
| M07 | 주② |
| M08 | 세① |
| M09 | 주②, 중② |
| M10 | 주② |
| M11 | 세①, 세ⓑ, 중① |
| M12 | 중① |
| M13 | 세②, 중① |
| M14 | 주③ |
| M15 | 주③, 중② |
| M17 | 중① |
| M18 | 주② |
| M19 | 세①, 주③, 주ⓑ, 중③ |
| M20 | 주②, 중① |

