-- influencer_master에 Instagram 정보 컬럼 추가
ALTER TABLE public.influencer_master
  ADD COLUMN IF NOT EXISTS instagram_url       TEXT,
  ADD COLUMN IF NOT EXISTS instagram_followers BIGINT;

-- browse 뷰에 신규 컬럼 포함
CREATE OR REPLACE VIEW public.v_browse_contents AS
SELECT DISTINCT ON (k.influencer_id)
    k.influencer_id,
    k.video_url,
    k.thumbnail_url,
    k.play_count,
    k.like_count,
    k.comment_count,
    k.share_count,
    k.save_count,
    k.caption,
    k.posted_at,
    i.account_url,
    i.platform,
    i.cover_url,
    i.instagram_url,
    i.instagram_followers
FROM public.koc_contents k
LEFT JOIN public.influencer_master i USING (influencer_id)
ORDER BY k.influencer_id, k.play_count DESC NULLS LAST;
