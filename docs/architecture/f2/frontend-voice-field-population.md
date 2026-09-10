---
status: 구현됨
updated: 2026-09-04
---

# F2 음성 데이터의 매물장·구입장 필드 반영 흐름

## 문서 안내

- **이 문서가 답하는 질문:** 프론트엔드에서 F2 음성메모를 실행했을 때 분석 결과가 어떻게 매물장 또는 구입장 필드에 들어가는가?
- **관련 요구사항:** [F2 정의와 흐름](../../requirements/f2/overview-and-flow.md) · [장부별 AI 채우기 필드](../../requirements/f2/fields.md) · [제안값 검토·저장](../../requirements/f2/review-and-save.md)
- **관련 프론트엔드 결정:** [ADR-006: 신규 음성메모의 장부 판정](../../../.agents/skills/frontend/references/decisions/ADR-006-home-voice-intake.md)
- **기준 코드:** `frontend/src/features/VoiceMemoModal.jsx` · `frontend/src/features/f2/api/f2Api.ts` · `frontend/src/AppShell.jsx`
- **이 문서가 소유하지 않는 상세:** STT·LLM 내부 처리, Backend API 계약, 장부 DB 스키마, 요구사항 필드 정의

## 핵심 요약

F2는 음성에서 추출한 값을 장부에 즉시 저장하지 않는다. 프론트엔드는 음성 파일과 현재 장부값을 F2 분석 API에 보내고, 서버가 반환한 구조화 제안을 화면 필드 키로 변환한다. 사용자가 검토표에서 선택한 제안만 상세 화면의 임시 작성 상태(`draft`)에 반영하며, 상세 화면에서 별도로 `저장`을 눌러야 장부 API를 통해 영구 저장된다.

```text
음성 파일 선택
→ F2 분석 API 호출
→ 상담 유형·필드 제안 수신
→ 매물장/구입장 결정
→ 사용자가 제안 선택
→ 상세 화면 draft에 반영
→ 사용자가 저장
→ 장부 API에 영구 저장
```

## 1. F2 진입 경로

### 신규 음성메모 접수

홈 또는 상단바의 `음성메모 입력`에서 시작한다. 이 경로는 특정 장부를 미리 선택하지 않으며, 분석된 상담 유형이 새 행을 만들 장부를 결정한다.

- 홈 진입: `frontend/src/features/HomeScreen.tsx`
- 상단바 진입: `frontend/src/AppShell.jsx`
- 모달 호출: `VoiceMemoModal`에 `ledgerType="auto"` 전달

### 기존 매물장 세대에 반영

매물장 상세의 `음성 메모 입력` 또는 한 세대를 선택한 뒤 `선택 세대 음성메모`를 실행한다. 대상이 이미 정해졌으므로 장부를 다시 판정하지 않고 `property` 기준으로 분석한다.

### 구입장 상세에 반영

`BuyerDetailWorkspace`도 `ledgerType="buyer"`인 `VoiceMemoModal`과 반영 함수를 가지고 있다. 다만 현재 화면에는 기존 구입장 상세에서 이 모달을 다시 여는 버튼이 노출되어 있지 않다. 신규 매수문의 접수로 구입장 상세가 열릴 때는 이미 분석한 값이 채워진 상태로 진입한다.

## 2. 파일 검증과 분석 요청

`VoiceMemoModal`은 분석 전에 다음 조건을 검사한다.

- 개인정보 주의 문구 확인
- 허용 형식: WAV, MP3, M4A
- 빈 파일 거부
- 25MB 초과 파일 거부
- 파일 재생·교체 및 진행 중 요청 취소

`분석 시작`을 누르면 `startAnalysis`가 실행된다. 일반 상세 경로는 `analyzeVoiceMemo`, 신규 접수 경로는 `analyzeNewIntake`를 호출한다.

`analyzeVoiceMemo`는 `POST /f2/analyses`에 다음 `multipart/form-data`를 보낸다.

| 필드 | 내용 |
|---|---|
| `audio` | 사용자가 선택한 음성 파일 |
| `ledger_type` | `매물장` 또는 `구입장` |
| `current_fields` | 현재 상세 화면 값을 서버 필드명 기준 JSON으로 변환한 값 |
| `privacy_confirmed` | 주의 문구 확인 여부. 분석 요청 시 `true` |

브라우저는 STT나 LLM 추출을 직접 수행하지 않는다. 프론트엔드는 하나의 분석 API를 호출하고 진행·성공·실패 UI와 취소를 관리한다.

## 3. 신규 접수의 장부 판정

장부가 정해지지 않은 신규 접수는 매물장을 기준 장부로 먼저 분석한다. 이후 `routeConsultation`이 상담 유형을 장부로 바꾼다.

