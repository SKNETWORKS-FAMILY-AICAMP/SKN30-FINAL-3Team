---
status: 구현됨
updated: 2026-09-08
---

# ADR-0032: 범용 모델 프로필 선택과 3모델 비교

상태: 사용자 구현·평가 승인, 코드 구현·팀 검토 대기. 실제 평가 결과는 연결된 정본 참조.
부분 대체: ADR-0026·0030의 범용 서빙 단일 27B BnB 고정 선택.
기존 local 기본값·개인정보·수동 전원·자동 fallback 금지·공유 DB 명시 활성화는 유지한다.

Infra는 `qwen3-14b-awq`, `qwen3-32b-awq`, `qwen38-27b-fp8` 및 기존 `qwen38-27b-bnb`의 repository·revision·
가중치 해시·런타임과 실행 옵션을 [프로필 파일](../../../../../infra/serving/model-profiles.json)에
고정한다. 모듈은 다른 모듈의 내부 Python 구현을 import하지 않는다. AI/CHATBOT 평가와
로컬 선택에는 명시적 프로필 파일을 전달하고, F3 Backend 내장 allowlist는 정합 테스트로 대조한다.
범용 endpoint alias는 유지하고 DB의 각 capability 활성 모델은 명시적으로만 변경한다.

모델 변경은 재기동·재로딩을 요구한다. Infra는 기대 모델을 준비 확인·endpoint metadata·앱 smoke에
전달하며, 다른 모델이 실행 중인 endpoint에 대한 활성화를 거부한다. 이미지에는 가중치를 넣지 않고
기동 시 다운로드·실제 bytes 해시 검증을 수행한다. 평가기는 인증된 서버 metadata를 전후 대조하고
공식 기반 이미지와 실제 배포 이미지 digest를 구분한다.

이번 비교는 세 모델을 동일한 8K·동시 추론 1건·L40S 48GB 조건에서 순차 평가한다.
사용자가 추론용 양자화 재검토 후 공식 `Qwen/Qwen3.8-27B-FP8`을 최종 선택하여
세 번째 품질 비교 모델을 BnB에서 FP8으로 변경했다. BnB는 기동 성공·품질 미평가 이력과
명시 선택 프로필로 보존하며 FP8 점수로 BnB 결과를 대체하지 않는다. 실패·미실행은 통과와 구분한다.
공유 dev 배포·기존 F3 개인 Pod 변경은 포함하지 않는다. 합성 입력만 사용한다.
평가 담당자가 평가 종료·로딩 실패 시 해당 Pod를 삭제한다.

실제 결과·비용·검증 한계와 실행 방법은 [비교 기록](../../../../../infra/serving/model-comparison-2026-09-08.md)이 정본이다.

사용자 요청으로 [검토 재현 절차](../../../../../infra/serving/comparison-reproduction.md)와
[게시 이미지 catalog](../../../../../infra/serving/published-images.json)를 유지한다.
태그는 식별용이며 실제 배포는 digest로 고정한다. CPU 검사·기동 성공·평가 완료·품질 합격을 구분하고
재현 도구의 증거 정합 통과를 모델 품질 합격이나 현재 원격 상태의 증명으로 간주하지 않는다.
