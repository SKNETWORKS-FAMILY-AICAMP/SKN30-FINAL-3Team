# Product Design QA — F1·F2·F3 코드 프로토타입

- 최종 결과: `passed`
- 기준일: 2026-08-13
- Source visual truth:
  - `../source/기존_장부_메인화면.jpeg` — 4000×2252 px
  - `../source/매물 입력.jpg` — 1782×1774 px
  - `../SCREEN_MATRIX_F1_F2_F3.md`
  - `../PENPOT_HANDOFF.md`
- Browser-rendered implementation: `http://127.0.0.1:4173/`
- Density normalization: Playwright `deviceScaleFactor: 1`; implementation은 1600×900 및 1366×768 CSS px와 동일 픽셀로 캡처. 기존 4000×2252 업무 화면은 16:9 비율을 유지해 800×450로 축소한 뒤 구현 1600×900 캡처를 800×450로 축소하여 한 캔버스에서 비교.

## Evidence

### Full-view comparison

- Grid source vs prototype: `artifacts/compare-grid-source-vs-prototype.png` — 1600×450.
- Detail source vs prototype: `artifacts/compare-detail-source-vs-prototype.png` — 1600×450.
- 1600×900 Grid: `artifacts/05-grid-1600-filtered.png`.
- 1366×768 Grid: `artifacts/12-grid-1366.png`.
- 1366×768 F3 Primary-detail: `artifacts/13-f3-1366-primary-detail.png`.

기존 화면은 직접적인 픽셀 복제 대상이 아니라 업무 밀도·전수 장부·상세 입력 구조의 기준이다. 새 구현은 PatternFly 구조와 AG Grid interaction을 사용해 정보 계층과 상태 표현을 현대화했으며, 프로젝트 전용 시각 Library가 아직 연결되지 않아 색상·radius의 픽셀 일치는 요구하지 않았다.

### Focused regions

- 닫기 세 분기: `artifacts/06-detail-close-three-way.png`.
- 불완전 저장: `artifacts/07-detail-incomplete-saved.png`.
- F2 녹음: `artifacts/08-f2-recording-focused.png`.
- F2 처리 중 닫기 경고: `artifacts/09-f2-processing-close-warning.png`.
- F2 제안 검수 6열: `artifacts/10-f2-review-focused.png`.
- 문자 copy-only: `artifacts/14-message-copy-only.png`.
- F3 실패 격리: `artifacts/15-f3-failure-isolated.png`.

중요한 Admin UI 세부가 전체 화면에서 작게 보이므로 F2와 문자 Modal을 별도 element screenshot으로 확인했다.

## Required fidelity surfaces

- Fonts/typography: 프로젝트 전용 폰트가 없으므로 `Noto Sans KR → NanumBarunGothic → OS sans` 순서로 명시했다. 상태·표·보조 설명의 계층은 분명하다. 상태막대·보조문구는 12px 이상으로 조정되어 P3 가독성 항목을 해결했다.
- Spacing/layout rhythm: 기존 장부의 고밀도 작업성을 유지했다. 40px Grid row, 좌 332px 고정 식별열, 1456px 상세 Modal, 200px F1 action rail, F3 40/60을 실측했다. 1366에서 document overflow는 없다.
- Colors/tokens: PatternFly semantic token을 사용하고 저장/AI/업무 상태를 텍스트와 별도 Badge로 구분했다. Gradient·sparkle·chatbot shell은 없다.
- Image quality/assets: 제품 사진·일러스트가 필요한 화면이 아니다. 아이콘은 PatternFly 공식 icon set만 사용했으며 handcrafted SVG/CSS art/emoji는 없다.
- Copy/content: F1/F2/F3 소유 경계, 상담 후 음성메모, 민감정보 금지, 불완전 저장, 번호 복사 종결을 앱 자체 문구로 설명한다. 실발송 CTA는 없다.

## Primary interactions tested

`artifacts/workflow-smoke.json`의 25개 assertion이 모두 통과했다.

