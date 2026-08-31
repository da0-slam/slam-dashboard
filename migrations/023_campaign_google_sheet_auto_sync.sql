-- ============================================================
-- Migration 023: 캠페인 구글시트 자동 동기화 설정
--
-- 콘텐츠 성과 관리의 "구글시트 데이터 이관"은 지금까지 수동으로 URL을
-- 붙여넣고 버튼을 눌러야 했다. 캠페인별로 시트 URL과 자동 동기화 여부를
-- 저장해두면, 별도 스케줄러(scripts/sync_google_sheets.py, GitHub Actions
-- 매일 실행)가 이 값을 읽어 자동으로 다시 가져올 수 있다.
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

ALTER TABLE public.campaigns
  ADD COLUMN IF NOT EXISTS google_sheet_url TEXT,
  ADD COLUMN IF NOT EXISTS google_sheet_auto_sync BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS google_sheet_last_synced_at TIMESTAMPTZ;
