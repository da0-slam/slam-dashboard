-- post_comments에 Instagram 지원을 위한 컬럼 추가
ALTER TABLE post_comments
  ADD COLUMN IF NOT EXISTS post_url  TEXT,   -- Instagram post URL (TT는 NULL)
  ADD COLUMN IF NOT EXISTS platform  TEXT DEFAULT 'tiktok';

CREATE INDEX IF NOT EXISTS idx_post_comments_post_url ON post_comments(post_url);

-- 기존 TikTok 댓글 platform 값 채우기
UPDATE post_comments SET platform = 'tiktok' WHERE platform IS NULL OR platform = '';