- 7200행 Grid, 33 data columns, 40px density, pinned identity, save/AI 상태 분리.
- 다중 선택, Empty/Error/Offline 복구, 1366 overflow 없음.
- F1 상세 Modal 1개, 불완전 저장 Enabled, 작성 중 저장.
- dirty close `저장 / 저장 안 함 / 취소`; 저장 안 함은 Grid 데이터에 누출되지 않음.
- F2 녹음, 처리, 검수 6열, 처리 중 닫기 취소 경고.
- F3 40/60, 강함/약함/기각, F1 action 유지, 실패 격리.
- 문자 대상·번호·문안 전달, `번호 복사/닫기`만 노출, clipboard 결과 확인.

`artifacts/critical-boundary-smoke.json`의 5개 assertion도 모두 통과했다.

- F2 음성 초안이 dirty close policy에 포함됨.
- 저장 payload에 음성 원본·제안 상태가 포함됨.
- 개인정보 패턴 저장 Gate가 보이고 포커스됨.
- 실제 AG Grid `role=grid`에 한국어 aria-label 적용.
- 브라우저 console/page error 0건.

Build 및 런타임 검증: `npm run build`, `npm run test:sites` 4/4 통과. 큰 bundle 경고는 프로토타입 단계의 성능 P3이며 기능 차단이 아니다.

## Comparison history

### Pass 1 — blocked

- P0: F2 음성 원본을 저장하지 않고 닫을 수 있어 silent data loss.
- P1: F2 내부에서 AI 충돌 결정, 닫기 alertdialog focus leak, F3 trigger가 화면 밖 Panel로 이동하지 않음, 문자 Modal focus leak.
- P1/P2: 실제 단지 필터와 결과 건수 불일치, F2 파일 검증·민감정보 안내·정확한 처리 단계 누락, Empty/Error 직접 복구 없음, AG Grid 한국어 접근성 라벨 누락.

수정:

- F2 audio/proposals/review state를 F1 저장 payload에 포함하고 닫기 dirty 판단에 연결.
- F1-MOD-145/F1-MOD-140 상태와 data trace 추가.
- close/conflict/message focus trap·Escape·restore 수정.
- F3 open 시 scroll/focus, 자동 sequential→ready, failure isolation 유지.
- 단지 filter를 실제 query에 적용하고 결과 건수 일치.
- 파일 형식/0-byte, 미리듣기, 개인정보 금지, 정확한 STT 단계, Error/Empty action 추가. 업로드 용량 상한은 가정 대장으로 분리.
- AG Grid label/한국어 locale, 검색 focus, TextArea label, toast/error live feedback 추가.

Post-fix evidence: `06`, `08`~`15` 캡처, `workflow-smoke.json`, `critical-boundary-smoke.json`.

### Pass 2 — passed

P0/P1/P2로 분류할 수 있는 화면·핵심 흐름 문제는 남지 않았다. 1600/1366 브라우저 캡처, focused state 캡처, 30개 자동 assertion, console error 0건으로 확인했다.

## Follow-up polish (P3)

- [해결] 상태막대·보조문구를 12px 이상으로 올려 장시간 업무 가독성을 개선.
- PatternFly+AG Grid 초기 bundle을 lazy-load/code-split.
- Penpot Cloud 파일이 생성되면 프로젝트 Library token으로 임시 색상·타이포를 교체.
- 실제 NVDA/JAWS, 실제 마이크 권한/MediaRecorder, 실제 backend save failure/idempotency는 구현 단계에서 별도 통합 검증.
- 이 프로토타입은 desktop Admin 시스템 기준이며 200% 확대 시 가로 작업 공간을 보존하기 위해 Grid 내부 스크롤을 사용한다. 모바일 화면은 대상 범위가 아니다.

final result: passed


## 2026-08-13 PO 피드백 반영 검증

