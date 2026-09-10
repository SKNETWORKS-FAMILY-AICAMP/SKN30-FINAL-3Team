---
status: 결정
updated: 2026-08-27
---

# 백엔드 결정 인덱스

| ADR | 상태 | 결정 |
|---|---|---|
| [ADR-0001](ADR-0001-contextual-architecture-defaults.md) | 승인됨 | 복잡도에 비례한 선택적 DDD·포트/어댑터·이벤트·테스트 기본안 사용 |
| [ADR-0002](ADR-0002-backend-runtime-database-authentication.md) | 부분 대체됨 | Python 3.13·uv·FastAPI·SQLModel·Yoyo·서버 세션 기반 사용; 환경 소유권·비밀값 주입과 개발 세션 `local` 전용 조항은 후속 ADR에서 대체 |
| [ADR-0003](ADR-0003-dev-deployment-contract.md) | 승인됨 | 같은 digest API·Worker, 명시적 migration과 비활성 Worker 배포 계약 |
| [ADR-0004](ADR-0004-always-on-f2-runtime.md) | 부분 대체됨 | F2 route를 항상 공개하고 초기에는 runtime도 항상 초기화 |
| [ADR-0005](ADR-0005-offline-f2-runtime.md) | 승인됨 | Infra endpoint가 active일 때만 F2 runtime을 초기화하고 offline 요청은 503 반환 |

큐와 배포처럼 아직 확정하지 않은 프로젝트 범위는 project-wiki의 관련 질문을 확인한다.
