-- ============================================================
-- Migration 019: 브랜드 랭킹용 UGC 콘텐츠 저장 테이블
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

CREATE TABLE IF NOT EXISTS public.brand_ranking_content (
    id                 TEXT PRIMARY KEY,          -- 플랫폼 콘텐츠 고유 ID (예: TikTok video id)
    brand_name         TEXT NOT NULL,
    platform           TEXT NOT NULL DEFAULT 'tiktok',
    post_url           TEXT,
    video_url          TEXT,
    title              TEXT,
    channel_username   TEXT,
    channel_followers  BIGINT,
    channel_verified   BOOLEAN,
    likes              BIGINT DEFAULT 0,
    comments           BIGINT DEFAULT 0,
    shares             BIGINT DEFAULT 0,
    views              BIGINT DEFAULT 0,
    hashtags           TEXT[],
    region_code        TEXT,
    city_name          TEXT,
    input_source       TEXT,                      -- 이 콘텐츠를 수집한 검색어/멘션/해시태그
    uploaded_at        TIMESTAMPTZ,
    imported_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brand_ranking_content_brand ON public.brand_ranking_content(brand_name);
CREATE INDEX IF NOT EXISTS idx_brand_ranking_content_uploaded ON public.brand_ranking_content(uploaded_at);

-- 확인 쿼리:
-- SELECT brand_name, COUNT(*), SUM(views), SUM(likes+comments+shares) FROM public.brand_ranking_content GROUP BY brand_name;