| 상담 유형 | 판정 장부 | 처리 |
|---|---|---|
| 매도의뢰·매도문의 | 매물장 | 첫 분석 결과 사용 |
| 매수문의·매수의뢰 | 구입장 | 같은 음성을 구입장 기준으로 한 번 더 분석 |
| 공동중개·단순문의 등 | 판정 불가 | 매물장을 기본 장부로 사용하고 상담 로그 중심으로 검토 |

매수문의에서 요청을 두 번 보내는 이유는 매물장 기준 분석이 장부 불일치로 판정되면 구입장 필드 제안을 받을 수 없기 때문이다.

## 4. 분석 응답을 화면 제안으로 변환

프론트엔드는 분석 응답에서 다음 값을 사용한다.

- `consultation_type`: 상담 유형
- `ledger_mismatch`: 현재 장부와 상담 유형의 불일치 여부
- `proposals`: 필드별 현재값·제안값·근거·상태·기본 선택 여부
- `consultation_log_draft`: 상담 로그 초안
- `uncertainties`: 추가 확인이 필요한 내용
- `privacy_confirmed_at`: 개인정보 주의 확인 시각

`decodeAnalysis`는 서버의 `field_name`을 React 상세 화면에서 사용하는 `fieldKey`로 변환한다. 등록되지 않은 서버 필드는 검토표에는 표시되지만 `fieldKey`가 `null`이므로 반영 체크박스가 비활성화된다.

### 매물장 필드 매핑

| 서버 필드명 | 화면 표시 | React 필드 키 |
|---|---|---|
| 단지 | 단지 | `complex` |
| 평형 | 평형 | `area` |
| 동 | 동 | `building` |
| 호 | 호 | `unit` |
| 타입 | 거래 유형 | `listingType` |
| 방향 | 방향 | `direction` |
| 현상태 | 현 상태 | `householdState` |
| 현재 보증금 | 현재 보증금 | `deposit` |
| 현재 차임 | 현재 차임 | `rent` |
| 만기일 | 계약 만기일 | `expiry` |
| 매매가 | 매매가 | `price` |
| 전세보증금 | 전세보증금 | `deposit` |
| 월세 보증금 | 월세 보증금 | `deposit` |
| 월세 차임 | 월세 차임 | `rent` |
| 명도 조건 | 명도 조건 | `clearance` |
| 임대인 | 임대인 | `owner` |
| 임대인 전화 | 임대인 전화 | `phone` |
| 임차인 | 임차인 | `tenant` |
| 담당자 | 담당자 | `assignee` |
| 비고 | 비고 | `memo` |
| 상담 로그 초안 | 상담 로그 | `log` |

### 구입장 필드 매핑

| 서버 필드명 | 화면 표시 | React 필드 키 |
|---|---|---|
| 접수일 | 접수일 | `date` |
| 거래 구분 | 거래 구분 | `category` |
| 희망 단지·희망 지역 | 희망 단지·지역 | `complex` |
| 희망 평형 | 희망 평형 | `area` |
| 금액 원문 | 금액 조건 | `budget` |
| 이사일 원문 | 이사일 | `moveDate` |
| 구입자 이름·구입자 별칭 | 손님 이름·별칭 | `buyer` |
| 전화번호 | 전화번호 | `phone` |
| 관련 중개업소 | 관련 부동산 | `brokerage` |
| 진행단계 | 진행 단계 | `stage` |
| 완료 여부 | 완료 여부 | `completion` |
| 담당자 | 담당자 | `assignee` |
| 분류 | 분류 | `classification` |
| 비고 | 비고 | `memo` |
| 상담 로그 초안 | 상담 로그 | `content` |

## 5. 검토표와 선택 항목 반영

분석이 성공하면 `VoiceMemoModal`은 각 제안을 다음 열로 보여 준다.

- 반영 체크박스
- 필드명
- 현재값
- AI 제안값
- 상태
- 근거 문장

서버가 `selected_by_default: true`로 준 매핑 가능한 제안은 기본 선택된다. 기존 값과 다른 제안은 일반적으로 `변경` 상태로 표시되고 기본 선택되지 않는다.

사용자가 `선택 항목 반영`을 누르면 `applySelected`가 선택된 제안으로 patch 객체를 만든다.

```js
{
  complex: "래미안",
  building: "101",
  unit: "1203",
  listingType: "매매",
  price: "15억",
  owner: "홍길동",
  log: "[26-09-04 14:30]매도의뢰 상담 요약..."
}
```

상담 로그는 기존 내용을 덮어쓰지 않는다. `appendVoiceMemoToLog`가 반영 시각을 `[YY-MM-DD HH:MM]` 형식으로 붙여 `log` 또는 `content` 뒤에 추가한다.

## 6. patch가 상세 화면에 들어가는 방식

### 신규 접수

