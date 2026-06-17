-- post_comments: 외부에서 스크랩한 게시물 댓글 저장
CREATE TABLE IF NOT EXISTS post_comments (
  id              TEXT PRIMARY KEY,
  aweme_id        TEXT NOT NULL,          -- TikTok 영상 ID (campaign_posts.post_url 에서 추출)
  text            TEXT,
  created_at      TIMESTAMPTZ,
  like_count      INT  DEFAULT 0,
  reply_count     INT  DEFAULT 0,
  language        TEXT,
  is_author_liked BOOLEAN DEFAULT FALSE,
  user_id         TEXT,
  username        TEXT,
  display_name    TEXT,
  avatar_url      TEXT,
  user_region     TEXT,
  imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_post_comments_aweme_id ON post_comments(aweme_id);
