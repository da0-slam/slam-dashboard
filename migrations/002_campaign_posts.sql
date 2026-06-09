-- ============================================================
-- Migration 002: campaign_posts 테이블 생성 (콘텐츠 성과 관리)
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
--
-- 설계 원칙:
--   · 게시물 1개당 1row (platform 독립 저장)
--   · campaign_selections(participant_id)와 선택적 연결 (nullable)
--   · influencer_id는 influencer_master 연결 가능하나 선택적 (수동 입력 허용)
--   · brand_id 직접 보유로 RLS 단순화 및 쿼리 성능 향상
--   · post_url UNIQUE 제약으로 중복 등록 방지
-- ============================================================


-- ─── 1. campaign_posts 테이블 생성 ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.campaign_posts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id        UUID        NOT NULL REFERENCES public.brands(id) ON DELETE CASCADE,
    campaign_id     UUID        NOT NULL REFERENCES public.campaigns(id) ON DELETE CASCADE,
    participant_id  UUID        REFERENCES public.campaign_selections(id) ON DELETE SET NULL,
    influencer_id   TEXT,       -- influencer_master 연결 (nullable, 수동 입력 허용)
    influencer_name TEXT        NOT NULL,
    platform        TEXT        NOT NULL CHECK (platform IN ('instagram', 'tiktok')),
    post_url        TEXT        NOT NULL,
    upload_date     DATE,
    views           BIGINT      NOT NULL DEFAULT 0,
    likes           BIGINT      NOT NULL DEFAULT 0,
    comments        BIGINT      NOT NULL DEFAULT 0,
    saves           BIGINT      NOT NULL DEFAULT 0,
    shares          BIGINT      NOT NULL DEFAULT 0,
    last_tracked_at TIMESTAMPTZ,         -- Apify 자동 갱신 시 업데이트
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT campaign_posts_post_url_unique UNIQUE (post_url)
);

COMMENT ON TABLE  public.campaign_posts IS '캠페인별 인플루언서 게시물 성과 추적. 게시물 1개 = 1row (플랫폼 독립).';
COMMENT ON COLUMN public.campaign_posts.participant_id  IS '캠페인 참여자(campaign_selections) 연결. 과거 데이터 이관 시 null 가능.';
COMMENT ON COLUMN public.campaign_posts.influencer_id   IS 'influencer_master 연결용. Apify 자동 트래킹 시 활용.';
COMMENT ON COLUMN public.campaign_posts.last_tracked_at IS 'Apify 자동 갱신 마지막 시각. 수동 입력 시 null.';


-- ─── 2. 인덱스 ───────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_campaign_posts_brand_id
    ON public.campaign_posts(brand_id);

CREATE INDEX IF NOT EXISTS idx_campaign_posts_campaign_id
    ON public.campaign_posts(campaign_id);

CREATE INDEX IF NOT EXISTS idx_campaign_posts_brand_campaign
    ON public.campaign_posts(brand_id, campaign_id);

CREATE INDEX IF NOT EXISTS idx_campaign_posts_influencer_id
    ON public.campaign_posts(influencer_id)
    WHERE influencer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_campaign_posts_platform
    ON public.campaign_posts(platform);

CREATE INDEX IF NOT EXISTS idx_campaign_posts_upload_date
    ON public.campaign_posts(upload_date DESC NULLS LAST);


-- ─── 3. updated_at 자동 갱신 트리거 ──────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_campaign_posts_updated_at ON public.campaign_posts;
CREATE TRIGGER trg_campaign_posts_updated_at
    BEFORE UPDATE ON public.campaign_posts
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();


-- ─── 4. Row Level Security ───────────────────────────────────────────────────
-- 현재 앱은 service_role 키를 사용하므로 RLS가 우회됩니다.
-- Python 코드에서 brand_id 조건으로 직접 필터링합니다.
-- 아래 정책은 anon 키로 전환 시 즉시 활성화됩니다.

ALTER TABLE public.campaign_posts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "cp_select_own_brand" ON public.campaign_posts;
CREATE POLICY "cp_select_own_brand"
ON public.campaign_posts FOR SELECT
USING (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

DROP POLICY IF EXISTS "cp_insert_own_brand" ON public.campaign_posts;
CREATE POLICY "cp_insert_own_brand"
ON public.campaign_posts FOR INSERT
WITH CHECK (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

DROP POLICY IF EXISTS "cp_update_own_brand" ON public.campaign_posts;
CREATE POLICY "cp_update_own_brand"
ON public.campaign_posts FOR UPDATE
USING (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
)
WITH CHECK (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

DROP POLICY IF EXISTS "cp_delete_own_brand" ON public.campaign_posts;
CREATE POLICY "cp_delete_own_brand"
ON public.campaign_posts FOR DELETE
USING (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

-- 관리자 전체 접근 정책
DROP POLICY IF EXISTS "cp_admin_all" ON public.campaign_posts;
CREATE POLICY "cp_admin_all"
ON public.campaign_posts FOR ALL
USING (
    EXISTS (
        SELECT 1 FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND role = 'admin'
    )
);


-- ─── 5. 확인 쿼리 ────────────────────────────────────────────────────────────
-- SELECT tablename, policyname, cmd
-- FROM pg_policies
-- WHERE tablename = 'campaign_posts'
-- ORDER BY policyname;
