-- ============================================================
-- Migration 018: 브랜드당 여러 개의 전략(콘텐츠 가이드) 문서 지원
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

ALTER TABLE public.brand_strategy ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE public.brand_strategy ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 기존 행(브랜드당 1개였던 문서)에 기본 이름 부여 — 기존 링크/데이터 그대로 유지됨
UPDATE public.brand_strategy SET name = '기본 가이드' WHERE name IS NULL;
UPDATE public.brand_strategy SET created_at = updated_at WHERE created_at IS NULL;

ALTER TABLE public.brand_strategy_files
  ADD COLUMN IF NOT EXISTS strategy_id UUID REFERENCES public.brand_strategy(id) ON DELETE CASCADE;

-- brand_id UNIQUE 제약 제거 — 이게 있으면 브랜드당 문서 1개로 계속 제한됨
-- (제약 이름은 Supabase가 테이블 생성 시 자동 부여한 것으로, information_schema로 실제 이름 확인 후 실행 권장)
ALTER TABLE public.brand_strategy DROP CONSTRAINT IF EXISTS brand_strategy_brand_id_key;

-- 확인 쿼리:
-- SELECT id, brand_id, name, created_at, updated_at FROM public.brand_strategy;
-- SELECT conname FROM pg_constraint WHERE conrelid = 'public.brand_strategy'::regclass;