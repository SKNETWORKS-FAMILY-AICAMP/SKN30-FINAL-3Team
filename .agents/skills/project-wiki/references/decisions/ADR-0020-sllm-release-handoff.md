---
status: 결정
updated: 2026-09-02
---

# ADR-0020: SLLM 릴리스 전달과 임시 dev 서빙

- 상태: 승인됨·코드 구현, 외부 자원 미적용
- 결정일: 2026-09-01
- 상위 런타임 유지: [ADR-0008](ADR-0008-dev-demo-runtime-and-delivery.md)의
  `EC2 Backend + 설치형 brokerage-ai + RunPod 추론` 구조
- 부분 대체: [Infra ADR-0002](../../../infra/references/decisions/ADR-0002-dev-demo-aws-runpod-architecture.md)의
  개발자별 RunPod 운영, 시연 기간 Pod 유지, 조건부 Network Volume 조항

## 맥락

학습 담당자가 RunPod 서빙 인프라까지 직접 운영하고 모델을 개인 PC에만 보관하면 학습 실험의
자율성과 dev 배포 책임이 섞인다. RunPod Pod는 정지 후 같은 GPU 재사용을 보장하지 않으므로
영속 Pod·Volume을 전제로 한 stop/start 운영도 맞지 않는다.

ADR-0008의 애플리케이션·GPU 런타임 배치는 유지한다. 다만 Infra ADR-0002의 초기 RunPod 운영은
모델 정본과 공유 dev 운영 주체가 불명확하고 유휴 Pod·Volume 비용이 남으므로, S3 release를
정본으로 사용하는 공유 Pod create/delete 방식으로 대체한다.

## 결정

- 학습 담당자는 `infra/` 접근 없이 로컬에서 학습·평가한다. 정량 승격 임계값은 아직 고정하지
  않으며, `full` 평가 지표를 검토한 담당자가 선택 모델·평가 실행·승인 사유를 명시한
  `promotion-approval:v1`을 만든다. 패키징 도구는 상태가 `approved`이고 선택 모델과 평가 실행이
  실제 요약에 일치할 때만 PEFT adapter와 최소 manifest를 bundle로 만든다. 비교를 위해 함께
  평가한 다른 모델까지 모두 통과할 필요는 없다.
- Infra 담당자는 bundle을 재검증하고 private S3 `releases/sllm/<release-id>/`에 불변 게시한다.
  원본 데이터, 전사, checkpoint와 비밀값은 전달하거나 게시하지 않는다.
- 공유 dev RunPod는 필요할 때 Secure Cloud Pod를 생성하고 작업 종료 시 삭제한다. Volume은 두지
  않으며 S3 release가 모델 정본이다.
- 외부 서비스명과 요청 모델명은 구현 모델명이 아니라 작업명 `sllm`, `stt`를 사용한다.
- Pod가 없으면 endpoint set을 `offline`으로 원자 갱신한다. Backend는 정상 기동하고 F2 요청만
  `F2_UNAVAILABLE` 503을 반환한다.

## 결과

학습자는 Cloud 권한이나 고정 Template 제약 없이 실험할 수 있고, Infra는 전달받은 모델만 검토해
dev에 승격한다. 매 생성 시 모델 다운로드 시간이 들지만 유휴 GPU·Volume 비용과 개인 PC 단일
보관 위험을 제거한다.
