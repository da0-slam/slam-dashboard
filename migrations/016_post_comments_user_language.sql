ALTER TABLE post_comments
  ADD COLUMN IF NOT EXISTS user_language TEXT;