- 선택 0건 기본 상태와 명시적 전체 선택 해제: 통과
- 상세 헤더 음성메모 진입 → 같은 F2 Panel scroll/focus: 통과
- 직접 문자 작업 / F3 캠페인 분기 및 대상 출처 표시: 통과
- 신규 행 상세의 새 단지 인라인 추가·즉시 선택: 통과
- 가시 텍스트 11px 잔여: 0건
- 증거: `artifacts/requested-feedback-smoke.json`, `16-requested-feedback-campaign.png`

## 2026-08-13 F1 장부 배치 변경

- Source visual truth: `/tmp/codex-remote-attachments/019ff8a4-1563-71a0-ad2b-403d281e0adb/d195f8ed-e167-4983-9738-5f7c8befd67c/1-Photo-1.jpg` — 597×1280 px. 상단 134px 모바일 브라우저 chrome은 비교에서 제외하고 앱 내부의 밀도·영역 순서만 참조했다.
- Implementation evidence:
  - `artifacts/17-f1-compact-layout-1600.png` — 1600×900 CSS px / DPR 1
  - `artifacts/17-f1-compact-layout-1366.png` — 1366×768 CSS px / DPR 1
  - `artifacts/compare-f1-layout-reference-vs-prototype.png` — 참조 앱 영역과 구현을 800×900씩 정규화한 full-view 비교
  - `artifacts/f1-layout-smoke.json`
- 상태: 기본 매물장, 선택 0건.
- 변경 범위: 디자인 토큰·컴포넌트 스타일·Grid 열/행은 유지하고 배치만 변경했다.

### Full-view 및 focused 비교

- 참조처럼 좌측 지속 Navigation과 큰 Page hero를 제거하고, 첫 줄에 F1 식별·장부 전환·동호 조회·통합 검색, 둘째 줄에 장부 유형·작업·필터·상태·보조 업무를 배치했다.
- Grid는 둘째 줄 바로 아래에서 전체 폭과 남은 높이를 사용한다. 1600에서 Grid 1600×768, 1366에서 1366×636으로 실측했다.
- 둘째 제어줄의 전체 콘텐츠 폭은 2455px이지만 줄 내부 스크롤로 격리된다. 문서 폭은 각각 1600/1366과 정확히 일치한다.
- 별도 focused crop은 필요하지 않았다. 사용자가 요청한 범위가 컨트롤 세부 모양이 아닌 큰 영역 배치이며, 상단 두 줄과 Grid 시작점이 full-view 캡처에서 판별 가능하다.

### Required fidelity surfaces

- Fonts/typography: 기존 Noto Sans KR 계층과 12px 최소값 유지. 참조의 더 작은 글자 크기는 가독성 계약 때문에 복제하지 않았다.
- Spacing/layout rhythm: 참조의 핵심인 얕은 상단 도구 영역과 즉시 시작하는 전체 폭 장부를 적용. persistent side nav와 92px page heading은 제거했다.
- Colors/tokens: 기존 PatternFly/프로젝트 의미색을 그대로 유지했다. 사용자가 디자인 변경을 요청하지 않아 참조의 색상을 복제하지 않았다.
- Image quality/assets: 참조에는 앱 배치 외 재사용할 제품 이미지가 없다. 모바일 브라우저 chrome은 구현하지 않았다.
- Copy/content: 기존 F1/F2/F3 용어와 동작을 유지했다. 검색·동호 조회는 상단으로 이동했지만 의미를 변경하지 않았다.

### Comparison history

#### Layout pass 1 — blocked

- P1: 알림 toast가 새 둘째 제어줄 위에 겹쳐 선택 해제 버튼을 가림.
- P2: 기존 회귀 테스트가 삭제된 `.page-heading-meta`와 옛 `동·호 바로가기` placeholder를 참조.

수정:
- 알림 시작 위치를 두 제어줄 아래로 이동.
- 테스트 selector를 `.f1-topbar__counts`, `동·호 조회`, `조회`로 갱신.

#### Layout pass 2 — passed

- F1 배치 전용 assertion 18/18 통과.
- 기존 critical boundary, workflow, requested feedback, visual smoke 전부 통과.
- 1600×900·1366×768에서 문서 overflow 0, console/page error 0.
- 활성 소스의 11px 또는 0.6875rem 잔여 0.

