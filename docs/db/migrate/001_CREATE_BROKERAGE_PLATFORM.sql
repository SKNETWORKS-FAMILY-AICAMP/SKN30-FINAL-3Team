-- PostgreSQL 15+
-- 중개사무소, 사용자, 불변 AI 모델 설정
-- depends:


CREATE TABLE brokerage (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                            VARCHAR(120) NOT NULL,
    business_registration_number    VARCHAR(20),
    settings                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    row_version                     BIGINT NOT NULL DEFAULT 1,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_brokerage_business_registration_number
    ON brokerage (business_registration_number)
    WHERE business_registration_number IS NOT NULL;

CREATE TABLE app_user (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    login_id            VARCHAR(100) NOT NULL,
    password_hash       TEXT NOT NULL,
    display_name        VARCHAR(80) NOT NULL,
    role                VARCHAR(20) NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at       TIMESTAMPTZ,
    row_version         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_app_user_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT uq_app_user_login
        UNIQUE (brokerage_id, login_id),
    CONSTRAINT uq_app_user_tenant_id
        UNIQUE (brokerage_id, id)
);

CREATE INDEX idx_app_user_brokerage_active
    ON app_user (brokerage_id, is_active);

CREATE TABLE ai_model_config (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id        BIGINT NOT NULL,
    capability          VARCHAR(50) NOT NULL,
    config_key          VARCHAR(100) NOT NULL,
    config_version      INTEGER NOT NULL,
    provider            VARCHAR(80) NOT NULL,
    model_name          VARCHAR(160) NOT NULL,
    model_version       VARCHAR(120),
    endpoint_alias      VARCHAR(160),
    parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ai_model_config_brokerage
        FOREIGN KEY (brokerage_id)
        REFERENCES brokerage (id),
    CONSTRAINT fk_ai_model_config_created_by
        FOREIGN KEY (brokerage_id, created_by)
        REFERENCES app_user (brokerage_id, id),
    CONSTRAINT uq_ai_model_config_version
        UNIQUE (brokerage_id, capability, config_key, config_version),
    CONSTRAINT uq_ai_model_config_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT ck_ai_model_config_positive_version
        CHECK (config_version > 0)
);

CREATE INDEX idx_ai_model_config_capability
    ON ai_model_config (brokerage_id, capability, is_active);


COMMENT ON TABLE brokerage IS '서비스를 사용하는 중개사무소. 전체 업무 데이터의 최상위 tenant.';
COMMENT ON COLUMN brokerage.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN brokerage.name IS '중개사무소 표시명.';
COMMENT ON COLUMN brokerage.business_registration_number IS '중개사무소 사업자등록번호.';
COMMENT ON COLUMN brokerage.settings IS '사무소 설정 JSON.';
COMMENT ON COLUMN brokerage.status IS '현재 상태 값. 상태 전이는 서버에서 관리한다.';
COMMENT ON COLUMN brokerage.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN brokerage.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN brokerage.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE app_user IS '개업공인중개사·직원·읽기전용 사용자를 관리한다. 계정은 삭제보다 비활성화를 사용한다.';
COMMENT ON COLUMN app_user.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN app_user.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN app_user.login_id IS '사용자 로그인 식별자.';
COMMENT ON COLUMN app_user.password_hash IS '비밀번호 해시 값.';
COMMENT ON COLUMN app_user.display_name IS '화면 표시 사용자명.';
COMMENT ON COLUMN app_user.role IS '사용자 역할 값.';
COMMENT ON COLUMN app_user.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN app_user.last_login_at IS '마지막 로그인 시각.';
COMMENT ON COLUMN app_user.row_version IS '낙관적 동시성 제어용 버전 값. 서버가 증가시킨다.';
COMMENT ON COLUMN app_user.created_at IS '레코드 생성 시각.';
COMMENT ON COLUMN app_user.updated_at IS '레코드 최종 수정 시각. 서버가 갱신한다.';

COMMENT ON TABLE ai_model_config IS '상담 전사·필드 추출과 에이전트·임베딩 모델을 설정으로 교체하기 위한 메타데이터. 비밀키는 저장하지 않는다.';
COMMENT ON COLUMN ai_model_config.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN ai_model_config.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN ai_model_config.capability IS '모델이 담당하는 AI 기능 구분 값.';
COMMENT ON COLUMN ai_model_config.config_key IS '동일 capability 안에서 모델 설정을 구분하는 키.';
COMMENT ON COLUMN ai_model_config.config_version IS '동일 설정 키의 양의 정수 버전.';
COMMENT ON COLUMN ai_model_config.provider IS '모델 제공자 또는 서빙 환경.';
COMMENT ON COLUMN ai_model_config.model_name IS '모델 이름.';
COMMENT ON COLUMN ai_model_config.model_version IS '공급자가 제공하거나 운영자가 기록한 모델 세부 버전.';
COMMENT ON COLUMN ai_model_config.endpoint_alias IS '서버에서 참조할 엔드포인트 별칭.';
COMMENT ON COLUMN ai_model_config.parameters IS '모델 호출 파라미터 JSON.';
COMMENT ON COLUMN ai_model_config.is_active IS '사용 가능 여부.';
COMMENT ON COLUMN ai_model_config.created_by IS '생성 사용자 식별자.';
COMMENT ON COLUMN ai_model_config.created_at IS '레코드 생성 시각.';
