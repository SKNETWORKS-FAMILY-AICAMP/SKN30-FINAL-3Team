---
name: frontend
description: "`frontend/`의 React 사용자 인터페이스를 개발하거나 프론트엔드 환경, 화면, 상태, 접근성, API 연동 및 빌드 방식을 변경할 때 사용한다. 프로젝트 공통 지식은 project-wiki와 함께 확인한다."
---

# 프론트엔드 스킬 초안

이 스킬의 구조와 개발 방식은 절대 규칙이 아니라 기본 권장안이다. 작업 규모와 위험에 맞는 가장 단순한 설계를 우선하고, 권장안에서 벗어난 이유와 검증 방법을 PR에 남긴다. 장기 유지할 모듈 내부 결정은 `.agents/skills/frontend/references/decisions/`에, 프로젝트 공통 결정·계약·정책은 project-wiki에 기록한다. 저장소 지침과 승인된 프로젝트·모듈 결정은 이 권장안보다 우선한다.

- 작업 위치: `frontend/`
- 현재 기술 방향: React
- 책임: 화면, 사용자 상호작용, 클라이언트 상태, API 연동
- 제외: 서버 비즈니스 로직, 에이전트 그래프, 데이터 파이프라인, IaC
- 프론트엔드 실행환경과 의존성은 모듈 내부에서 독립 관리
- API 계약은 project-wiki의 `contracts/api.md` 확인
- 개인정보가 화면, 브라우저 저장소, 분석 도구 또는 로그에 노출되면 개인정보 정책 확인
- 내부 폴더 구조, 상태 관리, UI 라이브러리, 테스트, 린트, 빌드·배포 규칙은 보류
- 작업 전 project-wiki와 존재하는 경우 `.agents/skills/frontend/references/index.md`에서 관련 결정만 확인
