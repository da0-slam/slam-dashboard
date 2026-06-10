-- browse 뷰 v4: 썸네일 있는 영상을 0순위로 우선 선택
-- 0순위: supabase storage에 업로드된 썸네일 존재 여부
-- 1순위: 뷰티 키워드 포함 여부
-- 2순위: ER
-- 3순위: 조회수

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
    ORDER BY
        influencer_id,
        -- 0순위: 유효한 썸네일(supabase storage)이 있는 영상 우선
        CASE WHEN thumbnail_url LIKE '%supabase%' THEN 0 ELSE 1 END ASC,
        -- 1순위: 뷰티/스킨케어 키워드
        CASE WHEN LOWER(COALESCE(caption, '')) ~
            '(skincare|skin care|skin routine|makeup|make up|grwm|get ready with me|beauty routine|foundation|concealer|moisturizer|serum|cleanser|toner|blush|lipstick|eyeshadow|mascara|primer|highlighter|contour|bronzer|night routine|morning routine|화장|스킨케어|메이크업|뷰티|파운데이션|립스틱|아이섀도|마스카라|세럼|토너|루틴|클렌징|겟레디위드미)'
        THEN 1 ELSE 0 END DESC,
        -- 2순위: ER
        CASE WHEN play_count > 0
        THEN (COALESCE(like_count,0) + COALESCE(comment_count,0) + COALESCE(share_count,0) + COALESCE(save_count,0))::float / play_count
        ELSE 0 END DESC,
        -- 3순위: 조회수
        play_count DESC NULLS LAST
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
LEFT JOIN public."US_DB" u ON LOWER(u."influencer_ID") = LOWER(tc.influencer_id);
