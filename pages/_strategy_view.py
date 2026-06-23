"""공개 전략 문서 뷰어 — 토큰 링크로 로그인 없이 접근 가능."""
import streamlit as st
import re
import streamlit.components.v1 as _components

st.set_page_config(page_title="전략 문서", page_icon="📋", layout="wide")

from utils.storage_client import resolve_strategy_token   # noqa: E402
from utils.supabase_client import get_brand_strategy, get_brands  # noqa: E402

# ── 토큰 검증 ─────────────────────────────────────────────────────────────────
token = st.query_params.get("token", "")
if not token:
    st.error("유효하지 않은 링크입니다.")
    st.stop()

with st.spinner("불러오는 중..."):
    brand_id = resolve_strategy_token(token)

if not brand_id:
    st.error("링크가 만료되었거나 유효하지 않습니다.")
    st.stop()

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _brand_name(bid: str) -> str:
    try:
        return next((b["name"] for b in get_brands() if b["id"] == bid), bid)
    except Exception:
        return bid

@st.cache_data(ttl=60, show_spinner=False)
def _strategy(bid: str) -> dict:
    return get_brand_strategy(bid) or {}

brand_name = _brand_name(brand_id)
data = _strategy(brand_id)

# ── 영상 임베드 렌더러 ────────────────────────────────────────────────────────
_TT_RE = re.compile(r'https?://(?:www\.)?tiktok\.com/@[\w.]+/video/(\d+)')
_IG_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/([\w-]+)/?')


def _render(content: str):
    lines = content.split("\n")
    buf: list[str] = []
    for line in lines:
        tt = _TT_RE.search(line)
        ig = _IG_RE.search(line)
        if tt or ig:
            if buf:
                st.markdown("\n".join(buf), unsafe_allow_html=True)
                buf = []
            if tt:
                _components.html(
                    f'<iframe src="https://www.tiktok.com/embed/v2/{tt.group(1)}" '
                    f'width="325" height="700" frameborder="0" allowfullscreen></iframe>',
                    height=720,
                )
            else:
                _components.html(
                    f'<iframe src="https://www.instagram.com/p/{ig.group(1)}/embed/" '
                    f'width="400" height="480" frameborder="0" scrolling="no" '
                    f'allowtransparency="true"></iframe>',
                    height=500,
                )
        else:
            buf.append(line)
    if buf:
        st.markdown("\n".join(buf), unsafe_allow_html=True)


# ── 렌더링 ────────────────────────────────────────────────────────────────────
st.markdown(
    "<p style='color:#aaa;font-size:0.75em;margin-bottom:4px'>SLAM — 공유된 전략 문서</p>",
    unsafe_allow_html=True,
)
st.title(f"📋 {brand_name} 전략 문서")
st.divider()

brand_guide     = data.get("brand_guide") or ""
campaign_goals  = data.get("campaign_goals") or ""
competitor_refs = data.get("competitor_refs") or ""

if not any([brand_guide.strip(), campaign_goals.strip(), competitor_refs.strip()]):
    st.info("아직 전략 문서 내용이 없습니다.")
    st.stop()

if brand_guide.strip():
    st.subheader("📖 브랜드 가이드")
    _render(brand_guide)
    st.divider()

if campaign_goals.strip():
    st.subheader("🎯 캠페인 목표")
    _render(campaign_goals)
    st.divider()

if competitor_refs.strip():
    st.subheader("🔍 경쟁사 레퍼런스")
    _render(competitor_refs)
