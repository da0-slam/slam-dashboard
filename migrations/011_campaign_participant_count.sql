-- ============================================================
-- Migration 011: campaigns.participant_count 추가 + platform 확장 (x, other)
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

-- 1. campaigns 테이블에 발송 인원 수 컬럼 추가
ALTER TABLE public.campaigns ADD COLUMN IF NOT EXISTS participant_count INTEGER;

COMMENT ON COLUMN public.campaigns.participant_count IS
  'Google Sheet 이관 시 A열(name) 총 행수. 업로드율 계산용.';

-- 2. campaign_posts.platform CHECK 제약 확장 (x, other 추가)
ALTER TABLE public.campaign_posts
  DROP CONSTRAINT IF EXISTS campaign_posts_platform_check;

ALTER TABLE public.campaign_posts
  ADD CONSTRAINT campaign_posts_platform_check
  CHECK (platform IN ('instagram', 'tiktok', 'x', 'other'));

-- 확인 쿼리:
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name = 'campaigns' AND column_name = 'participant_count';
