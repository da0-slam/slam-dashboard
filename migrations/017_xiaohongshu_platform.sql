-- ============================================================
-- Migration 017: campaign_posts.platform에 xiaohongshu(샤오홍슈/RedNote) 추가
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

ALTER TABLE public.campaign_posts
  DROP CONSTRAINT IF EXISTS campaign_posts_platform_check;

ALTER TABLE public.campaign_posts
  ADD CONSTRAINT campaign_posts_platform_check
  CHECK (platform IN ('instagram', 'tiktok', 'x', 'other', 'xiaohongshu'));

-- 확인 쿼리:
-- SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
-- WHERE conname = 'campaign_posts_platform_check';
