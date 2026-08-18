-- PostgreSQL 15+
-- 인물 개인정보 활용 동의 사실과 기록 주체 보존
-- depends: 009_ALTER_PROPERTY_LEDGER_FIELDS


ALTER TABLE party
    ADD COLUMN privacy_consent_at TIMESTAMPTZ,
    ADD COLUMN privacy_consent_by BIGINT,
    ADD CONSTRAINT fk_party_privacy_consent_by
        FOREIGN KEY (brokerage_id, privacy_consent_by)
        REFERENCES app_user (brokerage_id, id),
    ADD CONSTRAINT ck_party_privacy_consent_pair
        CHECK (num_nonnulls(privacy_consent_at, privacy_consent_by) <> 1);


COMMENT ON COLUMN party.privacy_consent_at IS '개인정보 활용 동의를 받은 시각. NULL은 미동의를 뜻한다. 동의 문구와 보존 기간은 별도 확정 대상이다.';
COMMENT ON COLUMN party.privacy_consent_by IS '동의 사실을 기록한 사용자 식별자.';
