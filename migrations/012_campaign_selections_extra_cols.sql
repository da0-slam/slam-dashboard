-- ============================================================
-- Migration 012: campaign_selections 협상 메타데이터 컬럼 추가
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

ALTER TABLE public.campaign_selections
  ADD COLUMN IF NOT EXISTS followers     BIGINT,
  ADD COLUMN IF NOT EXISTS contact_email TEXT,
  ADD COLUMN IF NOT EXISTS ratecard      TEXT,
  ADD COLUMN IF NOT EXISTS after_nego    TEXT,
  ADD COLUMN IF NOT EXISTS usage_rights  TEXT,
  ADD COLUMN IF NOT EXISTS platform_url  TEXT;

COMMENT ON COLUMN public.campaign_selections.followers     IS '팔로워 수 (Google Sheet 이관 시 채워짐)';
COMMENT ON COLUMN public.campaign_selections.contact_email IS '컨택 이메일';
COMMENT ON COLUMN public.campaign_selections.ratecard      IS '레이트카드 원문 텍스트';
COMMENT ON COLUMN public.campaign_selections.after_nego    IS '네고 후 확정가';
COMMENT ON COLUMN public.campaign_selections.usage_rights  IS 'Usage Rights 조건';
COMMENT ON COLUMN public.campaign_selections.platform_url  IS '프로필 URL';

-- 확인 쿼리:
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name = 'campaign_selections'
-- ORDER BY ordinal_position;
