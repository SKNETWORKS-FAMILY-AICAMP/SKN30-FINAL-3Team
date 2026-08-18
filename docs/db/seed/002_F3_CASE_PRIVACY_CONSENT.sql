-- PostgreSQL 15+
-- F3 케이스 시드의 구입장 손님에게 개인정보 활용 동의 사실을 부여한다
-- 요구 스키마: docs/db/migrate/001~010 적용 완료 상태
-- 선행: 001_F3_CASE_LEDGER.sql
--
-- 왜 별도 파일인가 — 010_ALTER_PARTY_PRIVACY_CONSENT 가 시드 생성 이후에 나와서
-- 001 이 privacy_consent_at 을 채우지 않는다. Backend 는 구입장 저장 전
-- require_privacy_consent() 로 이 값을 확인하므로(F1-DM-16), 비워 두면
-- POST /api/v1/property-requirements 가 PRIVACY_CONSENT_REQUIRED 로 전부 거절된다.
--
-- 대상은 구입장에 물린 손님 party 뿐이다. 공동중개 업소와 매물 소유자·임차인은
-- 동의 검사 대상이 아니므로 건드리지 않는다.
-- 재현성을 위해 now() 가 아닌 고정 시각을 쓴다.

UPDATE party p
SET privacy_consent_at = TIMESTAMPTZ '2026-07-01 09:00:00+09',
    privacy_consent_by = (SELECT u.id
                          FROM app_user u
                          WHERE u.brokerage_id = p.brokerage_id
                            AND u.login_id = 'owner')
WHERE p.brokerage_id = (SELECT id FROM brokerage WHERE name = '한들공인중개사사무소')
  AND p.id IN (SELECT r.party_id
               FROM property_requirement r
               WHERE r.brokerage_id = p.brokerage_id);
