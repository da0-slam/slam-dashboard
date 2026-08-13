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


def _camp_label(camp: dict) -> str:
    return f"{brand_map.get(camp.get('brand_id'), '–')} · {camp.get('name', '–')}"


# ── 필터 / 정렬 / 보기 방식 ───────────────────────────────────────────────────
f1, f2, f3 = st.columns([2.5, 1.3, 1.3])

_camp_options = {
    cid: _camp_label(c) for cid, c in campaign_map.items()
    if any(p.get("campaign_id") == cid for p in qualifying)
}
sel_camp_ids = f1.multiselect(
    "캠페인별 모아보기 (비워두면 전체)",
    list(_camp_options.keys()),
    format_func=lambda cid: _camp_options.get(cid, cid),
)

_sort_options = {"조회수": "views", "좋아요": "likes", "댓글": "comments", "저장": "saves", "공유": "shares"}
sort_label = f2.selectbox("정렬 기준", list(_sort_options.keys()))
sort_key = _sort_options[sort_label]

view_mode = f3.radio("보기 방식", ["그리드", "목록"], horizontal=True)

filtered = (
    [p for p in qualifying if p.get("campaign_id") in sel_camp_ids]
    if sel_camp_ids else qualifying
)
filtered = sorted(filtered, key=lambda p: p.get(sort_key) or 0, reverse=True)

st.caption(f"표시 중: {len(filtered):,}개")
st.divider()

# ── 그리드 / 목록 ─────────────────────────────────────────────────────────────


def _is_displayable_thumb(url) -> bool:
    if not url or not isinstance(url, str) or url != url:
        return False
    if "supabase" in url or "tiktokcdn" in url or "tiktok.com" in url:
        return True
    if "pbs.twimg.com" in url or "twimg.com" in url:
        return True
    try:
        from urllib.parse import urlparse as _p
        domain = _p(url).netloc
    except Exception:
        domain = url
    if any(d in domain for d in ("cdninstagram.com", "fbcdn.net", "scontent-")):
        return False
    return True


def _fmt(n) -> str:
    try:
        n = int(float(str(n)))
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.1f}K"
        return str(n)
    except Exception:
        return "-"


if view_mode == "그리드":
    _plat_colors = {"TikTok": "#010101", "Instagram": "#c13584", "X": "#1a8cd8", "샤오홍슈": "#ff2442", "기타": "#888888"}
    for idx, chunk_start in enumerate(range(0, len(filtered), 4)):
        chunk = filtered[chunk_start:chunk_start + 4]
        cols = st.columns(4)
        for cidx, (col, p) in enumerate(zip(cols, chunk)):
            camp = campaign_map.get(p.get("campaign_id"), {})
            plat = _plat_map.get(p.get("platform"), p.get("platform") or "기타")
            thumb = p.get("thumbnail_url") or ""
            url = p.get("post_url") or "#"
            name = p.get("influencer_name", "")
            plat_bg = _plat_colors.get(plat, "#555555")
            camp_label = _camp_label(camp)

            if _is_displayable_thumb(thumb):
                thumb_inner = f'<img src="{thumb}" style="width:100%;height:100%;object-fit:cover;display:block;">'
            else:
                thumb_inner = (
                    '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
                    'color:#888;font-size:28px;">🎬</div>'
                )

            col.markdown(f"""
<a href="{url}" target="_blank" style="text-decoration:none;display:block;margin-bottom:4px;">
  <div style="position:relative;border-radius:12px;overflow:hidden;background:#111;aspect-ratio:9/16;cursor:pointer;">
    {thumb_inner}
    <div style="position:absolute;bottom:0;left:0;right:0;
                background:linear-gradient(transparent,rgba(0,0,0,.85));
                padding:28px 10px 10px;">
      <p style="color:#fff;font-weight:700;font-size:13px;margin:0 0 4px;line-height:1.3;">{name}</p>
      <p style="color:rgba(255,255,255,.85);font-size:11px;margin:0;">
        👁 {_fmt(p.get('views'))} &nbsp;❤️ {_fmt(p.get('likes'))} &nbsp;💬 {_fmt(p.get('comments'))}
      </p>
    </div>
    <div style="position:absolute;top:8px;left:8px;background:{plat_bg};
                border-radius:5px;padding:2px 8px;color:#fff;font-size:10px;font-weight:700;">
      {plat}
    </div>
  </div>
</a>
<p style="font-size:11px;color:#888;margin:0 0 12px;">{camp_label}</p>
""", unsafe_allow_html=True)
else:
    rows = []
    for p in filtered:
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

    df = pd.DataFrame(rows)

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