final result: passed

## 2026-08-13 5차 요구사항 반영

- F1 활성 요구사항: 238건(기능 225·비기능 13). 폐기된 데이터 이관 10건은 `archive/data-migration/requirements/`에 보관.
- 폐기된 `F1-PG-130` 화면과 당시 증거는 `archive/data-migration/`로 이동.
- `F1-MOD-010`: `박이서·송경련`을 같은 임대인 역할의 `①/②`로 표시하고, 선택 즉시 로그에 자동 표기. 미선택은 `미지정`이며 1번 인물로 추정하지 않음.
- `F2-PNL-020`: 선택한 F1 상대 인덱스를 상담 로그 제안값에 동일 적용. F3 생성 로그는 요구사항·Matrix에 같은 규칙을 매핑했으며 현재 프로토타입에 없는 F3 로그 작성/정정 화면은 새로 꾸며내지 않음.
- 활성 상태: 상담 상대 미지정 / 선택·자동 표기.
- 접근성·가독성: 새 입력 모두 이름 연결, Disabled 이유 제공, 처리·오류·완료 live feedback, 1600×900·1366×768 document overflow 0, 새 화면 12px 미만 가시 텍스트 0.
- 활성 증거: `artifacts/fifth-requirements-smoke.json`, `19-fifth-requirements-person-index-1600.png`. 이관 증거는 archive에 보관.
- 전용 assertion 17/17, Sites 4/4, critical 9/9, workflow 25/25, PO feedback 13/13, F1 layout 18/18, console/page error 0.

final result: passed


## 2026-08-14 UI/UX 감사 적용 및 데이터 이관 폐기

- 장부: 제품 상태 버튼을 기본 도구막대에서 제거하고 보조 메뉴에 접었다. 연결되지 않은 실행 취소·내보내기·열 프리셋 행동을 제거했으며, 미지원 장부 탭은 실제 disabled 상태로 표시한다.
- 상세: 본문 구역 이동 navigation을 추가하고 이동 대상 제목에 포커스한다. 저장 여부를 우측 작업보다 먼저 표시하고 저장을 유일한 primary action으로 유지한다.
- F2: 제안·선택·결정 필요·반영 완료 요약을 검토 표 앞에 두고, 선택 항목 반영 CTA를 표 뒤 결정 지점에 고정했다. 선택 가능한 녹음 카드의 focus ring을 복원했다.
- F3: 추천 다음 행동과 문자 작성을 우선 노출하고, 프로토타입 상태와 나중에·관심없음·일정 검토는 disclosure 안으로 이동했다.
- 캠페인·문자: 대상 확인 → 세그먼트·문안 → 번호 복사의 3단계 진행을 표시하고, 문자 작업은 확정 인원·출처·문안을 먼저 읽도록 대상과 번호 목록을 접었다.
- 반응형·가독성: 전역 1180px 최소 너비를 제거했다. 1600×900과 1366×768에서 document overflow 0, 상세·F2·F3·문자·캠페인 가시 텍스트 12px 미만 0을 확인했다.
- 데이터 이관: `F1-PG-130`, `F1-NF-10`, `F1-MG-01~09`, 구현, 캡처, 원래 smoke 결과를 `archive/data-migration/`으로 이동하고 활성 진입·Screen Matrix·요구사항에서 제거했다. 활성 화면 수는 Page 17 / Panel 11 / Modal 18 / 총 46이다.
- 자동 검증: UI/UX 전용 23/23, critical boundary 9/9, workflow 25/25, 요청 피드백 13/13, Sites 4/4 통과. console/page error 0.
- 육안 증거: `21-uiux-ledger-1600.png`, `22-uiux-ledger-1366.png`, `23-uiux-detail-1366.png`, `24-uiux-f2-review-1366.png`, `25-uiux-f3-1366.png`, `26-uiux-message-1366.png`, `27-uiux-campaign-1366.png`.

final result: passed
