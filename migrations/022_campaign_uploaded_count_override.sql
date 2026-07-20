-- ============================================================
-- Migration 022: 캠페인 업로드 인원 수동 보정 필드
--
-- "업로드 인원"은 campaign_posts.influencer_name의 고유값 개수로 자동
-- 계산되는데, influencer_id/participant_id가 연결되지 않은 채 이름
-- 문자열만으로 집계되다 보니 같은 사람이 다른 표기로 여러 번 들어간
-- 경우를 구분하지 못해 실제 인원보다 부풀려질 수 있음 (2026-07-20 실사례:
-- 계산값 227명, 실제 확인된 인원 192명). participant_count(발송 인원)와
-- 동일한 패턴으로 수동 보정값을 저장해, 있으면 계산값 대신 이 값을 표시.
--
-- 적용 방법: Supabase 대시보드 → SQL Editor에서 이 파일 내용 전체 실행
-- ============================================================

ALTER TABLE public.campaigns
  ADD COLUMN IF NOT EXISTS uploaded_count_override INTEGER;
