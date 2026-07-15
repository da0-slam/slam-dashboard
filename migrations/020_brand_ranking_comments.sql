-- ============================================================
-- Migration 020: 브랜드 랭킹용 댓글(지역/언어 분석) 저장 테이블
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

CREATE TABLE IF NOT EXISTS public.brand_ranking_comments (
    id                 TEXT PRIMARY KEY,          -- 댓글 고유 ID
    brand_name         TEXT NOT NULL,
    aweme_id           TEXT,                       -- brand_ranking_content.id에 대응하는 영상 ID
    parent_id          TEXT,
    text               TEXT,
    comment_language   TEXT,
    like_count         BIGINT DEFAULT 0,
    reply_count        BIGINT DEFAULT 0,
    is_author_liked    BOOLEAN,
    created_at         TIMESTAMPTZ,
    user_id            TEXT,
    username           TEXT,
    display_name       TEXT,
    user_region        TEXT,
    user_language      TEXT,
    input_source       TEXT,
    imported_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brand_ranking_comments_brand ON public.brand_ranking_comments(brand_name);
CREATE INDEX IF NOT EXISTS idx_brand_ranking_comments_aweme ON public.brand_ranking_comments(aweme_id);

-- 확인 쿼리:
-- SELECT brand_name, COUNT(*), COUNT(user_region) FROM public.brand_ranking_comments GROUP BY brand_name;
