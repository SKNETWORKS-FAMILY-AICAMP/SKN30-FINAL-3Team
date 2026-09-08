---
status: 구현됨
updated: 2026-09-08
---

# ADR-0021: 자체 RunPod 운영 책임 축소

- 상태: 사용자 감시 제거 명시 선택·기반 제거 적용 승인·2026-09-07 적용 및 drift 확인·팀 병합 검토 대기
- 승인 경계: 사용자 작업 승인과 작성자 외 팀원의 PR 병합 승인은 별개다. 이 문서는 팀 승인 완료를 주장하지 않는다.
- 부분 대체: [ADR-0018](ADR-0018-runpod-bootstrap-secrets-monitoring.md)의 자체 감시,
  [ADR-0020](ADR-0020-runpod-console-registration.md)의 Secret metadata 조회
- 공통 결정: [프로젝트 ADR-0029](../../../project-wiki/references/decisions/ADR-0029-runpod-manual-observation.md)

## 구현 범위

- 전용 감시 Lambda, EventBridge rule/target/permission, log group, role/policy, 8개 경보,
  감시 Secret, 주기·시간 경고 변수와 output을 제거한다. 감시 key 입력·조회도 요구하지 않는다.
- Console 등록은 REST의 Pod·registry·Template 조회만 사용한다. GraphQL client와 Secret 목록
  해석을 제거한다. Template의 Secret 참조는 검사하며 실제 값 일치는 인증 health가 검사한다.
- create는 Pod 부재와 endpoint offline을 비용 발생 전에 확인한다. health 후 active를 게시하고
  API refresh·smoke를 수행한다. 실패하면 offline 전환·refresh와 생성 Pod 삭제를 시도한다.
  정리가 실패하면 상태 조회·정확한 ID 삭제·reconcile 순서를 보고하며 성공 이벤트를 내지 않는다.
- delete는 offline 게시 → API refresh → 정확한 ID 삭제 순서다. refresh 실패 시 Pod를 남기고
  같은 delete 명령을 재실행한다. 삭제 API 실패 시 offline을 유지한다. 서버가 삭제했지만 응답만
  잃은 경우에도 죽은 active endpoint를 복원하지 않는다.
- reconcile은 active Pod 부재 시 offline을 게시한다. offline이고 Pod가 없어도 명시적 apply로
  API refresh와 offline smoke를 재실행할 수 있다. 복수 Pod·다른 Pod를 자동 선택하지 않는다.

## 유지할 책임

S3 publisher의 불변 게시·품질 증빙 검증, Pod runtime의 artifact 무결성, 인증 proxy의 경로 제한,
모델 health와 프로세스 정리는 유지한다. 파일 분할이나 테스트 삭제를 운영 코드 감소로 세지 않는다.
동시 운영 명령 실행은 지원하지 않으며 한 명의 운영자가 순서대로 실행한다.
