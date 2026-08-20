# 「학습한 ML / DL 모델」 템플릿 계약

## 1. 용도와 상태

- 이 문서는 새 **Field Proposal Review Risk Model 설명서**를 만들 때 적용할 구조·시각 계약이다.
- 원본에 적힌 LightFM·레시피 추천 내용은 참고 지시가 아니며 재사용하지 않는다. 표지, 2쪽 요약 구성, 제목 계층, 목록과 표의 시각 체계만 재사용한다.
- 원본은 읽기 전용으로 분석했으며 수정하거나 재저장하지 않았다.
- 렌더 상태: **미완료**. 번들 Windows Python은 현재 WSL에서 실행되지 않고 Linux Python에는 `pdf2image`/Pillow가 없으며, `soffice`/LibreOffice와 `pdftoppm`도 없다. 아래 2쪽 구성은 명시적 페이지 나눔 1개에서 추정했으며 시각 검증된 결과가 아니다.
- 구조 대체 검증: ZIP 무결성, 필수 OOXML 파트, 섹션, 페이지 나눔, 스타일, Heading 1, 번호·글머리표, 표 기하, DrawingML, 관계, 헤더/푸터와 패키지 해시를 `structure_audit.json`으로 검사했다.

## 2. 참조와 증거

- 원본: `/mnt/c/Users/playdata2/Downloads/[데이터 전처리] 학습한 ML_DL 모델_27기_1팀.docx`
- 원본 크기: 774,875 bytes
- 원본 SHA-256: `6c7b57cf9a391c3f428917c1ed306b67b7fceb7aecf7180796f05943526321ae`
- OOXML 파트: 23개
- 구조 증거: `ml/field_proposal_reliability/qa/template-analysis/trained_model_report/structure_audit.json`
- 렌더 출력 예정 위치: `ml/field_proposal_reliability/qa/template-analysis/trained_model_report/render/` (현재 PNG 없음)
- 원본에는 `docProps/app.xml`이 없어 애플리케이션이 기록한 페이지 수는 없다.

## 3. 페이지 시스템

- 섹션: 1개, A4 세로 `11909 × 16834` DXA(약 210.0×297.0 mm).
- 여백: 위 `1275` DXA(22.5 mm), 아래 `1559` DXA(27.5 mm), 좌·우 각 `992` DXA(17.5 mm).
- 본문 가용 폭: `9925` DXA(175.1 mm).
- 헤더·푸터 거리: 각 `720` DXA(12.7 mm).
- 첫 페이지 구분(`w:titlePg`)이 켜져 있다. default/first/even 헤더와 푸터 파트는 모두 존재하지만 빈 문단만 포함하고, even/odd 분리 옵션은 꺼져 있다.
- 페이지 번호 시작값은 0이지만 표시 필드가 없다.

### 페이지 패턴

1. **표지**: 배경 그래픽, 두 줄 제목 표, 4×2 메타데이터 표.
2. **모델 요약 본문**: 1×1 제목 밴드 뒤에 10개 번호 섹션, 두 개의 데이터 표, 글머리표·절차 목록. 원본은 별도 후속 페이지 나눔이 없으므로 2쪽에 모두 들어가는 압축형 설명서다.

새 설명서도 원칙적으로 2쪽을 목표로 한다. 다만 실제 지표표나 한계 문구가 잘리면 3쪽으로 늘리고 글자 크기를 10 pt 아래로 줄이지 않는다.

## 4. 시각·타이포그래피 계약

### 색상과 글꼴

