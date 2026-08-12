---
status: 결정
updated: 2026-08-12
---

# ADR-0004: 공용 지침과 스킬을 Claude Code에서도 재사용

- 상태: 승인됨
- 결정일: 2026-08-12

## 맥락

저장소의 지침과 스킬은 Codex뿐 아니라 Claude Code에서도 사용해야 한다. 같은 정책과 스킬 본문을 도구별 위치에 복사하면 내용이 쉽게 달라진다.

Claude Code는 루트 `CLAUDE.md`를 매 세션 읽고, 프로젝트 스킬을 `.claude/skills/<name>/SKILL.md`에서 발견한다. `CLAUDE.md`와 스킬은 `@path` import를 지원한다.

## 결정

- 공용 상시 지침의 정본은 루트 `AGENTS.md`로 유지한다.
- 브랜치 및 PR 정책의 정본은 루트 `.agents-rule/git.md`로 유지한다.
- Claude Code의 `CLAUDE.md`는 `@AGENTS.md`와 `@.agents-rule/git.md`를 import한다.
- 공용 스킬 본문과 참조 문서의 정본은 `.agents/skills/`로 유지한다.
- `.claude/skills/`에는 자동 발견에 필요한 최소 frontmatter와 공용 `SKILL.md`를 가져오는 `@path`만 둔다.
- Claude 어댑터에 스킬 본문이나 정책을 복사하지 않는다.

## 결과

두 에이전트가 같은 지침과 스킬 본문을 사용한다. Claude 스킬 어댑터의 name과 description은 자동 발견을 위한 필수 메타데이터이므로 공용 frontmatter와 일치하도록 검증해야 한다.
