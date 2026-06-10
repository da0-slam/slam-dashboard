-- 브라우즈 페이지 성능 최적화
-- 인플루언서당 최고 조회수 영상 1개만 + influencer_master 조인을 DB에서 처리
-- Python 중복 제거 루프 제거, API 쿼리 수 대폭 감소

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
    i.cover_url
FROM public.koc_contents k
LEFT JOIN public.influencer_master i USING (influencer_id)
ORDER BY k.influencer_id, k.play_count DESC NULLS LAST;
