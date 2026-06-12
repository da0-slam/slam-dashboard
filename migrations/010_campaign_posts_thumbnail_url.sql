-- Migration 010: campaign_posts 테이블에 thumbnail_url 컬럼 추가
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행

ALTER TABLE public.campaign_posts
    ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;

COMMENT ON COLUMN public.campaign_posts.thumbnail_url IS '캠페인 게시물의 썸네일 URL. 대시보드 썸네일 뷰 및 스크래핑 저장용.';
