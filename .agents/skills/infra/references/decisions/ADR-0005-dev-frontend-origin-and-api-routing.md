---
status: 결정
updated: 2026-08-27
---

# ADR-0005: 개발 환경 Frontend origin과 API routing 기준

- 상태: 부분 대체됨
- 결정일: 2026-08-18
- 대체 범위: Frontend Verify와 Build의 분리된 실행 순서는 [ADR-0011](ADR-0011-dev-delivery-implementation.md)이 대체

## 맥락

사용자 소유 도메인 없이 Frontend와 Backend API를 동일 origin으로 제공하면서 S3를 공개하지 않고, 현재 합성·비식별 시연 제약 안에서 비용과 복잡도를 제한해야 한다. Frontend artifact 전달과 invalidation은 별도 delivery 단계다.

## 결정

- Frontend build artifact 전용 private S3 bucket을 Terraform state, Pipeline artifact와 업무용 bucket에서 분리한다.
- bucket은 BucketOwnerEnforced, public access block 4종, SSE-S3와 TLS-only deny를 사용하며 website hosting은 사용하지 않는다.
- CloudFront OAC가 SigV4로 서명하고 해당 distribution `AWS:SourceArn` 조건에서 object read만 허용한다. bucket list 권한은 주지 않는다.
- 사용자 도메인·Route 53·ACM 없이 CloudFront 기본 domain과 인증서를 사용한다. IPv6, WAF, access logging, Origin Shield는 현재 범위에서 제외한다.
- default behavior는 private S3와 managed `CachingOptimized`를 사용하고 viewer HTTP를 HTTPS로 redirect한다.
- `/api/*`는 ALB HTTP 80 custom origin으로 전달한다. viewer는 HTTPS redirect하고 cache는 끄며 `AllViewerExceptHostHeader`로 cookie, query와 CSRF를 포함한 viewer header를 전달한다.
- default와 API behavior 모두 managed `SecurityHeadersPolicy`를 사용한다. credential cookie와 충돌할 수 있는 wildcard CORS managed policy는 사용하지 않고 CORS는 Backend가 소유한다.
- 전역 403/404→`index.html` rewrite는 API 오류를 가릴 수 있고 현재 client router도 없으므로 추가하지 않는다.

## Delivery 선행 계약

- `npm ci → test:env → test:auth → typecheck → 원장 테스트 → Vite build → release test` 전체 검증 계약을 유지한다. Verify와 Build의 분리된 실행 순서는 ADR-0011을 따른다.
- `index.html`은 `no-cache` 또는 짧은 TTL metadata로, hash asset은 장기 immutable metadata로 업로드하고 distribution invalidation을 수행한다.
- CloudFront는 viewer Host를 ALB DNS Host로 바꾸므로 Backend allowed-host에 ALB DNS를 허용한다. ALB target health의 private-IP Host 처리는 별도 Backend 계약으로 해결한다.
- bucket은 `force_destroy=false`이므로 환경 종료 시 승인된 artifact 반출 후 객체를 비우고 Terraform destroy를 수행한다.

## 잔여 위험

- CloudFront 기본 인증서는 최소 viewer protocol을 별도로 강화할 수 없어 legacy TLS 허용이 남는다. 실제 개인정보를 금지하는 현재 demo 제약에서만 수용한다.
- CloudFront origin-facing prefix list는 현재 distribution 하나를 식별하지 않는다. 다른 distribution이 ALB DNS를 origin으로 지정하는 위험은 합성·비식별 환경에서 수용하고, 운영 승격 시 custom origin 인증 또는 VPC origin을 결정한다.
- CloudFront→ALB는 HTTP이므로 종단 간 TLS가 아니다. 실제 개인정보 사용 전에는 사용자 도메인·ACM과 origin 보안을 새 결정으로 승격한다.

## 결과

- Frontend 인프라 추가 후 원격 state 기준 read-only plan은 dev 전체 `96 add / 0 change / 0 destroy`이며 apply하지 않았다.
- CloudFront distribution 생성·변경은 전역 배포 완료까지 수분 이상 걸릴 수 있다.
- 비용은 CloudFront request·전송·invalidation과 S3 저장·request 사용량 중심이며 plan은 금액을 계산하지 않는다.
