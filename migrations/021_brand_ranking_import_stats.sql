-- ============================================================
-- Migration 021: 브랜드 랭킹 임포트 커버리지(원본/유효 건수) 저장 테이블
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

CREATE TABLE IF NOT EXISTS public.brand_ranking_import_stats (
    brand_name                 TEXT PRIMARY KEY,
    raw_count                  INTEGER NOT NULL DEFAULT 0,  -- 원본 시트/Apify 수집 건수
    kept_count                 INTEGER NOT NULL DEFAULT 0,  -- 필터링 후 실제 저장된 건수
    excluded_dupes             INTEGER DEFAULT 0,           -- 중복 id 제거 건수
    excluded_required_keyword  INTEGER DEFAULT 0,           -- --require-keywords 로 제외된 건수
    excluded_keyword           INTEGER DEFAULT 0,           -- --exclude-keywords 로 제외된 건수
    imported_at                TIMESTAMPTZ DEFAULT NOW()
);

-- 확인 쿼리:
-- SELECT brand_name, raw_count, kept_count,
--        ROUND(kept_count::numeric / NULLIF(raw_count, 0) * 100, 1) AS coverage_pct
-- FROM public.brand_ranking_import_stats ORDER BY brand_name;
