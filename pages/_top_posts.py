"""전체 브랜드 · 진행중 캠페인의 우수 게시물 취합 (관리자 전용, 비노출 내부 도구)."""
import pandas as pd
import streamlit as st

from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    get_all_campaigns, get_campaign_posts_for_campaigns, get_brands, get_user_profile,
)

st.set_page_config(page_title="우수 게시물 취합", page_icon="⭐", layout="wide")

user = require_auth()
sidebar_user_info()

profile = get_user_profile(user.id)
if not profile or profile.get("role") != "admin":
    st.error("관리자 전용 페이지입니다.")
    st.stop()

st.title("⭐ 우수 게시물 취합 (전체 브랜드 · 진행중 캠페인)")
st.caption("브랜드사에는 노출되지 않는 내부 확인용 페이지입니다.")

if st.button("🔄 새로고침"):
    st.rerun()

# ── 기준값 ────────────────────────────────────────────────────────────────────
st.markdown("#### 기준 (아래 중 하나라도 충족하면 포함 · OR 조건)")
c1, c2, c3 = st.columns(3)
min_views    = c1.number_input("조회수 ≥", min_value=0, value=1000, step=100)
min_likes    = c2.number_input("좋아요 ≥", min_value=0, value=50, step=10)
min_comments = c3.number_input("댓글 ≥", min_value=0, value=20, step=5)

st.divider()

# ── 데이터 취합 ───────────────────────────────────────────────────────────────
active_campaigns = get_all_campaigns(status="active")
if not active_campaigns:
    st.info("진행중(active) 상태인 캠페인이 없습니다.")
    st.stop()

campaign_map = {c["id"]: c for c in active_campaigns}
brands = get_brands()
brand_map = {b["id"]: b["name"] for b in brands}

posts = get_campaign_posts_for_campaigns(list(campaign_map.keys()))

qualifying = [
    p for p in posts
    if (p.get("views") or 0) >= min_views
    or (p.get("likes") or 0) >= min_likes
    or (p.get("comments") or 0) >= min_comments
]

m1, m2, m3, m4 = st.columns(4)
m1.metric("기준 충족 게시물", f"{len(qualifying):,}")
m2.metric("대상 캠페인", f"{len(active_campaigns):,}")
m3.metric("관련 브랜드", f"{len({campaign_map[p['campaign_id']]['brand_id'] for p in qualifying if p.get('campaign_id') in campaign_map}):,}")
m4.metric("전체 진행중 게시물", f"{len(posts):,}")

st.divider()

if not qualifying:
    st.info("기준을 충족하는 게시물이 없습니다. 기준값을 낮춰보세요.")
    st.stop()

_plat_map = {"instagram": "Instagram", "tiktok": "TikTok", "x": "X", "xiaohongshu": "샤오홍슈", "other": "기타"}

rows = []
for p in qualifying:
    camp = campaign_map.get(p.get("campaign_id"), {})
    rows.append({
        "브랜드": brand_map.get(camp.get("brand_id"), "–"),
        "캠페인": camp.get("name", "–"),
        "인플루언서": p.get("influencer_name", ""),
        "플랫폼": _plat_map.get(p.get("platform"), p.get("platform") or "–"),
        "게시물 URL": p.get("post_url", ""),
        "조회수": p.get("views") or 0,
        "좋아요": p.get("likes") or 0,
        "댓글": p.get("comments") or 0,
        "저장": p.get("saves") or 0,
        "공유": p.get("shares") or 0,
        "업로드일": p.get("upload_date") or "",
    })

df = pd.DataFrame(rows).sort_values("조회수", ascending=False)

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "게시물 URL": st.column_config.LinkColumn("게시물 URL", display_text="🔗 열기"),
        "조회수": st.column_config.NumberColumn(format="%d"),
        "좋아요": st.column_config.NumberColumn(format="%d"),
        "댓글": st.column_config.NumberColumn(format="%d"),
        "저장": st.column_config.NumberColumn(format="%d"),
        "공유": st.column_config.NumberColumn(format="%d"),
    },
)

st.download_button(
    "⬇️ CSV로 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name="우수_게시물_취합.csv",
    mime="text/csv",
)
