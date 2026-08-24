-- PostgreSQL 15+
-- 포지션 카드의 거래 유형별 표기·추정 금액 보존
-- depends: 011_ALTER_AGENT_EXECUTION_LEASE


-- negotiation_position_analysis 는 표기·추정 금액을 각각 컬럼 하나로만 갖는다.
-- 한 매물이 매매·전세·월세를 동시에 열어 둘 수 있으므로 그중 하나를 대표로 고르면
-- 나머지 금액이 사라진다. 거래 유형별로 행을 두어 전부 보존한다.
CREATE TABLE negotiation_position_price (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brokerage_id            BIGINT NOT NULL,
    position_analysis_id    BIGINT NOT NULL,
    price_kind              VARCHAR(20) NOT NULL,
    stated_amount           BIGINT,
    stated_monthly_amount   BIGINT,
    estimated_amount        BIGINT,
    estimated_monthly_amount BIGINT,
    display_order           INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_position_price_analysis
        FOREIGN KEY (brokerage_id, position_analysis_id)
        REFERENCES negotiation_position_analysis (brokerage_id, id),
    CONSTRAINT uq_position_price_tenant_id
        UNIQUE (brokerage_id, id),
    CONSTRAINT uq_position_price_kind
        UNIQUE (brokerage_id, position_analysis_id, price_kind),
    CONSTRAINT ck_position_price_amounts_not_negative
        CHECK (
            (stated_amount IS NULL OR stated_amount >= 0)
            AND (stated_monthly_amount IS NULL OR stated_monthly_amount >= 0)
            AND (estimated_amount IS NULL OR estimated_amount >= 0)
            AND (estimated_monthly_amount IS NULL OR estimated_monthly_amount >= 0)
        ),
    CONSTRAINT ck_position_price_monthly_requires_monthly_rent
        CHECK (
            price_kind = 'MONTHLY_RENT'
            OR (stated_monthly_amount IS NULL AND estimated_monthly_amount IS NULL)
        ),
    CONSTRAINT ck_position_price_display_order_not_negative
        CHECK (display_order >= 0)
);

CREATE INDEX idx_position_price_analysis
    ON negotiation_position_price (
        brokerage_id,
        position_analysis_id,
        display_order
    );


COMMENT ON TABLE negotiation_position_price IS '포지션 카드의 거래 유형별 장부 표기 금액과 대리 추정 금액. 한 카드에 매매·전세·월세가 함께 있을 수 있다.';
COMMENT ON COLUMN negotiation_position_price.id IS '레코드 고유 식별자.';
COMMENT ON COLUMN negotiation_position_price.brokerage_id IS '데이터를 소유하는 중개사무소 식별자.';
COMMENT ON COLUMN negotiation_position_price.position_analysis_id IS '소속 포지션 카드 식별자.';
COMMENT ON COLUMN negotiation_position_price.price_kind IS '금액이 가리키는 거래 유형. 매매, 전세, 월세 또는 구입 예산이다.';
COMMENT ON COLUMN negotiation_position_price.stated_amount IS '장부에 표기된 금액. 월세는 보증금이고 구입장은 예산 상한이다.';
COMMENT ON COLUMN negotiation_position_price.stated_monthly_amount IS '장부에 표기된 월 차임. 월세에서만 사용한다.';
COMMENT ON COLUMN negotiation_position_price.estimated_amount IS '대리가 추정한 실질 금액. 표기 금액과 다르면 근거가 필요하다.';
COMMENT ON COLUMN negotiation_position_price.estimated_monthly_amount IS '대리가 추정한 실질 월 차임. 월세에서만 사용한다.';
COMMENT ON COLUMN negotiation_position_price.display_order IS '카드에 실린 원래 순서.';
COMMENT ON COLUMN negotiation_position_price.created_at IS '레코드 생성 시각.';
