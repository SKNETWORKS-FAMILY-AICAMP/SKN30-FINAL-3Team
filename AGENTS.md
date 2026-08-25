# 저장소 에이전트 지침

## 프로젝트 원칙

- 현재 확정되지 않은 기능 기획을 사실이나 승인된 요구사항으로 가정하지 않는다.
- 루트 모듈은 `frontend/`, `backend/`, `ai/`, `data/`, `infra/`다.
- 모듈 내부 상세 구조는 아직 확정하지 않는다.

## 프로젝트 위키 사용

프로젝트 목표, 요구사항, 공통 아키텍처, 계약, 개인정보, 개발환경, Git 정책 또는 모듈 간 결정을 확인·변경할 때 `.agents/skills/project-wiki/SKILL.md`를 사용한다. 모듈 내부 결정은 해당 모듈 스킬의 `references/`에서 관리한다.

작업 전 다음을 수행한다.

1. project-wiki의 `references/index.md`를 읽는다.
2. 현재 작업과 직접 관련된 문서만 읽는다.
3. 프로젝트 아키텍처나 정책을 변경하기 전에 project-wiki 결정 인덱스와 관련 ADR을 확인한다.
4. 모듈 내부 구조나 개발 방식을 변경하기 전에 해당 모듈의 references와 결정 인덱스를 확인한다.
5. 미확정 사항에 의존하면 소유 범위의 `open-questions.md`를 확인한다.

사용자 요청이나 구현을 통해 영구적인 지식이 생기면 프로젝트 공통 내용은 project-wiki에, 모듈 내부 내용은 해당 모듈 references에 같은 브랜치에서 갱신한다. 임시 디버깅 정보와 추측은 기록하지 않는다.

## 산출물 관리

강사 제출용 산출물을 등록·작성·대조·검증하거나 Google Drive·관리 시트에 배포할 때 `.agents/skills/deliverables/SKILL.md`를 사용한다. 대상 선택, 한 문서 작업, WBS·4주차 경계, 제출 상태 확인과 외부 쓰기 승인에 관한 상세 규칙은 해당 스킬을 정본으로 따른다.

## 모듈 스킬 선택

| 작업 경로 또는 책임 | 함께 사용할 스킬 |
|---|---|
| `frontend/` 또는 React UI | `.agents/skills/frontend/SKILL.md` |
| `backend/` 또는 API·배치·이벤트 서버 | `.agents/skills/backend/SKILL.md` |
| `ai/` 또는 멀티에이전트·LangGraph | `.agents/skills/ai/SKILL.md` |
| `data/` 또는 데이터 수집·가공 | `.agents/skills/data/SKILL.md` |
| `infra/` 또는 AWS·RunPod·IaC | `.agents/skills/infra/SKILL.md` |

여러 모듈을 변경하면 관련 스킬을 모두 사용한다. 모듈 스킬의 구조와 개발 방식은 기본 권장안이며 작업 규모와 위험에 맞게 조정한다. 저장소 지침, 승인된 프로젝트·모듈 결정과 공통 계약·정책이 스킬 권장안보다 우선한다.

## 작업 경계

- 사람용 기획서, WBS, 스프레드시트를 에이전트 작업마다 전부 읽지 않는다.
- 개발 요청에 포함된 새로운 영구 지식만 에이전트용 위키에 구조적으로 반영한다.
- 루트 공통 Python 환경과 `packages/`를 미리 만들지 않는다.
- `data/`에는 테스트 코드를 추가하지 않는다.
- 비밀값과 개인정보를 저장소, 로그, 예시 데이터 또는 프롬프트에 기록하지 않는다.
- 현재 기술 후보를 팀이 승인한 결정으로 표현하지 않는다.

## Git

브랜치 생성, 변경 범위, PR, 검토와 병합 작업 전 [브랜치 및 PR 정책](.agents-rule/git.md)을 읽고 따른다. `.agents-rule/git.md`가 해당 정책의 유일한 정본이다.
