-- ============================================================
-- Migration 003: influencer_master에 cover_url 컬럼 추가
--
-- 적용: Supabase 대시보드 → SQL Editor에서 실행
--
-- 목적:
--   Apify KV Store 또는 TikTok CDN이 아닌
--   Supabase Storage의 영구 public URL을 저장한다.
--   scripts/migrate_kv_to_storage.py 실행 후 채워진다.
-- ============================================================

ALTER TABLE public.influencer_master
    ADD COLUMN IF NOT EXISTS cover_url TEXT;

COMMENT ON COLUMN public.influencer_master.cover_url
    IS 'Supabase Storage에 저장된 대표 커버 이미지 public URL. scripts/migrate_kv_to_storage.py로 채움.';

-- 확인
-- SELECT influencer_id, cover_url FROM influencer_master LIMIT 5;
