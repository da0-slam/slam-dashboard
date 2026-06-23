"""공개 전략 문서 뷰어 — 로그인 없이 토큰 링크로 접근 가능."""
import streamlit as st
import hmac
import hashlib
import os
import re

st.set_page_config(page_title="전략 문서", page_icon="📋", layout="wide")

from utils.supabase_client import get_brand_strategy, get_brands  # noqa: E402 (after set_page_config)

# ── 파라미터 검증 ─────────────────────────────────────────────────────────────
params = st.query_params
brand_id = params.get("brand", "")
token    = params.get("token", "")

if not brand_id or not token:
    st.error("유효하지 않은 링크입니다.")
    st.stop()

_secret = (os.environ.get("SUPABASE_KEY") or "slam-strategy-fallback").encode()
_expected = hmac.new(_secret, brand_id.encode(), hashlib.sha256).hexdigest()[:24]

if not hmac.compare_digest(token, _expected):
    st.error("링크가 만료되었거나 유효하지 않습니다.")
    st.stop()

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _load_brand_name(bid: str) -> str:
    try:
        brands = get_brands()
        return next((b["name"] for b in brands if b["id"] == bid), bid)
    except Exception:
        return bid

@st.cache_data(ttl=60, show_spinner=False)
def _load_strategy(bid: str) -> dict:
    return get_brand_strategy(bid) or {}

brand_name = _load_brand_name(brand_id)
data = _load_strategy(brand_id)

# ── YouTube 임베드 렌더러 ─────────────────────────────────────────────────────
_YT_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s)]*v=|youtu\.be/)([\w-]+)(?:[^\s)]*)?'
)


def _render_with_videos(content: str):
    lines = content.split("\n")
    buf: list[str] = []
    for line in lines:
        m = _YT_RE.search(line)
        if m:
            if buf:
                st.markdown("\n".join(buf), unsafe_allow_html=True)
                buf = []
            video_id = m.group(1)
            st.markdown(
                f'<iframe width="100%" height="380" '
                f'src="https://www.youtube.com/embed/{video_id}" '
                f'frameborder="0" allowfullscreen '
                f'style="border-radius:8px;margin:8px 0;display:block;"></iframe>',
                unsafe_allow_html=True,
            )
        else:
            buf.append(line)
    if buf:
        st.markdown("\n".join(buf), unsafe_allow_html=True)


# ── 렌더링 ────────────────────────────────────────────────────────────────────
st.markdown(
    "<p style='color:#888;font-size:0.8em;margin-bottom:0'>SLAM 플랫폼 — 공유된 전략 문서</p>",
    unsafe_allow_html=True,
)
st.title(f"📋 {brand_name} 전략 문서")
st.divider()

brand_guide    = data.get("brand_guide") or ""
campaign_goals = data.get("campaign_goals") or ""
competitor_refs = data.get("competitor_refs") or ""

if not any([brand_guide, campaign_goals, competitor_refs]):
    st.info("아직 전략 문서 내용이 없습니다.")
    st.stop()

if brand_guide.strip():
    st.subheader("📖 브랜드 가이드")
    _render_with_videos(brand_guide)
    st.divider()

if campaign_goals.strip():
    st.subheader("🎯 캠페인 목표")
    _render_with_videos(campaign_goals)
    st.divider()

if competitor_refs.strip():
    st.subheader("🔍 경쟁사 레퍼런스")
    _render_with_videos(competitor_refs)
