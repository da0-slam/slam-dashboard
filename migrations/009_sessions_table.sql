-- 서버 재시작 후에도 로그인 유지를 위한 세션 영구 저장 테이블

CREATE TABLE IF NOT EXISTS public.slam_sessions (
    id          TEXT PRIMARY KEY,
    refresh_token TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days')
);

-- 서비스 키만 접근 가능 (공개 접근 차단)
ALTER TABLE public.slam_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service only" ON public.slam_sessions FOR ALL USING (false);

-- 만료된 세션 자동 정리 (선택)
-- CREATE INDEX IF NOT EXISTS slam_sessions_expires_idx ON public.slam_sessions (expires_at);
