---
status: 결정
updated: 2026-09-04
---

# ADR-0019: Bedrock Luna dev POC runtime과 Instance Role 인증

- 상태: 승인됨·코드 구현, AWS 미적용
- 결정일: 2026-09-04
- 상위 결정: [프로젝트 ADR-0027: 범용 생성 모델은 Bedrock GPT-5.6 Luna로 dev POC한다](../../../project-wiki/references/decisions/ADR-0027-bedrock-gpt56-luna-dev-poc.md)
- 부분 대체: [ADR-0004](ADR-0004-dev-runtime-and-observability-baseline.md)의 IMDSv2 hop
  limit 1, [ADR-0013](ADR-0013-dev-environment-materialization.md)의 OpenAI key 필수 계약

## 결정

- 공개 SSM 설정 `AI_LLM_ENDPOINTS`에 `general-dev-bedrock`, `bedrock`,
  `ap-northeast-2`를 기록한다. URL은 AI runtime이 공식 `bedrock-runtime` host로
  조립하며 Terraform에는 Bedrock key나 임의 endpoint를 두지 않는다.
- 앱 EC2 role에는 `global.openai.gpt-5.6-luna`의 비스트리밍 Responses 생성에 필요한
  `bedrock:InvokeModel`과 `bedrock:GetInferenceProfile`만 추가한다. Global CRIS profile,
  서울·global foundation model과 계정의 `project/default`를 별도 statement로 제한하고
  `bedrock:InferenceProfileArn`, `bedrock:ProjectArn`, `bedrock:ModelArn` 조건을 적용한다.
  streaming·저장 응답 조회/취소/삭제와 Bedrock 관리 권한은 추가하지 않는다.
- Worker 컨테이너는 EC2 Instance Role 임시 credential로 요청마다 SigV4 서명한다. IMDSv2
  token 필수와 metadata tag 비활성화는 유지하고 Docker bridge를 위해 hop limit을 2로
  변경한다. 동일 EC2의 다른 컨테이너도 role credential에 접근할 수 있으므로 이 구성은
  합성·비식별 dev에만 허용한다.
- AI provider Secret의 OpenAI key는 선택값이다. F2 endpoint가 `active`일 때만 서로 다른
  SLLM·STT key 두 개를 필수로 검증해 API에 주입하고, `offline`이면 값이 없어도 Bedrock-only
  배포를 허용한다. RunPod bootstrap은 F2 key만 생성하며 Bedrock key를 만들지 않는다.
- `bedrock-doctor`는 SSM Run Command로 배포 image의 일회성 Worker 컨테이너를 실행해
  Instance Role, IMDSv2 hop과 `GetInferenceProfile`을 확인한다. 모델 추론, 사용자 입력과
  응답 저장은 수행하지 않는다.
- ASG에는 자동 `instance_refresh`를 추가하지 않는다. Terraform apply 뒤 운영자가 공유 dev의
  활성 작업 종료와 중단 시간을 확인하고 `dev-stop` 뒤 `dev-start`를 명시 실행해 기존 EC2를
  종료한 뒤 최신 Launch Template으로 교체한다. 이 과정은 RDS도 정지·재시작한다. 새 EC2가
  `InService`, SSM `Online`, IMDSv2 token 필수·hop limit 2이고 Backend revision이 배포된 뒤에만
  doctor를 실행한다.
- Terraform apply나 application deploy는 DB 활성 모델을 바꾸지 않는다. doctor가 성공하면
  `dev-bedrock-gpt56-luna` seed 프로필을 명시 적용한 뒤 합성 F3 smoke를 수행한다. 실패하면
  OpenAI key·runtime이 배포된 환경에서만 `local-openai`를 명시 재적재한다. 그렇지
  않으면 Worker를 정지하고 Bedrock 설정을 복구하며 자동 fallback하지 않는다.

## 결과와 운영 경계

정적 AWS access key와 Bedrock API key를 저장하지 않고 기존 EC2·CodeDeploy 경로에서 POC할 수
있다. 서울 호출은 Global cross-Region으로 처리될 수 있으므로 실제 개인정보는 금지한다.
GPU EC2·EBS cache와 Qwen serving, F2 RunPod lifecycle, prod identity는 변경하지 않는다.

적용 전 saved plan에서 Launch Template 변경, IAM resource와 condition, SSM 공개값 및 Secret
version 삭제 부재를 검토한다. apply 자체는 기존 ASG 인스턴스를 갱신하지 않는다. 적용 후
`dev-stop`→`dev-start`로 새 인스턴스를 만들고 application revision을 배포한 뒤
`bedrock-doctor`를 통과해야 합성 seed를 전환하고 F3 smoke를 수행할 수 있다. smoke가 실패하면
OpenAI key·runtime이 존재할 때만 `local-openai` profile을 명시 복구한다. Bedrock-only 환경은
Worker를 정지하고 설정을 복구한다.

## 근거

- [GPT-5.6 Luna model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html)
- [Responses API 권한](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html)
- [Global cross-Region IAM](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)
