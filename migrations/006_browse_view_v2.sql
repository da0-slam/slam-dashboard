-- browse 뷰 v2: 평균조회수 + us_db 팔로워 추가
CREATE OR REPLACE VIEW public.v_browse_contents AS
WITH avg_plays AS (
    SELECT influencer_id,
           ROUND(AVG(play_count)) AS avg_play_count
    FROM public.koc_contents
    GROUP BY influencer_id
),
top_content AS (
    SELECT DISTINCT ON (influencer_id)
        influencer_id, video_url, thumbnail_url, play_count,
        like_count, comment_count, share_count, save_count, caption, posted_at
    FROM public.koc_contents
    ORDER BY influencer_id, play_count DESC NULLS LAST
)
SELECT
    tc.influencer_id,
    tc.video_url,
    tc.thumbnail_url,
    tc.play_count,
    tc.like_count,
    tc.comment_count,
    tc.share_count,
    tc.save_count,
    tc.caption,
    tc.posted_at,
    i.account_url,
    i.platform,
    i.cover_url,
    i.instagram_url,
    i.instagram_followers,
    ap.avg_play_count,
    u.followers AS us_db_followers
FROM top_content tc
LEFT JOIN public.influencer_master i USING (influencer_id)
LEFT JOIN avg_plays ap USING (influencer_id)
LEFT JOIN public.us_db u ON LOWER(u."influencer_ID") = LOWER(tc.influencer_id);
