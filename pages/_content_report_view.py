"""공개 콘텐츠 성과 리포트 뷰어 — 토큰 링크로 로그인 없이 접근 가능.
읽기 전용 — 게시물 관리/댓글 등 편집 기능은 포함하지 않음."""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="콘텐츠 성과 리포트", page_icon="📊", layout="wide")

from utils.storage_client import resolve_content_report_token  # noqa: E402
from utils.supabase_client import (  # noqa: E402
    get_brands, get_campaigns, get_campaign_posts, get_influencer_cover_map,
)

# ── 토큰 검증 ─────────────────────────────────────────────────────────────────
token = st.query_params.get("token", "")
if not token:
    st.error("유효하지 않은 링크입니다.")
    st.stop()

with st.spinner("불러오는 중..."):
    resolved = resolve_content_report_token(token)

if not resolved:
    st.error("링크가 만료되었거나 유효하지 않습니다.")
    st.stop()

brand_id = resolved["brand_id"]
campaign_id = resolved["campaign_id"]


# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _brand_name(bid: str) -> str:
    try:
        return next((b["name"] for b in get_brands() if b["id"] == bid), bid)
    except Exception:
        return bid


@st.cache_data(ttl=60, show_spinner=False)
def _campaign(bid: str, cid: str) -> dict | None:
    return next((c for c in get_campaigns(bid) if c["id"] == cid), None)


@st.cache_data(ttl=60, show_spinner=False)
def _posts(cid: str) -> list[dict]:
    return get_campaign_posts(brand_id=brand_id, campaign_id=cid)


camp = _campaign(brand_id, campaign_id)
if not camp:
    st.error("캠페인을 찾을 수 없습니다. 링크가 삭제된 캠페인을 가리키고 있을 수 있습니다.")
    st.stop()

brand_name = _brand_name(brand_id)


def _er(p: dict) -> float:
    v = p.get("views") or 0
    if v <= 0:
        return 0.0
    return round((p.get("likes", 0) + p.get("comments", 0) +
                  p.get("saves", 0) + p.get("shares", 0)) / v * 100, 2)


raw = _posts(campaign_id)
posts = [{**p, "engagement_rate": _er(p)} for p in raw]
df = pd.DataFrame(posts) if posts else pd.DataFrame(columns=[
    "id", "influencer_name", "platform", "post_url", "views", "likes",
    "comments", "saves", "shares", "engagement_rate",
])

# ── 렌더링 ────────────────────────────────────────────────────────────────────
st.markdown(
    "<p style='color:#aaa;font-size:0.75em;margin-bottom:4px'>SLAM — 공유된 콘텐츠 성과 리포트</p>",
    unsafe_allow_html=True,
)
st.title(f"📊 {brand_name} · {camp['name']}")
st.divider()

if df.empty:
    st.info("아직 등록된 게시물 데이터가 없습니다.")
    st.stop()

# ── KPI ───────────────────────────────────────────────────────────────────
_HDR = {
    "name", "full name", "인플루언서", "인플루언서명", "influencer",
    "influencer_name", "이름", "계정", "아이디", "id",
}
_df_valid = df[
    df["influencer_name"].str.strip().str.lower()
    .apply(lambda x: x not in _HDR and x != "")
]
_computed_influencers = _df_valid["influencer_name"].nunique()
_override = camp.get("uploaded_count_override")
total_influencers = _override if _override is not None else _computed_influencers

total_posts    = len(df)
ig_posts       = int((df["platform"] == "instagram").sum())
tt_posts       = int((df["platform"] == "tiktok").sum())
total_views    = int(df["views"].sum())
total_likes    = int(df["likes"].sum())
total_comments = int(df["comments"].sum())
total_saves    = int(df["saves"].sum())
total_shares   = int(df["shares"].sum())
avg_er         = round(float(df["engagement_rate"].mean()), 2)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("참여 인플루언서", f"{total_influencers:,}")
c2.metric("총 게시물", f"{total_posts:,}")
c3.metric("Instagram", f"{ig_posts:,}")
c4.metric("TikTok", f"{tt_posts:,}")
c5.metric("평균 참여율", f"{avg_er:.1f}%")

c6, c7, c8, c9 = st.columns(4)
c6.metric("총 조회수", f"{total_views:,}")
c7.metric("총 좋아요", f"{total_likes:,}")
c8.metric("총 댓글", f"{total_comments:,}")
c9.metric("총 저장", f"{total_saves:,}")

p_count = camp.get("participant_count")
if p_count:
    u_rate = round(total_influencers / p_count * 100, 1)
    st.divider()
    ur1, ur2, ur3 = st.columns(3)
    ur1.metric("📦 발송 인원", f"{p_count:,}명")
    ur2.metric("📤 업로드 인원", f"{total_influencers:,}명")
    ur3.metric("📊 업로드율", f"{u_rate:.1f}%")

st.divider()

# ── 인플루언서별 성과 요약 ────────────────────────────────────────────────
st.subheader("인플루언서별 성과 요약")
grp = (
    _df_valid.groupby("influencer_name")
    .agg(
        총_게시물=("id", "count"),
        총_조회수=("views", "sum"),
        총_좋아요=("likes", "sum"),
        총_댓글=("comments", "sum"),
        총_저장=("saves", "sum"),
        평균_참여율=("engagement_rate", "mean"),
    )
    .reset_index()
)
grp["평균_참여율"] = grp["평균_참여율"].round(2)

_cover = get_influencer_cover_map()
grp["커버"] = grp["influencer_name"].apply(lambda n: _cover.get(n.lower()))
grp = grp.sort_values("총_조회수", ascending=False)
grp.rename(columns={
    "influencer_name": "인플루언서", "총_게시물": "총 게시물", "총_조회수": "총 조회수",
    "총_좋아요": "총 좋아요", "총_댓글": "총 댓글", "총_저장": "총 저장",
    "평균_참여율": "평균 참여율(%)",
}, inplace=True)
grp = grp[["커버"] + [c for c in grp.columns if c != "커버"]]

st.dataframe(
    grp, use_container_width=True, hide_index=True,
    column_config={
        "커버": st.column_config.ImageColumn("커버", width="small"),
        "평균 참여율(%)": st.column_config.NumberColumn("평균 참여율(%)", format="%.2f%%"),
    },
)

st.divider()

# ── 우수 콘텐츠 ─────────────────────────────────────────────────────────────
st.subheader("⭐ 우수 콘텐츠")


def _top5(title: str, col: str) -> None:
    st.markdown(f"#### {title}")
    top = (
        df.nlargest(5, col)
        [["influencer_name", "platform", "post_url", "views", "engagement_rate", "saves", "comments"]]
        .copy()
    )
    top["platform"] = top["platform"].map({"instagram": "Instagram", "tiktok": "TikTok"})
    top.rename(columns={
        "influencer_name": "인플루언서", "platform": "플랫폼", "post_url": "게시물 URL",
        "views": "조회수", "engagement_rate": "참여율(%)", "saves": "저장", "comments": "댓글",
    }, inplace=True)
    st.dataframe(
        top, use_container_width=True, hide_index=True,
        column_config={
            "게시물 URL": st.column_config.LinkColumn("게시물 URL", display_text="🔗 열기"),
            "참여율(%)": st.column_config.NumberColumn("참여율(%)", format="%.2f%%"),
        },
    )


col_a, col_b = st.columns(2)
with col_a:
    _top5("조회수 TOP 5", "views")
with col_b:
    _top5("참여율 TOP 5", "engagement_rate")