- 주 강조색 `#0B57D0`, 보조 강조색 `#33BCB1`, 표 헤더 `#CFE2F3`, 표 테두리 `#CCCCCC`, 본문 `#000000`.
- 문서 기본값은 Arial 11 pt 굵게, 한국어이지만 실제 보이는 런은 대부분 **맑은 고딕 11 pt**를 직접 지정한다. 새 문서는 맑은 고딕을 명시해 렌더러별 기본 글꼴 차이를 차단한다.
- 기본 줄 간격 `276`(자동), 약 1.15줄.
- 표지·본문 상단 대제목: 맑은 고딕 20 pt.
- 표지 메타데이터: 맑은 고딕 12 pt.
- 본문 Heading 1과 본문·표: 11 pt. 원본 Heading 1 스타일 정의 자체는 20 pt이지만 각 제목 런이 11 pt로 직접 덮어쓴다. 시각 충실도와 2쪽 밀도를 위해 새 문서에서도 최종 렌더 크기는 11 pt 굵게로 맞춘다.
- Heading 1 스타일: 앞 `400`, 뒤 `120` DXA, `keepNext`, `keepLines`. 제목은 본문 흐름에서 떨어지지 않게 다음 항목 또는 표와 함께 유지한다.

### 번호와 목록

- 섹션 제목은 텍스트에 `1.`~`10.`을 직접 포함하고 실제 `Heading1` 스타일을 사용한다.
- `numId=1`: 모델 개요의 ● 글머리표.
- `numId=2`: Target 정의의 ● 글머리표.
- `numId=3`: Feature 목록의 ● 글머리표.
- `numId=4`: 학습·평가 과정의 십진수 단계.
- `numId=5`: 최종 적용 전략의 ● 글머리표.
- `numId=6`: 한계·향후 개선의 ● 글머리표.
- level 0은 왼쪽 `720`, 내어쓰기 `360` DXA. 글머리표 2단계는 `o`, 3단계 이후는 `▪`를 사용한다.
- `word/fonts/NotoSansSymbols-regular.ttf`와 `NotoSansSymbols-bold.ttf`가 목록 기호 지원용으로 내장되어 있다. 원본 기반 편집에서는 번호 정의와 함께 보존한다.

## 5. 반복 구성요소

### 표지 배경

- 두 문서가 동일한 디자인 자산을 공유한다.
- `word/media/image2.png`: 1692×1452 RGBA, SHA-256 `870dde32a180bc9498566da821287becb142cc047bf2f9bd4278b5eb39a3869a`.
- 페이지 기준 x `-363371`, y `-57850` EMU, 크기 `8453438 × 7249802` EMU(약 234.8×201.4 mm), `behindDoc=1`, `wrapNone`.
- `word/media/image1.png`: 1×1 투명 이미지, SHA-256 `18d840af2c50eff9a5241d4b50833a596e6b71af0cee87cf2b3435345f2f7aba`, 동일 위치의 보조 anchor.
- 두 drawing의 `docPr` ID가 모두 1이고 대체 텍스트가 없는 것은 원본 결함이다. 새 문서는 고유 ID와 장식 이미지 대체 텍스트 정책을 사용한다.

### 표지 제목 표

- locator: `word/document.xml/body/tbl[1]`.
- 1열, 폭 `9925` DXA, 고정 레이아웃, 왼쪽 정렬, 행 최소 높이 `1297` DXA.
- 셀 위쪽 2.25 pt `#0B57D0`, 오른쪽 2.25 pt `#33BCB1`; 왼쪽·아래 없음. 셀 패딩 `100` DXA.
- 과정·기수·팀 / 문서 제목의 두 문단, 각각 20 pt.

### 표지 메타데이터 표

- locator: `word/document.xml/body/tbl[4]`.
- 4행×2열, 중앙 배치, 폭 `9000`, 열 `2250/6750` DXA.
- 행: 산출물 단계, 제출 일자, 깃허브 경로, 작성 팀원.
- 외곽 상·하단 2.25 pt 파랑, 내부 선 0.5 pt 파랑, 바깥 좌·우 없음. 패딩 `340` DXA.
- 라벨 가운데, 값 왼쪽, 값 셀은 세로 가운데.

### 본문 제목 밴드

- locator: `word/document.xml/body/tbl[7]`.
- 1열, 폭 `9930` DXA, 고정 레이아웃.
- 표지 제목 표와 같은 상단 파랑·오른쪽 청록 테두리, 맑은 고딕 20 pt 굵게.

### 입력·출력 표

