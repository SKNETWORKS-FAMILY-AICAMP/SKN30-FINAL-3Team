# 산출물 운영

이 디렉터리는 강사 제출용 산출물의 목록, Git 이관 상태와 외부 배포 이력을 관리한다. 산출물 본문과 프로젝트 위키의 정합성을 유지하되 한 작업에서 한 문서만 다룬다.

## 정본과 책임

- [`registry.yaml`](registry.yaml): 관리 대상, Git 소스 위치와 Drive·관리 시트 식별자
- project-wiki와 `docs/`: 프로젝트 요구사항, 아키텍처, 계약과 정책
- 문서별 `content`: 이관 후 제출 문서의 편집 정본
- Google Drive: 사람이 승인한 배포본
- 관리 시트: 제출 링크와 사람이 판단한 제출 상태

레지스트리는 제출 상태나 강사 피드백을 복제하지 않는다. 파일 존재, 링크, 마감일과 이전 셀 값만으로 제출 상태를 판단하지 않는다.

## v1 범위

레지스트리에는 사용자가 지정한 8개 산출물만 있다. WBS는 요청이 있을 때만 관리하고, 4주차·중간 발표·향후 6~7주차 산출물은 제외한다.

기존 6개 문서는 `external_pending_import`이며 선택된 문서 작업에서 한 건씩 Git으로 이관한다. ML 두 산출물은 예외적으로 `feat/ml-poc`의 `ml/field_proposal_reliability/`를 사용한다.

## 한 문서 작업

1. 레지스트리에서 대상 한 건을 고른다.
2. 그 문서에 필요한 Drive 원본과 Git 정본만 읽는다.
3. 충돌은 임의로 정리하지 않고 사람에게 확인한다.
4. 선택된 문서만 작성·검증하고 종료한다.
5. 다른 문서는 별도 요청에서 처리한다.

문서를 처음 이관할 때만 `docs/deliverables/<artifact_id>/` 아래에 `content`, `source-map.yaml`과 필요한 릴리스 기록을 만든다. 빈 문서 폴더를 미리 만들지 않는다.

상세 에이전트 절차는 [deliverables 스킬](../../.agents/skills/deliverables/SKILL.md), 필드 정의는 [레지스트리 계약](../../.agents/skills/deliverables/references/registry-schema.md)을 따른다.

## 외부 배포

Codex의 Google Drive 읽기 연결은 2026-08-25 확인했다. 업로드와 시트 수정 기능은 제공되지만 실제 쓰기 권한은 아직 검증하지 않았다. 첫 개별 문서 배포에서 사람의 명시적 승인 후 시험한다.

배포는 기존 파일을 덮어쓰지 않고 새 파일을 올린 뒤 Drive에서 다시 확인한다. `3팀` 시트의 행은 저장된 번호가 아니라 `산출물 구분`의 정확한 제목으로 찾는다. 링크만 갱신하며 상태값은 사람이 현재 작업에서 확인한 경우에만 그대로 입력한다.

Claude Code의 Drive·Sheets 연결은 미확정이므로 검증 전에는 Git 결과와 수동 배포 안내까지만 제공한다.

## 검증

```bash
python3 .agents/skills/deliverables/scripts/validate_registry.py
python3 /path/to/skill-creator/scripts/quick_validate.py .agents/skills/deliverables
```

두 번째 명령의 `quick_validate.py` 경로는 실행 중인 Codex skill-creator 설치 위치를 사용한다.
