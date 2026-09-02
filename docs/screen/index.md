---
status: 결정
updated: 2026-08-14
---

# 화면 문서 인덱스

현재 작업과 직접 관련된 문서만 읽는다. 각 문서의 상태를 확인하고, `검토안`을 승인된 요구사항이나 결정으로 표현하지 않는다.

| 문서 | 읽는 조건 |
|---|---|
| [Screen Matrix](SCREEN_MATRIX_F1_F2_F3.md) | Screen ID, 화면 소유, 주요 상태, 요구사항 연결 또는 화면 이동을 확인할 때 |
| [화면구조 분석](화면구조_분석_F1_F2_F3.md) | IA, Page·Panel·Modal 경계, 화면 구성 또는 기능 간 결합 관계를 확인할 때 |
| [랜딩 How it works 생성 프롬프트](../../site/prompts/how-it-works.md) | 소개용 랜딩 페이지를 UI 생성 AI로 만들거나, 대외 설명 문구가 F1·F2·F3 동작과 어긋나지 않는지 확인할 때. 실제 페이지 파일은 [site/](../../site/)에 있다 |

## 적용 기준

- 기능 범위, 사용자 동작, 수용 기준과 요구사항 ID는 [요구사항 인덱스](../requirements/index.md)가 연결한 문서를 기준으로 한다.
- 시각 디자인, 컴포넌트와 접근성은 [Frontend Design Guide](../../.agents/skills/frontend/references/design/index.md)를 기준으로 한다.
- 화면 문서는 요구사항을 UI 구조로 해석하기 위한 참고자료이며, 문서에 표시된 상태가 `검토안`이면 확정 결정으로 간주하지 않는다.
- 화면 문서와 요구사항이 충돌하면 요구사항을 따르고, 시각 디자인·컴포넌트·접근성 규칙이 충돌하면 Frontend Design Guide를 따른다.
