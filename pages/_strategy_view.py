"""공개 전략 문서 뷰어 — 토큰 링크로 로그인 없이 접근 가능."""
import streamlit as st
import re
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


def _embed_html(platform: str, vid_id: str) -> str:
    if platform == "tiktok":
        return (
            f'<iframe src="https://www.tiktok.com/embed/v2/{vid_id}" '
            f'style="width:100%;height:700px;border:none;" allowfullscreen></iframe>'
        )
    return (
        f'<iframe src="https://www.instagram.com/p/{vid_id}/embed/" '
        f'style="width:100%;height:560px;border:none;" scrolling="no" allowtransparency="true"></iframe>'
    )


def _render(content: str):
    """마크다운 렌더링 — TikTok/Instagram URL은 2열 그리드로 임베드."""
    segments: list[tuple] = []
    buf: list[str] = []
    for line in content.split("\n"):
        tt = _TT_RE.search(line)
        ig = _IG_RE.search(line)
        if tt or ig:
            if buf:
                segments.append(("text", "\n".join(buf)))
                buf = []
            segments.append(("video", "tiktok" if tt else "instagram", tt.group(1) if tt else ig.group(1)))
        else:
            buf.append(line)
    if buf:
        segments.append(("text", "\n".join(buf)))

    i = 0
    while i < len(segments):
        seg = segments[i]
        if seg[0] == "text":
            st.markdown(seg[1], unsafe_allow_html=True)
            i += 1
        else:
            videos = []
            while i < len(segments):
                if segments[i][0] == "video":
                    videos.append(segments[i])
                    i += 1
                elif segments[i][0] == "text" and segments[i][1].strip() == "":
                    i += 1
                else:
                    break
            for j in range(0, len(videos), 2):
                pair = videos[j : j + 2]
                cols = st.columns(len(pair))
                for k, (_, platform, vid_id) in enumerate(pair):
                    with cols[k]:
                        st.markdown(_embed_html(platform, vid_id), unsafe_allow_html=True)


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
