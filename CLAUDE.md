@AGENTS.md
@.agents-rule/git.md

## Claude Code

- 프로젝트 스킬은 `.claude/skills/`에서 발견하며, 각 어댑터가 `.agents/skills/`의 정본을 가져온다.
- 스킬 본문을 `.claude/skills/`에 복사하지 않는다.
- Claude 전용 어댑터와 공용 정본이 충돌하면 `.agents/skills/`의 정본을 따른다.
