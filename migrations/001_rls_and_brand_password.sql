-- ============================================================
-- Migration 001: 캠페인 브랜드별 접근 권한 강화
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
--
-- 주의: 현재 앱은 service_role 키를 사용하므로 RLS가 우회됩니다.
--       RLS를 DB 레벨에서 실제로 적용하려면 Supabase anon 키로 전환하고
--       각 요청에 사용자 JWT를 Authorization 헤더로 전달해야 합니다.
--       아래 정책은 anon 키 또는 사용자 JWT 기반 클라이언트 사용 시 유효합니다.
--       service_role 키 환경에서도 정책을 미리 생성해두면
--       나중에 anon 키로 전환 시 즉시 적용됩니다.
-- ============================================================


-- ─── 1. brands 테이블: 캠페인 관리 비밀번호 해시 컬럼 추가 ───────────────────
ALTER TABLE public.brands
  ADD COLUMN IF NOT EXISTS access_password_hash TEXT;


-- ─── 2. campaigns 테이블 RLS ─────────────────────────────────────────────────
ALTER TABLE public.campaigns ENABLE ROW LEVEL SECURITY;

-- 기존 정책 제거 (재실행 안전)
DROP POLICY IF EXISTS "campaigns_select_own_brand" ON public.campaigns;
DROP POLICY IF EXISTS "campaigns_insert_own_brand" ON public.campaigns;
DROP POLICY IF EXISTS "campaigns_update_own_brand" ON public.campaigns;
DROP POLICY IF EXISTS "campaigns_delete_own_brand"  ON public.campaigns;

-- SELECT: 자신의 브랜드에 속한 캠페인만 조회
CREATE POLICY "campaigns_select_own_brand"
ON public.campaigns FOR SELECT
USING (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

-- INSERT: 자신의 브랜드로만 캠페인 생성
CREATE POLICY "campaigns_insert_own_brand"
ON public.campaigns FOR INSERT
WITH CHECK (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

-- UPDATE: 자신의 브랜드 캠페인만 수정
CREATE POLICY "campaigns_update_own_brand"
ON public.campaigns FOR UPDATE
USING (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);

-- DELETE: 자신의 브랜드 캠페인만 삭제
CREATE POLICY "campaigns_delete_own_brand"
ON public.campaigns FOR DELETE
USING (
    brand_id IN (
        SELECT brand_id FROM public.user_profiles
        WHERE user_id = auth.uid()
          AND brand_id IS NOT NULL
    )
);


-- ─── 3. campaign_selections 테이블 RLS ───────────────────────────────────────
ALTER TABLE public.campaign_selections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "campaign_selections_select_own" ON public.campaign_selections;
DROP POLICY IF EXISTS "campaign_selections_insert_own" ON public.campaign_selections;
DROP POLICY IF EXISTS "campaign_selections_update_own" ON public.campaign_selections;
DROP POLICY IF EXISTS "campaign_selections_delete_own" ON public.campaign_selections;

-- 공통 서브쿼리: 현재 사용자의 브랜드에 속한 campaign_id 집합
-- SELECT
CREATE POLICY "campaign_selections_select_own"
ON public.campaign_selections FOR SELECT
USING (
    campaign_id IN (
        SELECT c.id FROM public.campaigns c
        JOIN public.user_profiles p ON p.brand_id = c.brand_id
        WHERE p.user_id = auth.uid()
          AND p.brand_id IS NOT NULL
    )
);

-- INSERT
CREATE POLICY "campaign_selections_insert_own"
ON public.campaign_selections FOR INSERT
WITH CHECK (
    campaign_id IN (
        SELECT c.id FROM public.campaigns c
        JOIN public.user_profiles p ON p.brand_id = c.brand_id
        WHERE p.user_id = auth.uid()
          AND p.brand_id IS NOT NULL
    )
);

-- UPDATE
CREATE POLICY "campaign_selections_update_own"
ON public.campaign_selections FOR UPDATE
USING (
    campaign_id IN (
        SELECT c.id FROM public.campaigns c
        JOIN public.user_profiles p ON p.brand_id = c.brand_id
        WHERE p.user_id = auth.uid()
          AND p.brand_id IS NOT NULL
    )
);

-- DELETE
CREATE POLICY "campaign_selections_delete_own"
ON public.campaign_selections FOR DELETE
USING (
    campaign_id IN (
        SELECT c.id FROM public.campaigns c
        JOIN public.user_profiles p ON p.brand_id = c.brand_id
        WHERE p.user_id = auth.uid()
          AND p.brand_id IS NOT NULL
    )
);


-- ─── 4. 확인 쿼리 (실행 후 결과 확인용) ──────────────────────────────────────
-- SELECT tablename, policyname, cmd, qual
-- FROM pg_policies
-- WHERE tablename IN ('campaigns', 'campaign_selections')
-- ORDER BY tablename, policyname;
