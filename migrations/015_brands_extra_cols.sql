-- brands 테이블에 추가 메타데이터 컬럼 추가
ALTER TABLE brands
  ADD COLUMN IF NOT EXISTS category      TEXT,
  ADD COLUMN IF NOT EXISTS contact_name  TEXT,
  ADD COLUMN IF NOT EXISTS contact_email TEXT,
  ADD COLUMN IF NOT EXISTS notes         TEXT;