`AppShell.applyIntake`가 분석 결과의 `ledgerType`에 맞는 장부 컬렉션을 고른다.

1. `propertyLedger.addDraft()` 또는 `buyerLedger.addDraft()`로 빈 임시 행을 만든다.
2. 빈 행, 선택한 patch, F2 검토 상태를 합친다.
3. 장부 컬렉션의 해당 행을 갱신한다.
4. 매물장 또는 구입장 화면으로 이동한다.
5. 값이 채워진 상세 화면을 연다.

이 과정에서는 서버 장부에 저장하지 않는다.

### 기존 매물장 상세

`DetailWorkspace.handleF2Apply`가 patch를 현재 `draft`에 병합한다. 이미 값이 있는 필드를 선택했다면 `음성 메모 값으로 대체`와 `기존 값 유지` 중 하나를 다시 고르게 한다. 기존 값 유지를 선택해도 원래 빈 칸에 적용한 제안은 유지한다.

매매가의 공통 `price` 값은 현재 거래 유형을 기준으로 `salePrice`, `leaseDeposit` 또는 `rentCondition`에 함께 복사된다.

### 구입장 상세

`BuyerDetailWorkspace.handleF2Apply`가 현재 `draft`에 patch와 F2 검토 상태를 병합한다. 이 단계의 값은 사용자가 직접 다시 수정할 수 있다.

## 7. 최종 장부 저장

상세 화면에서 `저장`을 눌러야 F2로 채운 값이 영구 저장된다. `AppShell.saveDetail`은 행 종류에 따라 다음 훅을 호출한다.

- 매물장: `propertyLedger.saveRow`
  - 세대 생성 또는 수정
  - 값이 있으면 매물 생성 또는 수정
  - 변경된 상담 로그 추가
- 구입장: `buyerLedger.saveRow`
  - 구입 조건 생성 또는 수정
  - 변경된 상담 로그 추가

저장에 성공하면 서버가 반환한 ID와 `row_version`을 화면 행에 반영한다. 실패하면 상세의 작성값은 유지하고 오류를 표시한다.

## 8. 현재 구현상의 제약과 주의점

### 여러 서버 필드가 같은 매물장 키를 사용한다

`현재 보증금`, `전세보증금`, `월세 보증금`은 모두 `deposit`으로 연결되고, `현재 차임`과 `월세 차임`은 모두 `rent`로 연결된다. 같은 키의 제안을 동시에 선택하면 응답 배열에서 뒤에 있는 제안이 앞의 값을 덮는다.

### 신규 매물장의 단지 ID

F2 제안은 단지명인 `complex`를 채우지만 신규 세대 저장에는 서버의 `complexId`가 필요하다. 분석 후 사용자가 등록된 단지를 선택하지 않으면 실제 저장이 거절될 수 있다.

### 신규 구입장의 인물 ID

신규 구입 조건 저장에는 `partyId`가 필요하다. 현재 계약에는 인물 생성 API가 없으므로 F2 신규 접수로 만든 손님 행은 화면에 채워지더라도 서버 저장이 제한될 수 있다.

### 기존 구입장 상세의 F2 재실행 진입점

구입장 상세 컴포넌트에는 F2 모달과 반영 로직이 있지만 현재 사용자에게 보이는 `음성 메모 입력` 버튼은 없다. 기존 구입장 행에서 F2를 다시 실행하는 사용자 경로는 별도 보완이 필요하다.

## 9. 주요 구현 위치

| 책임 | 파일·함수 |
|---|---|
| F2 모달 상태와 검토 UI | `frontend/src/features/VoiceMemoModal.jsx` |
| 분석 시작 | `VoiceMemoModal.startAnalysis` |
| 선택 제안 patch 생성 | `VoiceMemoModal.applySelected` |
| multipart 분석 요청 | `frontend/src/features/f2/api/f2Api.ts`의 `analyzeVoiceMemo` |
| 신규 접수 장부 판정·재분석 | `analyzeNewIntake` |
| 상담 유형→장부 변환 | `frontend/src/features/f2/model/consultationRouting.ts` |
| 상담 로그 append | `frontend/src/features/f2/model/consultationLog.ts` |
| 신규 행 생성·상세 열기 | `frontend/src/AppShell.jsx`의 `applyIntake` |
| 매물장 상세 반영 | `frontend/src/features/DetailWorkspace.jsx`의 `handleF2Apply` |
| 구입장 상세 반영 | `frontend/src/features/BuyerDetailWorkspace.jsx`의 `handleF2Apply` |
| 매물장 영구 저장 | `frontend/src/features/ledger/hooks/usePropertyLedger.ts`의 `saveRow` |
| 구입장 영구 저장 | `frontend/src/features/ledger/hooks/useBuyerLedger.ts`의 `saveRow` |
