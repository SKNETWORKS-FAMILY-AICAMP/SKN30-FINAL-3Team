# Brokerage AI

Backend에서 사용하는 Python 3.13 기반 AI 라이브러리입니다. 독립적으로 실행하는 서버나 CLI는 없습니다.

## 설치

[uv](https://docs.astral.sh/uv/)를 준비한 뒤 의존성을 설치합니다.

```bash
cd ai
uv sync --frozen
```

모델 API 비밀값이 필요한 경우 [`.env.example`](.env.example)에 선언된 변수 이름을 참고해 Git에서 제외된 `ai/.env` 또는 실행 프로세스 환경변수로 주입합니다.