- locator: `word/document.xml/body/tbl[17]`.
- 5행×3열, 폭 `9000`, 열 `724/3051/5225` DXA.
- 첫 행 `#CFE2F3`; 모든 셀 1 pt `#CCCCCC`; 패딩 `100` DXA.
- 헤더와 첫 열은 가운데, 설명 열은 왼쪽. 글자 11 pt.
- 새 문서에서도 `구분 / 항목 / 설명` 3열을 유지하고, 모델 Feature 입력과 `needs_review` 출력까지 5~7행 범위로 확장 가능하다.

### 평가 표

- locator: `word/document.xml/body/tbl[51]`.
- 7행×4열, 폭 `9000`, 열 `3156/2297/2122/1425` DXA.
- 첫 행 `#CFE2F3`; 모든 셀 1 pt `#CCCCCC`; 패딩 `100` DXA; 글자 11 pt.
- 새 문서는 `평가 지표 / 측정 대상 / 실제 결과 / 비고`로 바꾸고 Accuracy, Precision, Recall, F1, Train/Test gap을 수록한다. 성능 수치는 결과 JSON에서만 가져온다.
- 원본은 모든 행에 `w:tblHeader`와 `w:cantSplit`을 기록했다. 새 문서에서는 첫 행만 반복 헤더로 지정하고, 고정 행 높이는 사용하지 않는다.

## 6. 콘텐츠 슬롯 지도

| 안정 locator | 의미 | 새 문서 허용 내용 | 용량·형식 | 처리 |
|---|---|---|---|---|
| `body/tbl[1]/tr[0]/tc[0]/p[0]` | 과정·기수·팀 | `SK 네트웍스 Family AI 30기 : 3팀` | 1줄, 20 pt | rewrite |
| `body/tbl[1]/tr[0]/tc[0]/p[1]` | 표지 문서명 | `학습한 ML / DL 모델` | 1줄, 20 pt | rewrite |
| `body/tbl[4]/tr[0..3]/tc[0]` | 메타 라벨 | 원본 4개 라벨 | 고정 | preserve |
| `body/tbl[4]/tr[0..3]/tc[1]` | 메타 값 | 단계, 실제 제출일, 현재 origin, `3팀 전체` | 셀당 1문단 | rewrite |
| `body/tbl[7]/tr[0]/tc[0]` | 본문 대제목 | `학습한 ML / DL 모델 (Trained ML / DL Model)` | 1줄 | preserve/rewrite 팀 표기만 |
| `body/p[8]`~`body/p[13]` | 1. 모델 개요 | 모델명, 목적, 입력, 출력, 적용 대상과 synthetic PoC 표시 | 제목+5개 짧은 정의 | rewrite |
| `body/p[14]`~`body/p[15]` | 2. 모델 구조 | 데이터 생성→split→전처리→후보 모델→평가→선정→저장 | 1줄 또는 2줄 파이프라인 | rewrite |
| `body/p[16]`~`body/tbl[17]` | 3. 입력 / 출력 정의 | 7개 입력 Feature와 Target/예측 결과 | 5~7행 3열 표 | rewrite |
| `body/p[18]`~`body/p[21]` | 4. Target 정의 | `needs_review` 0/1, positive class, 대리 라벨 생성 한계 | 3~5개 글머리표 | rewrite |
| `body/p[22]`~`body/p[30]` | 5. Feature | field_type, confidence, evidence_length, mention_count, conflict, negation, parse_success | 최대 8개 글머리표 | rewrite |
| `body/p[33]`~`body/p[34]` | 6. 사용 프레임워크 | Python, pandas, NumPy, scikit-learn, Matplotlib, joblib, Colab | 1~2줄 | rewrite |
| `body/p[37]`~`body/p[47]` | 7. 학습 및 평가 과정 | 데이터 파생부터 저장·재로딩 확인까지 | 8~11개 실제 번호 단계 | rewrite |
| `body/p[50]`~`body/tbl[51]` | 8. 모델 평가 | 최종 선택 모델의 실제 Test 지표와 후보 비교 요약 | 5~7행 4열 표 | rewrite |
| `body/p[53]`~`body/p[58]` | 9. 최종 적용 전략 | 최종 모델명, 선택 이유, joblib 입력 계약, 서비스 미연동, 향후 실제 피드백 전환 | 최대 5개 글머리표 | rewrite |
| `body/p[60]`~`body/p[65]` | 10. 한계 및 향후 개선 | 합성 파생·대리 라벨, 소규모 데이터, 분포 차이, PoC, 실제 데이터 재학습 | 정확히 5개 짧은 글머리표 권장 | rewrite |
| `word/header*.xml`, `word/footer*.xml` | 페이지 장식 | 없음 | 빈 상태 | preserve |

