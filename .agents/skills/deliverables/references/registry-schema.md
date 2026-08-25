# 산출물 레지스트리 계약

## 책임

`docs/deliverables/registry.yaml`은 산출물 목록, Git 소스 위치와 외부 연결 식별자의 정본이다. 문서 본문, 강사 피드백과 제출 상태는 소유하지 않는다.

## 최상위 구조

- `schema_version`: 레지스트리 계약 버전
- `updated`: 마지막 구조 변경일
- `policy`: 정본, 한 문서 원칙과 제외 범위
- `integrations`: Drive와 관리 시트의 식별자 및 검증된 연결 범위
- `artifacts`: 관리 대상 산출물 목록

`policy.submission_status_owner`는 항상 `human`이다. `status`, `submission_status`, `feedback`, `instructor_feedback` 같은 현재 상태·피드백 필드를 레지스트리에 추가하지 않는다.

## 산출물 필드

각 `artifacts` 항목은 다음 필드를 모두 가진다.

| 필드 | 의미 |
|---|---|
| `artifact_id` | 영문 kebab-case 불변 식별자 |
| `title` | 산출물 안내·사람 화면용 제목 |
| `week` | 3팀 관리 시트에서 확인한 주차 숫자 |
| `management_mode` | `active` 또는 `manual_on_request` |
| `source_mode` | `external_pending_import`, `git_branch`, `git_managed` 중 하나 |
| `source_ref` | Git 브랜치·커밋 ref, 없으면 `null` |
| `source_paths` | Git 소스 경로 목록, 없으면 빈 목록 |
| `drive_folder_id` | 배포 대상 Drive 폴더 ID |
| `drive_file_id` | 2026-08-25에 확인한 기존 파일 ID |
| `drive_url` | 확인된 기존 파일 URL |
| `observed_at` | 외부 식별자를 마지막으로 확인한 날짜 |
| `sheet_row_key` | `3팀` 탭의 `산출물 구분`에서 찾을 정확한 값 |
| `notes` | 상태 판단이 아닌 운영상 예외 목록 |

## 소스 모드 전이

- `external_pending_import`: 기존 본문이 Drive에만 있다. 해당 문서를 선택한 작업에서만 Git 본문과 `source-map.yaml`을 만든 뒤 `git_managed`로 바꾼다.
- `git_branch`: 현재 통합 브랜치가 아닌 별도 Git ref가 정본이다. ref와 경로를 모두 확인한다.
- `git_managed`: 현재 개발 계열 Git 경로가 본문 정본이다.

`external_pending_import`는 운영 레지스트리가 Git 정본이라는 결정의 예외가 아니라, 과거 문서 본문을 아직 이관하지 않았다는 객관적 전환 상태다.

## 문서별 후속 파일

선택된 문서를 처음 이관할 때만 `docs/deliverables/<artifact_id>/`를 만들고 다음 파일을 둔다. 선택되지 않은 문서의 빈 폴더는 만들지 않는다.

- `content.<ext>`: 제출 문서의 편집 정본
- `source-map.yaml`: 문서 구역별 근거 경로, 확인 Git 커밋, 충돌과 미확정 항목
- `releases/<release_id>.yaml`: 출력 체크섬과 검증된 외부 배포 이력

`source-map.yaml`은 최소한 `schema_version`, `artifact_id`, `checked_commit`, `sections[]`를 가진다. 각 section은 `name`, `sources[]`, `conflicts[]`를 기록한다.

릴리스 기록은 객관적인 배포 사실만 소유한다. `release_id`, `artifact_id`, `source_commit`, `output_path`, `sha256`, Drive 파일 ID·URL, 시트 탭·행 키·확인 셀, `distribution_state`를 기록할 수 있다. 사람의 상태 확인을 기록할 필요가 있으면 사람이 제공한 값·확인자·확인 시각을 함께 남기며 추론값은 허용하지 않는다.

## 변경 규칙

- 제목이나 행 키가 바뀌면 Drive·시트 실물을 읽어 확인한 뒤 수정한다.
- 기존 `artifact_id`는 제목이 바뀌어도 재사용한다.
- 새 산출물 등록은 사람의 범위 승인 후 한 건씩 수행한다.
- 4주차, 중간 발표와 향후 6~7주차 항목은 v1 목록에 추가하지 않는다.
- 변경 후 레지스트리 검증 스크립트를 실행한다.