## 7. 패키지 보존 계약

- `word/document.xml` SHA-256 `202998b5c20dd260ee2780926ea0586e98c6008ffb873d5581ae3714400c3927`: 위 콘텐츠 슬롯만 재작성.
- `word/styles.xml` SHA-256 `9d4968e5b8973535e3468bf002a8fe5cb63c86e4fc16c1e06a3f052e4502d097`: Heading·표 시각 정본.
- `word/numbering.xml` SHA-256 `5f1c05891c45a7b39de892e21054099ac62a13cc2370ae38fc98a6af4af8129b`: 6개 목록 정의의 정본.
- `word/media/image2.png`, `word/media/image1.png`: 표지 디자인 자산.
- `word/fonts/NotoSansSymbols-regular.ttf`, `word/fonts/NotoSansSymbols-bold.ttf`: 글머리표 기호용 내장 글꼴. 원본 기반 편집 시 보존.
- `word/theme/theme1.xml`, `word/settings.xml`, `[Content_Types].xml`, 모든 `.rels`: 관계·테마 기반 구조. 연결된 자산을 수정할 때만 함께 갱신한다.
- `customXML/item1.xml`, `itemProps1.xml`: 의미가 불명확한 Google 변환 데이터. 원본 기반 편집 시 불투명 보존, 새 문서 생성 시 복사하지 않는다.
- 전체 파트별 크기·SHA-256·보존 분류는 `structure_audit.json`의 `package` 배열이 정본이다.

## 8. 구조 QA와 충실도 게이트

- ZIP CRC 검사와 필수 파트 존재 검사 통과.
- 섹션 1개, 명시적 페이지 나눔 1개, 표 5개, DrawingML 2개 확인.
- 콘텐츠 컨트롤, 하이퍼링크, 필드, 책갈피, 주석, 각주, 미주, 추적 변경은 없다.
- 원본 drawing의 중복 `docPr` ID와 대체 텍스트 부재는 새 문서에서 수정할 구조적 결함이다.
- 최종 생성물의 필수 게이트:
  1. A4·여백·표지 배경과 파랑/청록 제목 테두리가 원본 수치와 일치한다.
  2. 본문 대제목과 1~10 Heading 1 계층이 존재한다.
  3. 글머리표와 절차는 진짜 Word 번호 정의이며 수동 기호 텍스트를 쓰지 않는다.
  4. 두 데이터 표의 `tblW`, `tblGrid`, 모든 `tcW`가 일치하고 첫 행만 연한 파랑이다.
  5. 표는 고정 행 높이를 쓰지 않으며 11 pt 글자가 잘리거나 경계에 붙지 않는다.
  6. 실제 지표와 최종 모델명이 `metrics.json`, `model_comparison.csv`, metadata와 일치한다.
  7. 실제 사용자 데이터나 실서비스 검증으로 오해할 표현이 없고 합성 파생·대리 라벨 PoC 한계를 포함한다.
  8. 원본과 최종 DOCX를 모두 PNG로 렌더하고 각 페이지를 100%로 검사한다.
- 현재는 8번 시각 게이트를 수행할 수 없었다. 후속 제작 환경에서 LibreOffice가 준비되면 2쪽 밀도, 표 잘림과 제목 간격을 우선 확인한다.
