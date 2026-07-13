import io
import re
from datetime import date

import pandas as pd
import streamlit as st

from utils.auth import require_auth, sidebar_user_info, get_active_brand_id
from utils.storage_client import fetch_and_upload_thumbnail, upload_thumbnail
from utils.supabase_client import (
    bulk_upsert_post_comments,
    create_campaign_post,
    delete_campaign_post,
    detect_platform_from_url,
    fetch_metrics_from_apify_batch,
    get_brands,
    get_campaign_participants_info,
    get_campaign_post_by_id,
    get_campaign_posts,
    get_campaigns,
    get_influencer_cover_map,
    get_post_comments,
    get_user_profile,
    migrate_google_sheet_rows,
    post_url_exists,
    update_campaign,
    update_campaign_post,
    update_campaign_post_thumbnail,
)

st.set_page_config(page_title="콘텐츠 성과 관리", page_icon="📊", layout="wide")
require_auth()
sidebar_user_info()

# ── 사용자 / 브랜드 컨텍스트 ─────────────────────────────────────────────────

user = st.session_state["user"]
profile = get_user_profile(user.id)
if not profile:
    st.error("사용자 프로필을 찾을 수 없습니다.")
    st.stop()

is_admin = profile.get("role") == "admin"
brand_id: str | None = get_active_brand_id(profile) if not profile.get("role") == "admin" else profile.get("brand_id")

if is_admin:
    brands = get_brands()
    if not brands:
        st.warning("등록된 브랜드가 없습니다.")
        st.stop()
    from collections import Counter
    _name_cnt = Counter(b["name"] for b in brands)
    brand_options = {
        (f"{b['name']}  [{b['id'][:8]}]" if _name_cnt[b["name"]] > 1 else b["name"]): b["id"]
        for b in brands
    }
    sel_brand_label = st.sidebar.selectbox("브랜드 (관리자)", list(brand_options.keys()), key="cp_brand_sel")
    brand_id = brand_options[sel_brand_label]
    brand_map = {v: v for v in brand_options.values()}  # id→id (하위 호환)
    if "cp_prev_brand" not in st.session_state:
        st.session_state.cp_prev_brand = brand_id
    if st.session_state.cp_prev_brand != brand_id:
        st.session_state.cp_prev_brand = brand_id
        st.session_state.pop("cp_editing_post", None)

if not brand_id:
    st.warning("브랜드가 연결되지 않은 계정입니다. 관리자에게 문의하세요.")
    st.stop()

@st.cache_data(ttl=60, show_spinner=False)
def _load_campaigns(brand_id: str):
    return get_campaigns(brand_id)


@st.cache_data(ttl=300, show_spinner=False)
def _load_participants(campaign_id: str, brand_id: str):
    return get_campaign_participants_info(campaign_id, brand_id)


@st.cache_data(ttl=300, show_spinner=False)
def _load_all(brand_id: str) -> list[dict]:
    return get_campaign_posts(brand_id=brand_id)


campaigns = _load_campaigns(brand_id)
campaign_map: dict[str, str] = {c["id"]: c["name"] for c in campaigns}
campaign_name_to_id: dict[str, str] = {c["name"]: c["id"] for c in campaigns}

def _extract_post_id(post_url: str) -> str | None:
    if not post_url:
        return None
    path = post_url.split("?")[0].rstrip("/")
    ttm = re.search(r"/video/(\d+)", path)
    if ttm:
        return ttm.group(1)
    igm = re.search(r"/(?:reel|p|tv)/([^/]+)", path)
    if igm:
        return igm.group(1)
    parts = [seg for seg in path.split("/") if seg]
    return parts[-1] if parts else None


def _sanitize_storage_key(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", (value or "unknown")).strip("_")[:60]


def _aweme_id_from_url(url: str) -> str | None:
    m = re.search(r"/video/(\d+)", url or "")
    return m.group(1) if m else None

def _fmt_time(ts: str) -> str:
    if not ts:
        return ""
    try:
        from datetime import datetime as _dt
        dt = _dt.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts[:16]

def _comment_avatar_color(name: str) -> str:
    colors = ["#6366f1","#ec4899","#f59e0b","#10b981","#3b82f6","#ef4444","#8b5cf6","#14b8a6"]
    return colors[sum(ord(c) for c in (name or "?")) % len(colors)]

@st.cache_data(ttl=60, show_spinner=False)
def _load_comments_tt(aweme_id: str) -> list[dict]:
    return get_post_comments(aweme_id=aweme_id)

@st.cache_data(ttl=60, show_spinner=False)
def _load_comments_ig(post_url: str) -> list[dict]:
    return get_post_comments(post_url=post_url)

def _render_comment_summary(comments: list[dict]) -> None:
    from collections import Counter
    r_cnt = Counter(c.get("user_region")   or "" for c in comments if c.get("user_region"))
    l_cnt = Counter(c.get("user_language") or "" for c in comments if c.get("user_language"))
    if not r_cnt and not l_cnt:
        return
    sc1, sc2 = st.columns(2)
    with sc1:
        if r_cnt:
            st.markdown("**🌍 댓글 작성 지역 TOP 5**")
            total = sum(r_cnt.values())
            tags = "".join(
                f"<span style='background:#f3f4f6;border-radius:6px;padding:3px 10px;margin:2px;"
                f"font-size:12px;font-weight:600;color:#374151;display:inline-block;'>"
                f"{r} <span style='color:#6b7280;font-weight:400'>{c/total*100:.0f}%</span></span>"
                for r, c in r_cnt.most_common(5)
            )
            st.markdown(f"<div style='margin-bottom:8px'>{tags}</div>", unsafe_allow_html=True)
    with sc2:
        if l_cnt:
            st.markdown("**🗣 사용자 언어 TOP 5**")
            total = sum(l_cnt.values())
            tags = "".join(
                f"<span style='background:#eff6ff;border-radius:6px;padding:3px 10px;margin:2px;"
                f"font-size:12px;font-weight:600;color:#1d4ed8;display:inline-block;'>"
                f"{l.upper()} <span style='color:#6b7280;font-weight:400'>{c/total*100:.0f}%</span></span>"
                for l, c in l_cnt.most_common(5)
            )
            st.markdown(f"<div style='margin-bottom:8px'>{tags}</div>", unsafe_allow_html=True)
    st.divider()

def _render_comments(comments: list[dict]) -> None:
    _render_comment_summary(comments)
    st.markdown("""
    <style>
    .cmt-card{padding:10px 12px;border-radius:8px;margin-bottom:6px;background:#f9fafb;}
    .cmt-av{width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;
            justify-content:center;color:#fff;font-size:13px;font-weight:700;flex-shrink:0;
            vertical-align:top;margin-right:9px;}
    .cmt-body{display:inline-block;vertical-align:top;max-width:calc(100% - 48px);}
    .cmt-user{font-size:12px;font-weight:700;color:#111;margin:0 0 1px;}
    .cmt-meta{font-size:11px;color:#9ca3af;margin:0 0 4px;}
    .cmt-text{font-size:13px;color:#374151;margin:0;word-break:break-word;}
    .cmt-like{font-size:11px;color:#6b7280;margin-top:4px;}
    </style>
    """, unsafe_allow_html=True)
    for cmt in comments:
        uname     = cmt.get("username") or cmt.get("display_name") or "?"
        dname     = cmt.get("display_name") or uname
        initial   = uname[0].upper() if uname != "?" else "?"
        color     = _comment_avatar_color(uname)
        time_str  = _fmt_time(cmt.get("created_at") or "")
        text      = (cmt.get("text") or "").replace("<","&lt;").replace(">","&gt;")
        likes     = cmt.get("like_count") or 0
        region    = cmt.get("user_region") or ""
        user_lang = (cmt.get("user_language") or "").upper()
        badge_html = ""
        if region:
            badge_html += f"<span style='background:#f3f4f6;border-radius:4px;padding:1px 6px;font-size:10px;color:#374151;margin-right:3px;'>🌍 {region}</span>"
        if user_lang:
            badge_html += f"<span style='background:#eff6ff;border-radius:4px;padding:1px 6px;font-size:10px;color:#1d4ed8;'>🗣 {user_lang}</span>"
        st.markdown(
            f"""<div class='cmt-card'>
                <span class='cmt-av' style='background:{color};'>{initial}</span>
                <span class='cmt-body'>
                    <p class='cmt-user'>@{uname} <span style='font-weight:400;color:#6b7280;'>· {dname}</span>{"&nbsp;&nbsp;" + badge_html if badge_html else ""}</p>
                    <p class='cmt-meta'>{time_str}</p>
                    <p class='cmt-text'>{text}</p>
                    <p class='cmt-like'>❤️ {likes:,}</p>
                </span>
            </div>""",
            unsafe_allow_html=True,
        )

@st.dialog("💬 댓글", width="large")
def _show_comments_dialog(orig_post: dict) -> None:
    is_tt = orig_post.get("platform") == "tiktok"
    st.caption(f"{'TikTok' if is_tt else 'Instagram'} · {orig_post.get('influencer_name','')} · [게시물 열기]({orig_post.get('post_url','')})")
    if is_tt:
        aweme = _aweme_id_from_url(orig_post["post_url"])
        cmts  = _load_comments_tt(aweme) if aweme else []
    else:
        cmts = _load_comments_ig(orig_post["post_url"])

    if not cmts:
        st.info("이 게시물에 수집된 댓글이 없습니다.")
        return

    kw = st.text_input("검색", placeholder="🔍 내용 또는 사용자명", label_visibility="collapsed", key="dlg_cmt_search")
    show = [c for c in cmts if not kw or kw.lower() in (c.get("text") or "").lower() or kw.lower() in (c.get("username") or "").lower()] if kw else cmts
    st.caption(f"총 {len(cmts)}개 · 표시 {len(show)}개")
    st.divider()
    _render_comments(show)


def _scrape_thumbnails_for_posts(posts: list[dict]) -> list[dict]:
    results: list[dict] = []
    if not posts:
        return results

    total = len(posts)
    progress = st.progress(0)
    status = st.empty()

    for idx, post in enumerate(posts, start=1):
        post_id = post.get("id")
        post_url = post.get("post_url", "")
        username = post.get("influencer_id") or post.get("influencer_name") or "unknown"
        storage_key = post_id or _extract_post_id(post_url) or str(idx)
        storage_key = _sanitize_storage_key(storage_key)

        pct = idx / total
        status.markdown(f"**{idx} / {total}** ({pct*100:.0f}%) — {post.get('influencer_name', '')}")
        progress.progress(pct)

        saved_url = fetch_and_upload_thumbnail(post_url, username, storage_key)
        if saved_url and post_id:
            update_campaign_post_thumbnail(post_id, brand_id, saved_url)

        results.append({
            "인플루언서": post.get("influencer_name", ""),
            "플랫폼": post.get("platform", ""),
            "게시물 URL": post_url,
            "상태": "✅ 성공" if saved_url else "❌ 실패",
            "썸네일 URL": saved_url or "",
        })

    status.empty()
    return results
# ── 캠페인 선택 (filter_campaign_id 먼저 정의 — 데이터 로드에서 사용) ──────────

camp_choices = {"전체 캠페인": None}
camp_choices.update({c["name"]: c["id"] for c in campaigns})
camp_labels = list(camp_choices.keys())

if len(campaigns) <= 7:
    sel_camp_label = st.radio(
        "캠페인",
        camp_labels,
        horizontal=True,
        key="cp_camp",
        label_visibility="collapsed",
    )
else:
    sel_camp_label = st.selectbox(
        "캠페인 선택",
        camp_labels,
        key="cp_camp",
        label_visibility="collapsed",
    )

filter_campaign_id: str | None = camp_choices[sel_camp_label]

# ── 사이드바 필터 ─────────────────────────────────────────────────────────────

st.sidebar.header("필터")

platform_choice = st.sidebar.selectbox("플랫폼", ["전체", "Instagram", "TikTok", "X", "기타"], index=0, key="cp_plat")
filter_platform = {"전체": None, "Instagram": "instagram", "TikTok": "tiktok", "X": "x", "기타": "other"}[platform_choice]

st.sidebar.markdown("**업로드 기간**")
sc1, sc2 = st.sidebar.columns(2)
filter_start: date | None = sc1.date_input("시작일", value=None, key="cp_start")
filter_end: date | None   = sc2.date_input("종료일",  value=None, key="cp_end")

filter_name = st.sidebar.text_input("인플루언서명 검색", key="cp_name")
filter_url  = st.sidebar.text_input("URL 검색",         key="cp_url")

sort_options = {
    "조회수":    "views",
    "업로드일":  "upload_date",
    "참여율":    "engagement_rate",
    "저장 수":   "saves",
    "댓글 수":   "comments",
    "좋아요":    "likes",
}
sort_label = st.sidebar.selectbox("정렬 기준", list(sort_options.keys()), key="cp_sort")
sort_by = sort_options[sort_label]

# ── 데이터 로드 ───────────────────────────────────────────────────────────────

all_posts_raw = _load_all(brand_id)

# 삭제된 캠페인의 포스트 제외 (campaign_id가 현재 캠페인 목록에 없는 것)
_valid_campaign_ids = {c["id"] for c in campaigns}
all_posts_raw = [p for p in all_posts_raw if p.get("campaign_id") in _valid_campaign_ids]

# Python-side 필터링 (DB 재쿼리 없이 처리)
raw = all_posts_raw
if filter_campaign_id:
    raw = [p for p in raw if p.get("campaign_id") == filter_campaign_id]
if filter_platform:
    raw = [p for p in raw if p.get("platform") == filter_platform]
if filter_start:
    s = str(filter_start)
    raw = [p for p in raw if (p.get("upload_date") or "") >= s]
if filter_end:
    e = str(filter_end)
    raw = [p for p in raw if (p.get("upload_date") or "") <= e]
if filter_name:
    nl = filter_name.lower()
    raw = [p for p in raw if nl in (p.get("influencer_name") or "").lower()]
if filter_url:
    ul = filter_url.lower()
    raw = [p for p in raw if ul in (p.get("post_url") or "").lower()]

# 캠페인별 상단 고정 인플루언서 (이름 포함 매칭)
_PRIORITY_NAMES: dict[str, list[str]] = {
    "36ff7778-7955-4714-b41c-2e5dd1d7b1d1": [  # [JP] 23yearsold 5월 나노/마이크로
        "中さゆり", "尾崎", "上田博美", "泉麻依子", "佐藤愛",
        "手取瑞恵", "山崎明音", "薦田みどり", "西飯真子",
    ],
}

def _priority_rank(p: dict) -> int:
    """고정 인플루언서면 순서 인덱스(0~), 아니면 큰 수 반환"""
    names = _PRIORITY_NAMES.get(p.get("campaign_id", ""), [])
    iname = p.get("influencer_name") or ""
    for i, n in enumerate(names):
        if n in iname:
            return i
    return 10000

_SORT_KEY: dict = {
    "upload_date":    lambda p: p.get("upload_date") or "",
    "views":          lambda p: p.get("views") or 0,
    "likes":          lambda p: p.get("likes") or 0,
    "saves":          lambda p: p.get("saves") or 0,
    "comments":       lambda p: p.get("comments") or 0,
    "shares":         lambda p: p.get("shares") or 0,
    "engagement_rate": lambda _: 0,
}
if sort_by != "engagement_rate" and sort_by in _SORT_KEY:
    _prio = sorted(
        [p for p in raw if _priority_rank(p) < 10000],
        key=_priority_rank,
    )
    _rest = sorted(
        [p for p in raw if _priority_rank(p) == 10000],
        key=_SORT_KEY[sort_by], reverse=True,
    )
    raw = _prio + _rest


def _er(p: dict) -> float:
    v = p.get("views") or 0
    if v <= 0:
        return 0.0
    return round((p.get("likes", 0) + p.get("comments", 0) +
                  p.get("saves", 0) + p.get("shares", 0)) / v * 100, 2)


posts = [{**p, "engagement_rate": _er(p)} for p in raw]
if sort_by == "engagement_rate":
    posts = sorted(posts, key=lambda x: x["engagement_rate"], reverse=True)

df = pd.DataFrame(posts) if posts else pd.DataFrame(columns=[
    "id", "brand_id", "campaign_id", "influencer_name", "platform",
    "post_url", "upload_date", "views", "likes", "comments", "saves",
    "shares", "engagement_rate", "last_tracked_at", "created_at",
])

# ── 페이지 헤더 ───────────────────────────────────────────────────────────────

st.title("📊 콘텐츠 성과 관리")
if filter_campaign_id:
    st.caption(f"캠페인: **{sel_camp_label}**  ·  플랫폼: {platform_choice}")
st.divider()

# ── 탭 ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 성과 대시보드",
    "👥 인플루언서 요약",
    "⭐ 우수 콘텐츠",
    "➕ 게시물 관리",
    "💬 댓글",
])

# ═══════════════════════════════════════════════════════════════
# Tab 1 – 성과 대시보드
# ═══════════════════════════════════════════════════════════════

with tab1:
    if df.empty:
        st.info("게시물 데이터가 없습니다. '게시물 관리' 탭에서 게시물을 추가해주세요.")
    else:
        # KPI 계산
        _HDR = {
            "name", "full name", "인플루언서", "인플루언서명", "influencer",
            "influencer_name", "이름", "계정", "아이디", "id",
        }
        _df_valid = df[
            df["influencer_name"].str.strip().str.lower()
            .apply(lambda x: x not in _HDR and x != "")
        ]
        # 게시물(URL)이 있는 사람 = 참여(업로드)한 인플루언서
        total_influencers = _df_valid["influencer_name"].nunique()
        total_posts       = len(df)
        ig_posts          = int((df["platform"] == "instagram").sum())
        tt_posts          = int((df["platform"] == "tiktok").sum())
        x_posts           = int((df["platform"] == "x").sum())
        other_posts       = int((df["platform"] == "other").sum())
        total_views       = int(df["views"].sum())
        total_likes       = int(df["likes"].sum())
        total_comments    = int(df["comments"].sum())
        total_saves       = int(df["saves"].sum())
        total_shares      = int(df["shares"].sum())
        avg_er            = round(float(df["engagement_rate"].mean()), 2)

        # 업로드율 (캠페인 선택 + participant_count 있을 때만)
        if filter_campaign_id:
            camp_data = next((c for c in campaigns if c["id"] == filter_campaign_id), {})
            p_count = camp_data.get("participant_count")

            with st.expander(f"📦 발송 인원 수정 (현재: {p_count or 0}명)"):
                new_p_count = st.number_input(
                    "발송 인원", min_value=0, step=1,
                    value=int(p_count or 0), key="cp_edit_p_count",
                )
                if st.button("저장", key="cp_save_p_count"):
                    update_campaign(filter_campaign_id, {"participant_count": int(new_p_count)})
                    _load_campaigns.clear()
                    st.success("발송 인원이 저장되었습니다.")
                    st.rerun()

            if p_count:
                _HEADER_NAMES = {
                    "name", "full name", "인플루언서", "인플루언서명", "influencer",
                    "influencer_name", "이름", "계정", "아이디", "id",
                }
                u_count = df[
                    df["influencer_name"].str.strip().str.lower()
                    .apply(lambda x: x not in _HEADER_NAMES and x != "")
                ]["influencer_name"].nunique()
                if p_count < u_count:
                    st.warning(
                        f"발송 인원({p_count:,}명)이 업로드 인원({u_count:,}명)보다 적습니다. "
                        "위 '발송 인원 수정'에서 발송 인원을 수정해주세요."
                    )
                else:
                    u_rate  = round(u_count / p_count * 100, 1)
                    ur1, ur2, ur3 = st.columns(3)
                    ur1.metric("📦 발송 인원", f"{p_count:,}명")
                    ur2.metric("📤 업로드 인원", f"{u_count:,}명")
                    ur3.metric("📊 업로드율", f"{u_rate:.1f}%")
                    st.divider()

        # KPI 카드 (5 + 5)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("참여 인플루언서", f"{total_influencers:,}")
        c2.metric("총 게시물",       f"{total_posts:,}")
        c3.metric("Instagram",      f"{ig_posts:,}")
        c4.metric("TikTok",         f"{tt_posts:,}")
        c5.metric("X / 기타",       f"{x_posts + other_posts:,}")

        c6, c7, c8, c9, c10 = st.columns(5)
        c6.metric("평균 참여율",f"{avg_er:.1f}%")
        c7.metric("총 조회수",  f"{total_views:,}")
        c8.metric("총 좋아요",  f"{total_likes:,}")
        c9.metric("총 댓글",    f"{total_comments:,}")
        c10.metric("총 저장",   f"{total_saves:,}")

        st.divider()

        # ── 차트 ──────────────────────────────────────────────────────────
        ch1, ch2 = st.columns(2)

        with ch1:
            st.markdown("#### 👑 인플루언서별 조회수 TOP 10")
            top_inf = (
                df.groupby("influencer_name")["views"].sum()
                .nlargest(10)
                .reset_index()
                .rename(columns={"influencer_name": "인플루언서", "views": "총 조회수"})
            )
            st.bar_chart(top_inf.set_index("인플루언서"), color="#FF6B2C")

        with ch2:
            st.markdown("#### 📊 플랫폼별 성과 비교")
            _plat_label_map = {"instagram": "Instagram", "tiktok": "TikTok", "x": "X", "other": "기타"}
            plat_df = (
                df[df["platform"].notna() & df["platform"].isin(_plat_label_map)]
                .groupby("platform")
                .agg(총_조회수=("views", "sum"), 총_좋아요=("likes", "sum"),
                     평균_ER=("engagement_rate", "mean"))
                .reset_index()
            )
            plat_df["platform"] = plat_df["platform"].map(_plat_label_map)
            plat_df = plat_df.set_index("platform")
            st.bar_chart(plat_df[["총_조회수", "총_좋아요"]])

        # ── 인플루언서별 TT vs IG 비교 (둘 다 있는 경우) ──────────────────
        dual = df.groupby("influencer_name")["platform"].nunique()
        dual_names = dual[dual > 1].index.tolist()
        if dual_names:
            st.markdown("#### 🔄 TikTok · Instagram 동시 참여 인플루언서")
            dual_df = df[df["influencer_name"].isin(dual_names)].copy()
            dual_df["platform_label"] = dual_df["platform"].map({"instagram": "IG", "tiktok": "TT"})
            dual_pivot = (
                dual_df.pivot_table(
                    index="influencer_name",
                    columns="platform_label",
                    values=["views", "likes", "engagement_rate"],
                    aggfunc="sum",
                )
            )
            dual_pivot.columns = [f"{m}_{p}" for m, p in dual_pivot.columns]
            dual_pivot = dual_pivot.fillna(0).reset_index().rename(columns={"influencer_name": "인플루언서"})
            st.dataframe(dual_pivot, use_container_width=True, hide_index=True)

        st.divider()

        view_mode = st.radio("게시물 보기 방식", ["그리드", "목록"], horizontal=True, key="cp_view_mode")

        # 썸네일 스크랩핑 (관리자 전용)
        if is_admin:
            with st.expander("🖼️ 썸네일 스크랩핑", expanded=False):
                force_ig = st.checkbox("Instagram 썸네일 강제 재스크랩 (깨진 경우)", value=True, key="cp_force_ig")
                missing = [p for p in posts
                           if not p.get("thumbnail_url")
                           or "supabase" not in (p.get("thumbnail_url") or "")
                           or (force_ig and p.get("platform") == "instagram")]
                if missing:
                    st.write(f"스크랩 대상: {len(missing)}개")
                    if st.button("썸네일 스크랩핑 실행", key="cp_scrape_thumbnails"):
                        st.session_state.cp_scrape_results = _scrape_thumbnails_for_posts(missing)
                        _load_all.clear()
                        st.rerun()

                    if st.session_state.get("cp_scrape_results"):
                        res_df = pd.DataFrame(st.session_state.cp_scrape_results)
                        st.dataframe(res_df, use_container_width=True, hide_index=True)
                else:
                    st.success("이미 모든 게시물에 썸네일이 있습니다.")
        else:
            # 브랜드 사용자에게는 스크랩핑 UI를 표시하지 않음
            pass

        disp = df.copy()
        _plat_map = {"instagram": "Instagram", "tiktok": "TikTok", "x": "X", "other": "기타"}
        disp["플랫폼"] = disp["platform"].map(_plat_map).fillna("기타")

        show_cols = ["influencer_name", "플랫폼", "post_url",
                     "views", "likes", "comments", "saves", "shares",
                     "engagement_rate", "last_tracked_at"]
        if "thumbnail_url" in disp.columns:
            show_cols = ["thumbnail_url"] + show_cols

        if sel_camp_label == "전체 캠페인":
            # campaign_id 컬럼이 없을 수 있으므로 안전하게 처리
            if "campaign_id" in disp.columns:
                disp["캠페인"] = disp["campaign_id"].map(campaign_map).fillna("–")
            else:
                disp["캠페인"] = "–"
            # 캠페인 추가, influencer_name 유지
            show_cols = ["캠페인", "influencer_name"] + [c for c in show_cols if c != "influencer_name"]

        show_cols = [c for c in show_cols if c in disp.columns]
        rename = {
            "influencer_name":  "인플루언서",
            "플랫폼":           "플랫폼",
            "post_url":         "게시물 URL",
            "upload_date":      "업로드일",
            "views":            "조회수",
            "likes":            "좋아요",
            "comments":         "댓글",
            "saves":            "저장",
            "shares":           "공유",
            "engagement_rate":  "참여율(%)",
            "last_tracked_at":  "마지막 갱신",
            "캠페인":           "캠페인",
            "thumbnail_url":    "썸네일",
        }
        disp = disp[show_cols].rename(columns=rename)

        def _is_displayable_thumb(url) -> bool:
            """브라우저에서 실제로 표시 가능한 썸네일 URL인지 확인."""
            if not url or not isinstance(url, str) or url != url:  # None / NaN / float
                return False
            # Supabase Storage URL — 항상 OK
            if "supabase" in url:
                return True
            # TikTok CDN — 공개 접근 가능
            if "tiktokcdn" in url or "tiktok.com" in url:
                return True
            # imginn / picuki 프록시 CDN — 공개 접근 가능
            if "imginn.com" in url or "picuki.com" in url:
                return True
            # X(트위터) 미디어 CDN — 프로필 이미지 포함 허용
            if "pbs.twimg.com" in url or "twimg.com" in url:
                return True
            # JS/CSS 파일
            if url.lower().split("?")[0].endswith((".js", ".css", ".json")):
                return False
            # Instagram 자체 CDN은 도메인 기준으로 차단 (query string 포함 오탐 방지)
            try:
                from urllib.parse import urlparse as _p
                domain = _p(url).netloc
            except Exception:
                domain = url
            if any(d in domain for d in ("cdninstagram.com", "fbcdn.net", "scontent-")):
                return False
            return True

        if view_mode == "그리드":
            # 인플루언서 프로필 사진 (influencer_master.cover_url) — 썸네일 없을 때 fallback
            _cover_map = get_influencer_cover_map()  # influencer_id.lower() → cover_url
            # campaign_posts의 influencer_id / influencer_name → cover_url 매핑
            _name_to_cover: dict = {}
            for _p in posts:
                _iid  = (_p.get("influencer_id")   or "").strip().lower()
                _iname = (_p.get("influencer_name") or "").strip()
                _cv = _cover_map.get(_iid) or _cover_map.get(_iname.lower())
                if _cv and _iname:
                    _name_to_cover[_iname] = _cv

            _all_records = disp.to_dict(orient="records")
            rows = []
            for _r in _all_records:
                _thumb = _r.get("썸네일") or ""
                if _is_displayable_thumb(_thumb):
                    rows.append({**_r, "_img": _thumb, "_is_cover": False})
                else:
                    # 썸네일 없으면 프로필 사진으로 대체
                    _cv = _name_to_cover.get(_r.get("인플루언서") or "")
                    if _cv:
                        rows.append({**_r, "_img": _cv, "_is_cover": True})
                    # 둘 다 없으면 그리드에서 제외

            # X는 항상 마지막에, 나머지는 참여율 내림차순
            rows.sort(key=lambda r: (
                1 if r.get("플랫폼") == "X" else 0,
                -(r.get("참여율(%)", 0) or 0),
            ))
            # 중복 제거: 게시물 URL (쿼리 제거) + 썸네일 URL 둘 다 체크
            _seen_keys: set = set()
            _deduped: list = []
            for _r in rows:
                _url_key   = (_r.get("게시물 URL") or "").split("?")[0].rstrip("/")
                _thumb_key = (_r.get("_img") or _r.get("썸네일") or "").split("?")[0]
                # 둘 중 하나라도 이미 본 적 있으면 중복으로 판단
                _dup = (_url_key and _url_key in _seen_keys) or \
                       (_thumb_key and _thumb_key in _seen_keys)
                if _dup:
                    continue
                if _url_key:   _seen_keys.add(_url_key)
                if _thumb_key: _seen_keys.add(_thumb_key)
                _deduped.append(_r)
            rows = _deduped
            if not rows:
                st.info("썸네일이 있는 게시물이 없습니다. 썸네일 스크랩핑을 실행하거나 목록 보기를 이용하세요.")
            else:
                def _fmt(n) -> str:
                    try:
                        n = int(float(str(n)))
                        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
                        if n >= 1_000:     return f"{n/1_000:.1f}K"
                        return str(n)
                    except Exception:
                        return "-"

                # 게시물 → post 원본 데이터 매핑 (URL 기준)
                _url_to_post = {
                    (p.get("post_url") or "").split("?")[0].rstrip("/"): p
                    for p in posts
                }

                for idx, chunk in enumerate([rows[i:i + 4] for i in range(0, len(rows), 4)]):
                    cols = st.columns(4)
                    for cidx, (col, row) in enumerate(zip(cols, chunk)):
                        thumb  = row.get("_img") or row.get("썸네일", "")
                        url    = row.get("게시물 URL", "") or "#"
                        name   = row.get("인플루언서", "")
                        plat   = row.get("플랫폼", "")
                        views  = _fmt(row.get("조회수", 0))
                        likes  = _fmt(row.get("좋아요", 0))
                        cmts   = _fmt(row.get("댓글", 0))
                        er     = row.get("참여율(%)", 0)
                        er_str = f"{float(er):.1f}%" if er else "-"
                        _plat_colors = {"TikTok": "#010101", "Instagram": "#c13584", "X": "#1a8cd8", "기타": "#888888"}
                        plat_bg = _plat_colors.get(plat, "#555555")
                        card_key = f"cmt_card_{idx}_{cidx}"

                        col.markdown(f"""
<a href="{url}" target="_blank" style="text-decoration:none;display:block;margin-bottom:4px;">
  <div style="position:relative;border-radius:12px;overflow:hidden;background:#111;aspect-ratio:9/16;cursor:pointer;">
    <img src="{thumb}" style="width:100%;height:100%;object-fit:cover;display:block;">
    <div style="position:absolute;bottom:0;left:0;right:0;
                background:linear-gradient(transparent,rgba(0,0,0,.85));
                padding:28px 10px 10px;">
      <p style="color:#fff;font-weight:700;font-size:13px;margin:0 0 4px;line-height:1.3;">{name}</p>
      <p style="color:rgba(255,255,255,.85);font-size:11px;margin:0;">
        👁 {views} &nbsp;❤️ {likes} &nbsp;💬 {cmts} &nbsp;ER {er_str}
      </p>
    </div>
    <div style="position:absolute;top:8px;left:8px;background:{plat_bg};
                border-radius:5px;padding:2px 8px;color:#fff;font-size:10px;font-weight:700;">
      {plat}
    </div>
  </div>
</a>
""", unsafe_allow_html=True)
                        # 댓글 버튼 → 모달 다이얼로그
                        _norm_url = url.split("?")[0].rstrip("/")
                        _orig = _url_to_post.get(_norm_url)
                        _has_comments = bool(
                            (_orig and _orig.get("platform") == "tiktok" and _aweme_id_from_url(url))
                            or (_orig and _orig.get("platform") == "instagram")
                        )
                        if _has_comments and _orig:
                            if col.button("💬 댓글 보기", key=card_key, use_container_width=True):
                                _show_comments_dialog(_orig)

            st.divider()
        else:
            st.subheader("게시물 목록")
            list_disp = disp[[c for c in disp.columns if c != "썸네일"]]
            st.dataframe(
                list_disp,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "게시물 URL":    st.column_config.LinkColumn("게시물 URL", display_text="🔗 열기"),
                    "조회수":        st.column_config.NumberColumn("조회수",    format="%d"),
                    "좋아요":        st.column_config.NumberColumn("좋아요",    format="%d"),
                    "댓글":          st.column_config.NumberColumn("댓글",      format="%d"),
                    "저장":          st.column_config.NumberColumn("저장",      format="%d"),
                    "공유":          st.column_config.NumberColumn("공유",      format="%d"),
                    "참여율(%)":     st.column_config.NumberColumn("참여율(%)", format="%.2f%%"),
                    "마지막 갱신":   st.column_config.DatetimeColumn("마지막 갱신", format="YYYY-MM-DD HH:mm"),
                },
            )

# ═══════════════════════════════════════════════════════════════
# Tab 2 – 인플루언서별 요약
# ═══════════════════════════════════════════════════════════════

with tab2:
    if df.empty:
        st.info("데이터가 없습니다.")
    else:
        st.subheader("인플루언서별 성과 요약")

        grp = (
            df.groupby("influencer_name")
            .agg(
                총_게시물    =("id",              "count"),
                Instagram    =("platform",         lambda x: (x == "instagram").sum()),
                TikTok       =("platform",         lambda x: (x == "tiktok").sum()),
                X            =("platform",         lambda x: (x == "x").sum()),
                총_조회수    =("views",            "sum"),
                총_좋아요    =("likes",            "sum"),
                총_댓글      =("comments",         "sum"),
                총_저장      =("saves",            "sum"),
                총_공유      =("shares",           "sum"),
                평균_참여율  =("engagement_rate",  "mean"),
            )
            .reset_index()
        )
        grp["평균_참여율"] = grp["평균_참여율"].round(2)

        # 최고 조회수 게시물 URL
        if not df.empty and "views" in df.columns:
            best = (
                df.loc[df.groupby("influencer_name")["views"].idxmax()]
                [["influencer_name", "post_url"]]
                .rename(columns={"post_url": "최고성과_URL"})
            )
            grp = grp.merge(best, on="influencer_name", how="left")

        # 커버 이미지 URL 추가 (influencer_master.cover_url 기반)
        _cover = get_influencer_cover_map()
        grp["커버"] = grp["influencer_name"].apply(
            lambda n: _cover.get(n.lower())
        )

        grp = grp.sort_values("총_조회수", ascending=False)
        grp.rename(columns={
            "influencer_name": "인플루언서",
            "총_게시물":       "총 게시물",
            "총_조회수":       "총 조회수",
            "총_좋아요":       "총 좋아요",
            "총_댓글":         "총 댓글",
            "총_저장":         "총 저장",
            "총_공유":         "총 공유",
            "평균_참여율":     "평균 참여율(%)",
            "최고성과_URL":    "최고 성과 URL",
        }, inplace=True)

        # 커버 컬럼을 맨 앞으로
        cols = ["커버"] + [c for c in grp.columns if c != "커버"]
        grp = grp[cols]

        col_config = {
            "커버":           st.column_config.ImageColumn("커버", width="small"),
            "평균 참여율(%)": st.column_config.NumberColumn("평균 참여율(%)", format="%.2f%%"),
        }
        if "최고 성과 URL" in grp.columns:
            col_config["최고 성과 URL"] = st.column_config.LinkColumn("최고 성과 URL", display_text="🔗 열기")

        st.dataframe(grp, use_container_width=True, hide_index=True, column_config=col_config)

# ═══════════════════════════════════════════════════════════════
# Tab 3 – 우수 콘텐츠 추천
# ═══════════════════════════════════════════════════════════════

with tab3:
    if df.empty:
        st.info("데이터가 없습니다.")
    else:
        st.subheader("⭐ 광고 소재 추천 콘텐츠")

        def _top5(title: str, col: str) -> None:
            st.markdown(f"#### {title}")
            top = (
                df.nlargest(5, col)
                [["influencer_name", "platform", "post_url", "views", "engagement_rate", "saves", "comments"]]
                .copy()
            )
            top["platform"] = top["platform"].map({"instagram": "Instagram", "tiktok": "TikTok"})
            top.rename(columns={
                "influencer_name": "인플루언서",
                "platform":        "플랫폼",
                "post_url":        "게시물 URL",
                "views":           "조회수",
                "engagement_rate": "참여율(%)",
                "saves":           "저장",
                "comments":        "댓글",
            }, inplace=True)
            st.dataframe(
                top, use_container_width=True, hide_index=True,
                column_config={
                    "게시물 URL":  st.column_config.LinkColumn("게시물 URL", display_text="🔗 열기"),
                    "참여율(%)":   st.column_config.NumberColumn("참여율(%)", format="%.2f%%"),
                },
            )

        col_a, col_b = st.columns(2)
        with col_a:
            _top5("조회수 TOP 5",  "views")
            st.divider()
            _top5("저장 수 TOP 5", "saves")
        with col_b:
            _top5("참여율 TOP 5",  "engagement_rate")
            st.divider()
            _top5("댓글 TOP 5",    "comments")

# ═══════════════════════════════════════════════════════════════
# Tab 4 – 게시물 관리
# ═══════════════════════════════════════════════════════════════

with tab4:
    if not campaigns:
        st.warning("먼저 캠페인을 생성해주세요. (캠페인 메뉴)")
        st.stop()

    # ── 수정 폼 (상단 고정, 수정 버튼 클릭 시 표시) ─────────────────────────

    if "cp_editing_post" in st.session_state and st.session_state.cp_editing_post:
        ep = st.session_state.cp_editing_post
        st.subheader("✏️ 게시물 수정")
        with st.form("edit_post_form"):
            ec1, ec2 = st.columns(2)
            e_name = ec1.text_input(
                "인플루언서명 *",
                value=ep.get("influencer_name", ""),
            )
            e_plat = ec2.selectbox(
                "플랫폼 *",
                ["instagram", "tiktok"],
                index=0 if ep.get("platform") == "instagram" else 1,
            )
            e_url = st.text_input("게시물 URL *", value=ep.get("post_url", ""))

            # 썸네일 직접 지정 (자동 스크랩 실패 시)
            cur_thumb = ep.get("thumbnail_url") or ""
            with st.expander("🖼️ 썸네일 직접 지정 (선택)", expanded=bool(cur_thumb and "supabase" not in cur_thumb)):
                thumb_cols = st.columns([3, 1])
                e_thumb_url = thumb_cols[0].text_input(
                    "썸네일 이미지 URL",
                    value=cur_thumb,
                    placeholder="https://...",
                    help="자동 스크랩이 안 될 때 이미지 URL을 직접 붙여넣으세요.",
                )
                if cur_thumb:
                    thumb_cols[1].image(cur_thumb, use_container_width=True)
            e_rescrape = st.checkbox("저장 후 썸네일 자동 재스크랩", value=False, key="edit_rescrape")

            raw_date = ep.get("upload_date")
            try:
                from datetime import datetime as _dt
                default_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date() if raw_date else None
            except Exception:
                default_date = None

            ec3, ec4 = st.columns(2)
            e_date   = ec3.date_input("업로드 날짜", value=default_date)
            e_views  = ec4.number_input("조회수",  min_value=0, value=int(ep.get("views",  0)), step=1)

            ec5, ec6, ec7, ec8 = st.columns(4)
            e_likes    = ec5.number_input("좋아요",  min_value=0, value=int(ep.get("likes",    0)), step=1)
            e_comments = ec6.number_input("댓글",    min_value=0, value=int(ep.get("comments", 0)), step=1)
            e_saves    = ec7.number_input("저장",    min_value=0, value=int(ep.get("saves",    0)), step=1)
            e_shares   = ec8.number_input("공유",    min_value=0, value=int(ep.get("shares",   0)), step=1)

            sb1, sb2 = st.columns([1, 1])
            submitted_edit = sb1.form_submit_button("✅ 수정 완료", use_container_width=True)
            cancel_edit    = sb2.form_submit_button("✖ 취소",       use_container_width=True)

        if cancel_edit:
            st.session_state.cp_editing_post = None
            st.rerun()

        if submitted_edit:
            if not e_name.strip():
                st.error("인플루언서명을 입력해주세요.")
            elif not e_url.strip():
                st.error("게시물 URL을 입력해주세요.")
            elif post_url_exists(e_url.strip(), exclude_post_id=ep["id"]):
                st.error("이미 등록된 URL입니다.")
            else:
                payload = {
                    "influencer_name": e_name.strip(),
                    "platform":        e_plat,
                    "post_url":        e_url.strip(),
                    "upload_date":     str(e_date) if e_date else None,
                    "views":           e_views,
                    "likes":           e_likes,
                    "comments":        e_comments,
                    "saves":           e_saves,
                    "shares":          e_shares,
                }
                # 썸네일 직접 지정값 반영
                if e_thumb_url.strip():
                    payload["thumbnail_url"] = e_thumb_url.strip()
                ok = update_campaign_post(ep["id"], brand_id, payload)
                # 자동 재스크랩 요청 시
                if ok and e_rescrape:
                    with st.spinner("썸네일 재스크랩 중..."):
                        new_thumb = fetch_and_upload_thumbnail(
                            e_url.strip(),
                            e_name.strip(),
                            _sanitize_storage_key(ep["id"]),
                        )
                        if new_thumb:
                            update_campaign_post_thumbnail(ep["id"], brand_id, new_thumb)
                if ok:
                    st.success("수정되었습니다.")
                    st.session_state.cp_editing_post = None
                    _load_all.clear()
                    st.rerun()
                else:
                    st.error("수정에 실패했습니다.")
        st.divider()

    # ── 새 게시물 추가 ────────────────────────────────────────────────────────

    with st.expander("➕ 새 게시물 추가", expanded=True):
        with st.form("add_post_form", clear_on_submit=True):
            fa1, fa2 = st.columns(2)

            # 캠페인 선택
            camp_labels = [c["name"] for c in campaigns]
            default_camp_idx = 0
            if filter_campaign_id:
                try:
                    default_camp_idx = next(
                        i for i, c in enumerate(campaigns) if c["id"] == filter_campaign_id
                    )
                except StopIteration:
                    pass
            sel_camp_form = fa1.selectbox("캠페인 *", camp_labels, index=default_camp_idx)
            form_campaign_id = campaign_name_to_id[sel_camp_form]

            form_platform = fa2.selectbox("플랫폼 *", ["instagram", "tiktok"])

            # 인플루언서 선택
            participants = _load_participants(form_campaign_id, brand_id)
            part_labels = ["직접 입력"] + [p["display_name"] for p in participants if p.get("display_name")]
            fb1, fb2 = st.columns(2)
            sel_participant = fb1.selectbox("캠페인 참여자 선택", part_labels)

            if sel_participant == "직접 입력":
                form_name      = fb2.text_input("인플루언서명 *", placeholder="예: Adriana Kim")
                form_part_id   = None
                form_inf_id    = None
            else:
                matched = next((p for p in participants if p.get("display_name") == sel_participant), None)
                form_name      = fb2.text_input("인플루언서명 *", value=sel_participant)
                form_part_id   = matched["id"]           if matched else None
                form_inf_id    = matched["influencer_id"] if matched else None

            form_url  = st.text_input("게시물 URL *", placeholder="https://www.tiktok.com/@...")
            fc1, fc2  = st.columns(2)
            form_date = fc1.date_input("업로드 날짜", value=None)
            form_views = fc2.number_input("조회수", min_value=0, step=1)

            fd1, fd2, fd3, fd4 = st.columns(4)
            form_likes    = fd1.number_input("좋아요",  min_value=0, step=1)
            form_comments = fd2.number_input("댓글",    min_value=0, step=1)
            form_saves    = fd3.number_input("저장",    min_value=0, step=1)
            form_shares   = fd4.number_input("공유",    min_value=0, step=1)

            submitted_add = st.form_submit_button("게시물 추가", use_container_width=True)

        if submitted_add:
            if not form_name.strip():
                st.error("인플루언서명을 입력해주세요.")
            elif not form_url.strip():
                st.error("게시물 URL을 입력해주세요.")
            elif post_url_exists(form_url.strip()):
                st.error("이미 등록된 URL입니다.")
            else:
                result = create_campaign_post(brand_id, {
                    "campaign_id":     form_campaign_id,
                    "participant_id":  form_part_id,
                    "influencer_id":   form_inf_id,
                    "influencer_name": form_name.strip(),
                    "platform":        form_platform,
                    "post_url":        form_url.strip(),
                    "upload_date":     str(form_date) if form_date else None,
                    "views":           form_views,
                    "likes":           form_likes,
                    "comments":        form_comments,
                    "saves":           form_saves,
                    "shares":          form_shares,
                })
                if result:
                    post_id = result.get("id") if isinstance(result, dict) else None
                    # 자동 썸네일 스크랩
                    if post_id:
                        with st.spinner("썸네일 스크랩 중..."):
                            thumb = fetch_and_upload_thumbnail(
                                form_url.strip(),
                                form_name.strip(),
                                _sanitize_storage_key(post_id),
                            )
                            if thumb:
                                update_campaign_post_thumbnail(post_id, brand_id, thumb)
                    st.success(f"게시물이 추가되었습니다. ({form_platform.upper()} · {form_name})")
                    _load_all.clear()
                    st.rerun()
                else:
                    st.error("게시물 추가에 실패했습니다.")

    # ── URL 붙여넣기로 자동 트래킹 (Apify) ────────────────────────────────────

    with st.expander("🔄 URL 붙여넣기로 자동 트래킹 (Apify)", expanded=False):
        st.caption(
            "TikTok · Instagram 게시물 URL을 한 줄에 하나씩 붙여넣으면 "
            "Apify로 조회수/좋아요/댓글 등을 자동으로 가져와 캠페인에 추가합니다."
        )

        _ap_pending = st.session_state.get("ap_pending")
        _ap_preview = st.session_state.get("ap_preview")

        # ── 입력 폼 (진행/미리보기 중이 아닐 때만 표시) ───────────────────────
        if _ap_pending is None and _ap_preview is None:
            ap_camp_label = st.selectbox(
                "캠페인 *", [c["name"] for c in campaigns], key="ap_camp",
            )
            ap_urls_raw = st.text_area(
                "게시물 URL (한 줄에 하나씩)",
                placeholder="https://www.tiktok.com/@.../video/...\nhttps://www.instagram.com/p/...",
                height=140,
                key="ap_urls_input",
            )
            if st.button("🔄 가져오기", key="ap_fetch_btn"):
                lines = [u.strip() for u in ap_urls_raw.splitlines() if u.strip()]
                seen, queue = set(), []
                n_dup = n_unsupported = n_existing = 0
                for u in lines:
                    if u in seen:
                        n_dup += 1
                        continue
                    seen.add(u)
                    plat = detect_platform_from_url(u)
                    if not plat:
                        n_unsupported += 1
                        continue
                    if post_url_exists(u):
                        n_existing += 1
                        continue
                    queue.append({"url": u, "platform": plat})

                if not queue:
                    st.warning("가져올 URL이 없습니다. (중복/미지원/이미 등록된 URL은 자동 제외됩니다)")
                else:
                    st.session_state["ap_campaign_id"] = campaign_name_to_id[ap_camp_label]
                    st.session_state["ap_pending"] = queue
                    st.session_state["ap_offset"] = 0
                    st.session_state["ap_results"] = []
                    st.session_state["ap_skip_note"] = (
                        f"제외됨 — 중복 {n_dup}건 · 미지원 플랫폼 {n_unsupported}건 · 이미 등록됨 {n_existing}건"
                        if (n_dup or n_unsupported or n_existing) else ""
                    )
                    st.rerun()

        # ── 청크 단위 Apify 조회 (같은 플랫폼 URL을 최대한 한 번의 액터 실행으로 묶어 조회) ──
        if _ap_pending is not None:
            _AP_CHUNK = 8
            _ap_offset = st.session_state.get("ap_offset", 0)
            _ap_total = len(_ap_pending)
            _ap_chunk = _ap_pending[_ap_offset:_ap_offset + _AP_CHUNK]
            _ap_done = min(_ap_offset + _AP_CHUNK, _ap_total)
            st.progress(
                _ap_done / _ap_total if _ap_total else 1.0,
                text=f"Apify로 가져오는 중... ({_ap_done}/{_ap_total})",
            )

            if _ap_chunk:
                ap_campaign_id = st.session_state["ap_campaign_id"]
                ap_participants = _load_participants(ap_campaign_id, brand_id)
                batch_results = fetch_metrics_from_apify_batch(
                    [(it["url"], it["platform"]) for it in _ap_chunk]
                )
                for item in _ap_chunk:
                    url, plat = item["url"], item["platform"]
                    metrics, debug_reason = batch_results.get(url, (None, "알 수 없는 오류"))
                    row = {
                        "url": url, "platform": plat,
                        "views": 0, "likes": 0, "comments": 0, "saves": 0, "shares": 0,
                        "thumbnail_url": None, "upload_date": None,
                        "influencer_name": "", "participant_id": None, "influencer_id": None,
                        "matched": False, "status": "ok" if metrics else "failed",
                        "debug_reason": debug_reason,
                    }
                    if metrics:
                        row.update({
                            "views": metrics["views"], "likes": metrics["likes"],
                            "comments": metrics["comments"], "saves": metrics["saves"],
                            "shares": metrics["shares"], "thumbnail_url": metrics.get("thumbnail_url"),
                            "upload_date": metrics.get("upload_date"),
                        })
                        uname = metrics.get("username") or ""
                        if uname:
                            for p in ap_participants:
                                acc_l = (p.get("display_name") or "").lower()
                                if acc_l and uname in acc_l:
                                    row.update({
                                        "influencer_name": p.get("display_name") or "",
                                        "participant_id": p.get("id"),
                                        "influencer_id": p.get("influencer_id"),
                                        "matched": True,
                                    })
                                    break
                    st.session_state["ap_results"].append(row)

                st.session_state["ap_offset"] = _ap_offset + _AP_CHUNK
                st.rerun()
            else:
                st.session_state["ap_preview"] = st.session_state.pop("ap_results", [])
                st.session_state.pop("ap_pending", None)
                st.session_state.pop("ap_offset", None)
                st.rerun()

        # ── 미리보기 & 확인 ────────────────────────────────────────────────────
        if _ap_preview is not None:
            skip_note = st.session_state.pop("ap_skip_note", "")
            if skip_note:
                st.caption(skip_note)

            if not _ap_preview:
                st.info("가져온 게시물이 없습니다.")
                if st.button("닫기", key="ap_close_empty"):
                    for k in ("ap_preview", "ap_campaign_id"):
                        st.session_state.pop(k, None)
                    st.rerun()
            else:
                n_failed = sum(1 for r in _ap_preview if r["status"] == "failed")
                n_unmatched = sum(1 for r in _ap_preview if r["status"] == "ok" and not r["matched"])
                st.caption(
                    f"총 {len(_ap_preview)}건 · 매칭 실패/실패 항목은 인플루언서명을 직접 입력해야 포함됩니다."
                    + (f" (조회 실패 {n_failed}건, 미매칭 {n_unmatched}건)" if (n_failed or n_unmatched) else "")
                )

                for i, row in enumerate(_ap_preview):
                    pc1, pc2, pc3 = st.columns([1, 3, 2])
                    with pc1:
                        if row["thumbnail_url"]:
                            st.image(row["thumbnail_url"], use_container_width=True)
                        else:
                            st.caption("썸네일 없음")
                    with pc2:
                        badge = "TT" if row["platform"] == "tiktok" else "IG"
                        status_txt = "⚠️ 조회 실패 (값 0으로 등록됨)" if row["status"] == "failed" else (
                            "✅ 매칭됨" if row["matched"] else "⚠️ 매칭 실패 — 이름 직접 입력 필요"
                        )
                        st.markdown(f"`{badge}` {status_txt}")
                        if row["status"] == "failed" and row.get("debug_reason"):
                            st.caption(f"사유: {row['debug_reason']}")
                        st.caption(row["url"][:70] + ("..." if len(row["url"]) > 70 else ""))
                        if row["status"] == "ok":
                            st.caption(
                                f"조회수 {row['views']:,} · 좋아요 {row['likes']:,} · "
                                f"댓글 {row['comments']:,} · 공유 {row['shares']:,}"
                            )
                    with pc3:
                        st.text_input(
                            "인플루언서명", value=row["influencer_name"],
                            key=f"ap_name_{i}", placeholder="이름 입력",
                        )
                        st.checkbox("포함", value=True, key=f"ap_inc_{i}")
                    st.divider()

                bcol1, bcol2 = st.columns(2)
                if bcol1.button("✅ 선택한 게시물 캠페인에 추가", key="ap_confirm_btn", use_container_width=True):
                    ap_campaign_id = st.session_state["ap_campaign_id"]
                    n_created = 0
                    n_no_name = 0
                    n_dup = 0
                    n_failed = 0
                    for i, row in enumerate(_ap_preview):
                        included = st.session_state.get(f"ap_inc_{i}", True)
                        name = (st.session_state.get(f"ap_name_{i}", "") or "").strip()
                        if not included:
                            continue
                        if not name:
                            n_no_name += 1
                            continue
                        if post_url_exists(row["url"]):
                            n_dup += 1
                            continue
                        result = create_campaign_post(brand_id, {
                            "campaign_id": ap_campaign_id,
                            "participant_id": row["participant_id"],
                            "influencer_id": row["influencer_id"],
                            "influencer_name": name,
                            "platform": row["platform"],
                            "post_url": row["url"],
                            "upload_date": row["upload_date"],
                            "views": row["views"], "likes": row["likes"],
                            "comments": row["comments"], "saves": row["saves"],
                            "shares": row["shares"],
                        })
                        if result:
                            n_created += 1
                            post_id = result.get("id") if isinstance(result, dict) else None
                            if post_id and row["thumbnail_url"]:
                                stored = upload_thumbnail(
                                    row["thumbnail_url"], name, _sanitize_storage_key(post_id),
                                )
                                if stored:
                                    update_campaign_post_thumbnail(post_id, brand_id, stored)
                        else:
                            n_failed += 1

                    st.session_state.pop("ap_preview", None)
                    st.session_state.pop("ap_campaign_id", None)
                    for i in range(len(_ap_preview)):
                        st.session_state.pop(f"ap_name_{i}", None)
                        st.session_state.pop(f"ap_inc_{i}", None)
                    _load_all.clear()
                    msg = f"{n_created}개 게시물이 추가되었습니다."
                    detail = []
                    if n_no_name:
                        detail.append(f"이름 미입력 {n_no_name}건")
                    if n_dup:
                        detail.append(f"이미 등록됨 {n_dup}건")
                    if n_failed:
                        detail.append(f"등록 실패 {n_failed}건")
                    if detail:
                        msg += " (제외: " + " · ".join(detail) + ")"
                    st.success(msg)
                    st.rerun()

                if bcol2.button("❌ 취소", key="ap_cancel_btn", use_container_width=True):
                    for i in range(len(_ap_preview)):
                        st.session_state.pop(f"ap_name_{i}", None)
                        st.session_state.pop(f"ap_inc_{i}", None)
                    st.session_state.pop("ap_preview", None)
                    st.session_state.pop("ap_campaign_id", None)
                    st.rerun()

    # ── 기존 게시물 수정 / 삭제 ───────────────────────────────────────────────

    with st.expander("✏️ 기존 게시물 수정 / 삭제", expanded=False):
        if df.empty:
            st.info("현재 필터 기준으로 표시할 게시물이 없습니다.")
        else:
            st.caption("현재 사이드바 필터 기준으로 표시됩니다. 필터를 변경해 원하는 게시물을 찾으세요.")

            for _, row in df.iterrows():
                pid    = row["id"]
                pname  = row.get("influencer_name", "")
                pplat  = "IG" if row.get("platform") == "instagram" else "TT"
                purl   = str(row.get("post_url", ""))
                pdate  = str(row.get("upload_date") or "날짜 없음")
                pviews = int(row.get("views", 0))

                mg1, mg2, mg3 = st.columns([6, 1, 1])
                mg1.markdown(
                    f"**{pname}** · `{pplat}` · {pdate} · "
                    f"조회수 {pviews:,} · [{purl[:55]}...]({purl})"
                    if len(purl) > 55
                    else f"**{pname}** · `{pplat}` · {pdate} · 조회수 {pviews:,} · [{purl}]({purl})"
                )
                if mg2.button("✏️", key=f"edit_{pid}", use_container_width=True):
                    full = get_campaign_post_by_id(pid, brand_id)
                    if full:
                        st.session_state.cp_editing_post = full
                    st.rerun()

                del_key = f"del_confirm_{pid}"
                if st.session_state.get(del_key):
                    if mg3.button("⚠️확인", key=f"del_ok_{pid}", use_container_width=True):
                        delete_campaign_post(pid, brand_id)
                        st.session_state.pop(del_key, None)
                        _load_all.clear()
                        st.rerun()
                else:
                    if mg3.button("🗑️", key=f"del_{pid}", use_container_width=True):
                        st.session_state[del_key] = True
                        st.rerun()

    # ── Google Sheet 데이터 이관 ──────────────────────────────────────────────

    with st.expander("📥 Google Sheet 데이터 이관", expanded=False):
        st.markdown("""
**CSV 형식 안내**

헤더 행이 반드시 포함되어야 합니다. TikTok · Instagram · X · LIPS 지표를 각각 입력할 수 있습니다.

| name | tt_url | ig_url | x_url | lips_url | upload_day | tt_views | tt_likes | ig_views | ig_likes |
|------|--------|--------|-------|----------|------------|----------|----------|----------|----------|
| Adriana | https://tiktok.com/... | https://instagram.com/... | | | 2026/05/10 | 5000 | 300 | 1156 | 25 |

**매핑 규칙**
- `tt_url` / `ig_url` / `x_url` / `lips_url` 각각 별도 게시물로 등록 (있는 것만)
- URL 없는 행도 **발송 인원**으로 집계되어 업로드율 계산에 포함됩니다
- 구 형식(`views/likes/…` 단일 컬럼)도 그대로 지원됩니다

**Google Sheet 컬럼명 자동 인식**: `Posting URL (TT)`, `Posting URL (IG)`, `Posting URL (X)`, `others(LIPS)`, `Views`, `Likes▼`, `Comments`, `Saves`
""")

        mi_camp_label = st.selectbox(
            "이관 대상 캠페인 *",
            [c["name"] for c in campaigns],
            key="mi_camp",
        )
        mi_campaign_id = campaign_name_to_id[mi_camp_label]

        import_method = st.radio(
            "가져오기 방법",
            ["🔗 Google Sheets URL", "📎 CSV 파일 업로드"],
            horizontal=True,
            key="mi_method",
        )

        raw_csv = None

        # ── Google Sheets URL 방식 ────────────────────────────────────────────
        if import_method == "🔗 Google Sheets URL":
            st.caption("시트를 **'링크가 있는 모든 사용자 → 뷰어'** 로 공유한 후 URL을 붙여넣으세요.")
            sheets_url = st.text_input(
                "Google Sheets URL",
                placeholder="https://docs.google.com/spreadsheets/d/...",
                key="mi_sheets_url",
            )

            if sheets_url:
                m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", sheets_url)
                if not m:
                    st.error("올바른 Google Sheets URL이 아닙니다.")
                else:
                    sheet_id = m.group(1)
                    gid_m = re.search(r"[#&?]gid=(\d+)", sheets_url)
                    gid = gid_m.group(1) if gid_m else "0"
                    csv_export_url = (
                        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
                        f"/export?format=csv&gid={gid}"
                    )

                    fetch_col, info_col = st.columns([1, 3])
                    if fetch_col.button("📥 시트 불러오기", key="mi_fetch_btn"):
                        try:
                            import requests as _http
                            resp = _http.get(csv_export_url, timeout=20)
                            resp.raise_for_status()
                            fetched = pd.read_csv(
                                io.StringIO(resp.content.decode("utf-8-sig"))
                            )
                            st.session_state["mi_fetched_csv"] = fetched.to_dict(orient="list")
                            st.session_state["mi_fetched_url"] = sheets_url
                            st.success(f"시트 불러오기 완료: {len(fetched)}행")
                        except Exception as fe:
                            st.error(f"불러오기 실패: {fe}")
                            st.caption(
                                "시트가 '링크가 있는 모든 사용자' 공유인지 확인하거나, "
                                "URL의 gid 값(탭 번호)이 맞는지 확인하세요."
                            )

                    # 같은 URL로 이미 불러온 데이터가 있으면 재사용
                    if (
                        st.session_state.get("mi_fetched_url") == sheets_url
                        and "mi_fetched_csv" in st.session_state
                    ):
                        raw_csv = pd.DataFrame(st.session_state["mi_fetched_csv"])
                        info_col.caption(f"✅ 불러온 시트: {len(raw_csv)}행 · URL이 바뀌면 다시 '불러오기'를 누르세요.")

        # ── CSV 파일 업로드 방식 ──────────────────────────────────────────────
        else:
            f = st.file_uploader("CSV 파일 업로드", type=["csv"], key="mi_csv")
            if f:
                try:
                    raw_csv = pd.read_csv(io.StringIO(f.getvalue().decode("utf-8-sig")))
                except Exception as fe:
                    st.error(f"CSV 파싱 오류: {fe}")

        # ── 청크 이관 자동 실행 (Railway 타임아웃 방지: 20행씩 처리 후 rerun) ────
        _CHUNK = 20
        _mi_pending = st.session_state.get("mi_pending_rows")
        if _mi_pending is not None:
            _mi_offset = st.session_state.get("mi_offset", 0)
            _mi_total  = len(_mi_pending)
            _is_last   = (_mi_offset + _CHUNK) >= _mi_total
            _chunk     = _mi_pending[_mi_offset : _mi_offset + _CHUNK]
            _done_so_far = min(_mi_offset + len(_chunk), _mi_total)
            st.progress(_done_so_far / _mi_total)
            st.caption(f"이관 중... ({_done_so_far}/{_mi_total})")
            _chunk_c, _chunk_e = migrate_google_sheet_rows(
                st.session_state["mi_q_campaign"],
                brand_id,
                _chunk,
                overwrite=st.session_state.get("mi_q_overwrite", False),
                participant_count=st.session_state["mi_q_p_count"] if _is_last else None,
                force_participant_count=st.session_state.get("mi_q_force_p", False),
            )
            st.session_state["mi_q_created"] = st.session_state.get("mi_q_created", 0) + _chunk_c
            st.session_state["mi_q_errors"]  = st.session_state.get("mi_q_errors",  []) + _chunk_e
            st.session_state["mi_offset"]    = _mi_offset + _CHUNK
            if _is_last:
                st.session_state["mi_done_result"] = (
                    st.session_state.pop("mi_q_created", 0),
                    st.session_state.pop("mi_q_errors",  []),
                    "업데이트" if st.session_state.get("mi_q_overwrite", False) else "생성",
                )
                for _k in ("mi_pending_rows", "mi_offset", "mi_q_campaign",
                           "mi_q_overwrite", "mi_q_p_count", "mi_q_force_p"):
                    st.session_state.pop(_k, None)
                _load_all.clear()
            st.rerun()

        if "mi_done_result" in st.session_state:
            _dc, _de, _verb = st.session_state.pop("mi_done_result")
            st.success(f"이관 완료: {_dc}개 게시물 {_verb}")
            if _de:
                with st.expander(f"경고 / 건너뜀 ({len(_de)}건)"):
                    for _e in _de:
                        st.warning(_e)
            if "mi_thumb_camp" in st.session_state:
                _tc = st.session_state.pop("mi_thumb_camp")
                _camp_posts = get_campaign_posts(brand_id, _tc)
                _th_posts = [
                    p for p in _camp_posts
                    if p.get("platform") in ("tiktok", "instagram") and not p.get("thumbnail_url")
                ]
                _av_posts = [
                    p for p in _camp_posts
                    if p.get("platform") in ("tiktok", "instagram") and p.get("post_url")
                    and not (
                        p.get("views") or p.get("likes") or p.get("comments")
                        or p.get("saves") or p.get("shares")
                    )
                ]
                if _th_posts:
                    st.session_state["mi_thumb_queue"] = [
                        {"id": p["id"], "url": p["post_url"], "name": p.get("influencer_name") or ""}
                        for p in _th_posts
                    ]
                    st.session_state["mi_thumb_off"] = 0
                if _av_posts:
                    st.session_state["mi_apify_queue"] = [
                        {
                            "id": p["id"], "url": p["post_url"], "platform": p["platform"],
                            "name": p.get("influencer_name") or "unknown",
                        }
                        for p in _av_posts
                    ]
                    st.session_state["mi_apify_off"] = 0
                if _th_posts or _av_posts:
                    st.rerun()

        # ── 썸네일 스크랩 단계 (이관 완료 후 자동 실행) ──────────────────────
        if st.session_state.get("mi_thumb_queue") is not None:
            _th_q     = st.session_state["mi_thumb_queue"]
            _th_off   = st.session_state.get("mi_thumb_off", 0)
            _TH_N     = 3
            _th_total = len(_th_q)
            _th_chunk = _th_q[_th_off : _th_off + _TH_N]
            _th_done  = min(_th_off + _TH_N, _th_total)
            st.progress(_th_done / _th_total, text=f"썸네일 스크랩 중... ({_th_done}/{_th_total})")
            if _th_chunk:
                for _tj in _th_chunk:
                    try:
                        _t = fetch_and_upload_thumbnail(
                            _tj["url"], _tj["name"], _sanitize_storage_key(_tj["id"])
                        )
                        if _t:
                            update_campaign_post_thumbnail(_tj["id"], brand_id, _t)
                    except Exception:
                        pass
                st.session_state["mi_thumb_off"] = _th_off + _TH_N
                st.rerun()
            else:
                st.session_state.pop("mi_thumb_queue")
                st.session_state.pop("mi_thumb_off", None)
                _load_all.clear()
                st.rerun()

        # ── 값 자동 트래킹 단계 (URL은 있지만 지표가 비어있는 게시물, Apify) ──
        if (
            st.session_state.get("mi_apify_queue") is not None
            and st.session_state.get("mi_thumb_queue") is None
        ):
            _av_q = st.session_state["mi_apify_queue"]
            _av_off = st.session_state.get("mi_apify_off", 0)
            _AV_N = 8
            _av_total = len(_av_q)
            _av_chunk = _av_q[_av_off:_av_off + _AV_N]
            _av_done = min(_av_off + _AV_N, _av_total)
            st.progress(_av_done / _av_total, text=f"값 자동 트래킹 중 (Apify)... ({_av_done}/{_av_total})")
            if _av_chunk:
                _av_batch = fetch_metrics_from_apify_batch(
                    [(aj["url"], aj["platform"]) for aj in _av_chunk]
                )
                for _aj in _av_chunk:
                    try:
                        _m, _ = _av_batch.get(_aj["url"], (None, "알 수 없는 오류"))
                        if _m:
                            update_campaign_post(_aj["id"], brand_id, {
                                "views": _m["views"], "likes": _m["likes"],
                                "comments": _m["comments"], "saves": _m["saves"],
                                "shares": _m["shares"],
                            })
                            if _m.get("thumbnail_url"):
                                _stored = upload_thumbnail(
                                    _m["thumbnail_url"], _aj["name"], _sanitize_storage_key(_aj["id"]),
                                )
                                if _stored:
                                    update_campaign_post_thumbnail(_aj["id"], brand_id, _stored)
                    except Exception:
                        pass
                st.session_state["mi_apify_off"] = _av_off + _AV_N
                st.rerun()
            else:
                st.session_state.pop("mi_apify_queue")
                st.session_state.pop("mi_apify_off", None)
                _load_all.clear()
                st.success("값 자동 트래킹이 완료되었습니다.")
                st.rerun()

        # ── 공통 처리 로직 ────────────────────────────────────────────────────
        if raw_csv is not None:
            try:
                raw_csv.columns = [c.strip().lower() for c in raw_csv.columns]

                col_aliases = {
                    "name":          ["name", "full name", "인플루언서", "influencer", "influencer_name"],
                    "ig_url":        ["ig_url", "posting url (ig)", "ig url", "instagram_url", "instagram url"],
                    "tt_url":        ["tt_url", "posting url (tt)", "tt url", "tiktok_url", "tiktok url"],
                    "x_url":         ["x_url", "posting url (x)", "x url", "twitter_url", "x/twitter url"],
                    "lips_url":      ["lips_url", "others(lips)", "others(lip)", "lips url", "lips posting url", "other url"],
                    "upload_day":    ["upload_day", "upload day", "upload day(within the last month)", "uploadday", "날짜", "date", "visit date"],
                    "tt_views":      ["tt_views", "views", "view", "조회수", "재생수"],
                    "tt_likes":      ["tt_likes", "likes", "likes▼", "likes♥", "like", "좋아요"],
                    "tt_comments":   ["tt_comments", "comments", "comment", "댓글"],
                    "tt_saves":      ["tt_saves", "saves", "save", "저장"],
                    "tt_shares":     ["tt_shares", "shares", "share", "공유"],
                    "ig_views":      ["ig_views", "views(ig)", "views_ig"],
                    "ig_likes":      ["ig_likes", "likes(ig)", "likes▼(ig)", "likes♥(ig)", "likes_ig"],
                    "ig_comments":   ["ig_comments", "comments(ig)", "comments_ig"],
                    "ig_saves":      ["ig_saves", "saves(ig)", "saves_ig"],
                    "ig_shares":     ["ig_shares", "shares(ig)", "shares_ig"],
                    "x_views":       ["x_views", "views(x)", "views_x"],
                    "x_likes":       ["x_likes", "likes(x)", "likes_x"],
                    "x_comments":    ["x_comments", "comments(x)", "comments_x"],
                    "x_saves":       ["x_saves", "saves(x)", "saves_x"],
                    "x_shares":      ["x_shares", "shares(x)", "shares_x"],
                    "other_views":   ["other_views", "lips_views", "views(lips)", "views(other)"],
                    "other_likes":   ["other_likes", "lips_likes", "likes(lips)", "likes(other)"],
                    "other_comments":["other_comments", "lips_comments", "comments(lips)"],
                    "other_saves":   ["other_saves", "lips_saves", "saves(lips)"],
                    "other_shares":  ["other_shares", "lips_shares", "shares(lips)"],
                }

                def _find_col(aliases: list[str]) -> str | None:
                    for a in aliases:
                        if a in raw_csv.columns:
                            return a
                    return None

                mapped = {field: _find_col(aliases) for field, aliases in col_aliases.items()}

                if not mapped.get("name"):
                    st.error("필수 컬럼 누락: name (인플루언서명). 헤더를 확인해주세요.")
                else:
                    def _val(r, field, default=0):
                        col = mapped.get(field)
                        return r[col] if col and col in r.index else default

                    def _clean(v): return "" if str(v).strip().lower() in ("","nan","none","-") else str(v).strip()

                    rows_to_migrate = []
                    for _, r in raw_csv.iterrows():
                        rows_to_migrate.append({
                            "name":           str(_val(r, "name", "")),
                            "ig_url":         str(_val(r, "ig_url", "")),
                            "tt_url":         str(_val(r, "tt_url", "")),
                            "x_url":          str(_val(r, "x_url", "")),
                            "lips_url":       str(_val(r, "lips_url", "")),
                            "upload_day":     str(_val(r, "upload_day", "")),
                            "tt_views":       _val(r, "tt_views"),
                            "tt_likes":       _val(r, "tt_likes"),
                            "tt_comments":    _val(r, "tt_comments"),
                            "tt_saves":       _val(r, "tt_saves"),
                            "tt_shares":      _val(r, "tt_shares"),
                            "ig_views":       _val(r, "ig_views"),
                            "ig_likes":       _val(r, "ig_likes"),
                            "ig_comments":    _val(r, "ig_comments"),
                            "ig_saves":       _val(r, "ig_saves"),
                            "ig_shares":      _val(r, "ig_shares"),
                            "x_views":        _val(r, "x_views"),
                            "x_likes":        _val(r, "x_likes"),
                            "x_comments":     _val(r, "x_comments"),
                            "x_saves":        _val(r, "x_saves"),
                            "x_shares":       _val(r, "x_shares"),
                            "other_views":    _val(r, "other_views"),
                            "other_likes":    _val(r, "other_likes"),
                            "other_comments": _val(r, "other_comments"),
                            "other_saves":    _val(r, "other_saves"),
                            "other_shares":   _val(r, "other_shares"),
                        })

                    # 이름이 빈 행(구분용 공백 행 등)은 발송 인원 집계에서 제외
                    rows_to_migrate = [r for r in rows_to_migrate if _clean(r.get("name", ""))]

                    # ── 업로드율 미리보기 (upload_day 기준) ───────────────
                    uploaded_cnt = sum(
                        1 for r in rows_to_migrate
                        if _clean(r.get("upload_day", ""))
                    )
                    no_url_cnt   = len(rows_to_migrate) - uploaded_cnt
                    u_rate       = round(uploaded_cnt / len(rows_to_migrate) * 100, 1) if rows_to_migrate else 0

                    pv1, pv2, pv3, pv4 = st.columns(4)
                    pv1.metric("📦 총 발송 인원", f"{len(rows_to_migrate)}명")
                    pv2.metric("📤 업로드 인원",  f"{uploaded_cnt}명")
                    pv3.metric("📊 업로드율",      f"{u_rate:.1f}%")
                    pv4.metric("⏳ 미업로드",      f"{no_url_cnt}명")

                    # ── 미리보기 테이블 ────────────────────────────────────
                    st.markdown("**미리보기** (상위 5행)")
                    preview_cols = ["name", "tt_url", "ig_url", "x_url", "lips_url", "upload_day",
                                    "tt_views", "tt_likes", "ig_views", "ig_likes"]
                    pv_df = pd.DataFrame(rows_to_migrate)
                    st.dataframe(
                        pv_df[[c for c in preview_cols if c in pv_df.columns]].head(5),
                        use_container_width=True, hide_index=True,
                    )

                    # ── 플랫폼별 현황 ──────────────────────────────────────
                    info_parts = []
                    dual_cnt  = sum(1 for r in rows_to_migrate if _clean(r.get("tt_url","")) and _clean(r.get("ig_url","")))
                    x_cnt     = sum(1 for r in rows_to_migrate if _clean(r.get("x_url","")))
                    lips_cnt  = sum(1 for r in rows_to_migrate if _clean(r.get("lips_url","")))
                    if dual_cnt:  info_parts.append(f"TikTok+Instagram 동시: **{dual_cnt}명**")
                    if x_cnt:     info_parts.append(f"X: **{x_cnt}명**")
                    if lips_cnt:  info_parts.append(f"LIPS/기타: **{lips_cnt}명**")
                    if info_parts:
                        st.info("  ·  ".join(info_parts))

                    oc1, oc2 = st.columns([2, 1])
                    overwrite_mode = oc1.checkbox(
                        "🔄 기존 데이터 덮어쓰기 (수치가 잘못 저장된 경우)",
                        value=False,
                        key="mi_overwrite",
                        help="이미 등록된 URL의 지표를 현재 데이터로 업데이트합니다.",
                    )
                    manual_p_count = oc2.number_input(
                        "발송 인원 직접 입력 (0=시트 행수 사용)",
                        min_value=0,
                        value=0,
                        step=1,
                        key="mi_p_count_override",
                        help="0이면 시트 행수를 자동 사용. 잘못 저장된 경우 여기서 수정하세요.",
                    )
                    final_p_count = int(manual_p_count) if manual_p_count > 0 else len(rows_to_migrate)

                    if st.button(
                        f"✅ {len(rows_to_migrate)}개 행 이관 시작 (발송인원 {final_p_count}명 저장)",
                        key="mi_run",
                    ):
                        st.session_state["mi_pending_rows"] = rows_to_migrate
                        st.session_state["mi_offset"]       = 0
                        st.session_state["mi_q_created"]    = 0
                        st.session_state["mi_q_errors"]     = []
                        st.session_state["mi_q_campaign"]   = mi_campaign_id
                        st.session_state["mi_q_overwrite"]  = overwrite_mode
                        st.session_state["mi_q_p_count"]    = final_p_count
                        st.session_state["mi_q_force_p"]    = (manual_p_count > 0)
                        st.session_state["mi_thumb_camp"]   = mi_campaign_id
                        st.rerun()

            except Exception as ex:
                st.error(f"처리 오류: {ex}")

# ═══════════════════════════════════════════════════════════════
# Tab 5 – 댓글
# ═══════════════════════════════════════════════════════════════

with tab5:
    st.subheader("💬 게시물 댓글")

    # ── 댓글 조회 ────────────────────────────────────────────────────────────
    if df.empty:
        st.info("게시물 데이터가 없습니다. '게시물 관리' 탭에서 게시물을 추가해주세요.")
    else:
        # TikTok + Instagram 모두 선택 가능
        viewable_posts = [
            p for p in posts
            if (p.get("platform") == "tiktok" and _aweme_id_from_url(p.get("post_url","")))
            or (p.get("platform") == "instagram" and p.get("post_url",""))
        ]

        if not viewable_posts:
            st.info("현재 필터에 댓글을 볼 수 있는 게시물이 없습니다.")
        else:
            def _post_label(p):
                plat = "TT" if p.get("platform") == "tiktok" else "IG"
                name = p.get("influencer_name","")
                if p.get("platform") == "tiktok":
                    key = _aweme_id_from_url(p["post_url"]) or p["post_url"]
                else:
                    key = p["post_url"].split("?")[0].rstrip("/").split("/")[-1]
                return f"[{plat}] {name} · {key}"

            post_label_map = {_post_label(p): p for p in viewable_posts}
            sel_label = st.selectbox("게시물 선택", list(post_label_map.keys()), key="cmt_post_sel")
            sel_post  = post_label_map[sel_label]
            is_tt     = sel_post.get("platform") == "tiktok"

            c_left, c_right = st.columns([3, 1])
            with c_left:
                if is_tt:
                    aweme_id = _aweme_id_from_url(sel_post["post_url"])
                    st.caption(f"TikTok · awemeId: `{aweme_id}` · [게시물 열기]({sel_post.get('post_url','')})")
                else:
                    st.caption(f"Instagram · [게시물 열기]({sel_post.get('post_url','')})")
            with c_right:
                if st.button("🔄 새로고침", key="cmt_refresh"):
                    _load_comments_tt.clear()
                    _load_comments_ig.clear()
                    st.rerun()

            if is_tt:
                comments = _load_comments_tt(_aweme_id_from_url(sel_post["post_url"]))
            else:
                comments = _load_comments_ig(sel_post["post_url"])

            if not comments:
                st.info("이 게시물에 가져온 댓글이 없습니다. 아래에서 스프레드시트로 댓글을 가져오세요.")
            else:
                cmt_search = st.text_input(
                    "댓글 검색",
                    placeholder="🔍  내용 또는 사용자명 검색",
                    label_visibility="collapsed",
                    key="cmt_search",
                )
                filtered = comments
                if cmt_search:
                    kw = cmt_search.lower()
                    filtered = [
                        c for c in comments
                        if kw in (c.get("text") or "").lower()
                        or kw in (c.get("username") or "").lower()
                        or kw in (c.get("display_name") or "").lower()
                    ]
                st.caption(f"총 {len(comments)}개 · 표시 {len(filtered)}개 (좋아요 순)")
                st.divider()
                _render_comments(filtered)

    st.divider()

    # ── 댓글 Google Sheets 가져오기 ──────────────────────────────────────────
    with st.expander("📥 댓글 Google Sheets로 가져오기", expanded=False):
        cmt_plat = st.radio("플랫폼", ["TikTok", "Instagram"], horizontal=True, key="cmt_import_plat")

        if cmt_plat == "TikTok":
            st.markdown("""
**TikTok 컬럼 형식**

`id` · `text` · `createdAt` · `likeCount` · `replyCount` · `commentLanguage` · **`awemeId`** · `user.username` · `user.displayName` · `user.avatarUrl` · `user.region`
""")
        else:
            st.markdown("""
**Instagram 컬럼 형식**

`id` · `text` · `timestamp` · **`postUrl`** · `ownerUsername` · `ownerProfilePicUrl`
""")

        cmt_sheets_url = st.text_input(
            "Google Sheets URL",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key="cmt_sheets_url",
        )

        if cmt_sheets_url:
            m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", cmt_sheets_url)
            if not m:
                st.error("올바른 Google Sheets URL이 아닙니다.")
            else:
                cmt_sheet_id = m.group(1)
                gid_m = re.search(r"[#&?]gid=(\d+)", cmt_sheets_url)
                cmt_gid = gid_m.group(1) if gid_m else "0"
                cmt_csv_url = (
                    f"https://docs.google.com/spreadsheets/d/{cmt_sheet_id}"
                    f"/export?format=csv&gid={cmt_gid}"
                )

                fetch_col2, _ = st.columns([1, 3])
                if fetch_col2.button("📥 시트 불러오기", key="cmt_fetch_btn"):
                    try:
                        import requests as _http2
                        resp2 = _http2.get(cmt_csv_url, timeout=20)
                        resp2.raise_for_status()
                        cmt_df = pd.read_csv(io.StringIO(resp2.content.decode("utf-8-sig")))
                        st.session_state["cmt_fetched_df"]   = cmt_df.to_dict(orient="list")
                        st.session_state["cmt_fetched_url"]  = cmt_sheets_url
                        st.session_state["cmt_fetched_plat"] = cmt_plat
                        st.success(f"시트 불러오기 완료: {len(cmt_df)}행")
                    except Exception as fe:
                        st.error(f"불러오기 실패: {fe}")

                if (
                    st.session_state.get("cmt_fetched_url") == cmt_sheets_url
                    and "cmt_fetched_df" in st.session_state
                ):
                    cmt_raw = pd.DataFrame(st.session_state["cmt_fetched_df"])
                    cmt_raw.columns = [c.strip().lower().replace(".", "_") for c in cmt_raw.columns]

                    def _fc(aliases):
                        for a in aliases:
                            if a in cmt_raw.columns:
                                return a
                        return None

                    def _sv(row, col, default=None):
                        if col and col in row.index:
                            v = row[col]
                            return None if str(v).strip().lower() in ("nan","none","") else v
                        return default

                    col_id = _fc(["id", "comment_id"])

                    if cmt_plat == "TikTok":
                        col_aweme   = _fc(["awemeid", "aweme_id", "videoid", "video_id"])
                        col_text    = _fc(["text", "content", "comment"])
                        col_created = _fc(["createdat", "created_at", "date", "time", "timestamp"])
                        col_likes   = _fc(["likecount", "like_count", "likes"])
                        col_replies = _fc(["replycount", "reply_count", "replies"])
                        col_lang    = _fc(["commentlanguage", "language", "lang"])
                        col_authliked = _fc(["isauthorliked", "is_author_liked"])
                        col_uid     = _fc(["user_id", "userid"])
                        col_uname   = _fc(["user_username", "username"])
                        col_dname   = _fc(["user_displayname", "display_name", "displayname"])
                        col_avatar  = _fc(["user_avatarurl", "avatar_url", "avatarurl"])
                        col_region    = _fc(["user_region", "region"])
                        col_user_lang = _fc(["user_language", "user_lang"])

                        if not col_id or not col_aweme:
                            st.error(f"필수 컬럼 누락: {'id' if not col_id else ''} {'awemeId' if not col_aweme else ''}")
                        else:
                            rows_cmt = []
                            for _, r in cmt_raw.iterrows():
                                cmt_id    = str(_sv(r, col_id) or "")
                                aweme_val = str(_sv(r, col_aweme) or "")
                                if not cmt_id or not aweme_val:
                                    continue
                                rows_cmt.append({
                                    "id":              cmt_id,
                                    "aweme_id":        aweme_val,
                                    "platform":        "tiktok",
                                    "text":            str(_sv(r, col_text) or ""),
                                    "created_at":      str(_sv(r, col_created) or "") or None,
                                    "like_count":      int(float(_sv(r, col_likes) or 0)),
                                    "reply_count":     int(float(_sv(r, col_replies) or 0)),
                                    "language":        str(_sv(r, col_lang) or "") or None,
                                    "is_author_liked": bool(_sv(r, col_authliked)) if col_authliked else False,
                                    "user_id":         str(_sv(r, col_uid) or "") or None,
                                    "username":        str(_sv(r, col_uname) or "") or None,
                                    "display_name":    str(_sv(r, col_dname) or "") or None,
                                    "avatar_url":      str(_sv(r, col_avatar) or "") or None,
                                    "user_region":     str(_sv(r, col_region)    or "") or None,
                                    "user_language":   str(_sv(r, col_user_lang) or "") or None,
                                })

                            st.caption(f"유효 댓글 {len(rows_cmt)}개 · 미리보기 (상위 5행)")
                            st.dataframe(
                                pd.DataFrame(rows_cmt)[["aweme_id","username","text","like_count"]].head(5),
                                use_container_width=True, hide_index=True,
                            )
                            if st.button(f"✅ {len(rows_cmt)}개 TikTok 댓글 가져오기", key="cmt_run_tt"):
                                with st.spinner("댓글 저장 중..."):
                                    cnt, errs = bulk_upsert_post_comments(rows_cmt)
                                st.success(f"완료: {cnt}개 저장")
                                for e in errs:
                                    st.warning(e)
                                _load_comments_tt.clear()
                                st.rerun()

                    else:  # Instagram
                        col_post_url = _fc(["posturl", "post_url", "url", "link"])
                        col_text     = _fc(["text", "content", "comment"])
                        col_created  = _fc(["timestamp", "createdat", "created_at", "date"])
                        col_uname    = _fc(["ownerusername", "username", "owner_username"])
                        col_avatar   = _fc(["ownerprofilepicurl", "avatar_url", "profile_pic"])

                        if not col_id or not col_post_url:
                            st.error(f"필수 컬럼 누락: {'id' if not col_id else ''} {'postUrl' if not col_post_url else ''}")
                        else:
                            rows_cmt = []
                            for _, r in cmt_raw.iterrows():
                                cmt_id   = str(_sv(r, col_id) or "")
                                post_url_val = str(_sv(r, col_post_url) or "")
                                if not cmt_id or not post_url_val:
                                    continue
                                # URL 정규화 (쿼리파라미터 제거)
                                norm_url = post_url_val.split("?")[0].rstrip("/")
                                rows_cmt.append({
                                    "id":           cmt_id,
                                    "post_url":     norm_url,
                                    "platform":     "instagram",
                                    "aweme_id":     "",
                                    "text":         str(_sv(r, col_text) or ""),
                                    "created_at":   str(_sv(r, col_created) or "") or None,
                                    "like_count":   0,
                                    "reply_count":  0,
                                    "username":     str(_sv(r, col_uname) or "") or None,
                                    "avatar_url":   str(_sv(r, col_avatar) or "") or None,
                                })

                            st.caption(f"유효 댓글 {len(rows_cmt)}개 · 미리보기 (상위 5행)")
                            st.dataframe(
                                pd.DataFrame(rows_cmt)[["post_url","username","text"]].head(5),
                                use_container_width=True, hide_index=True,
                            )
                            if st.button(f"✅ {len(rows_cmt)}개 Instagram 댓글 가져오기", key="cmt_run_ig"):
                                with st.spinner("댓글 저장 중..."):
                                    cnt, errs = bulk_upsert_post_comments(rows_cmt)
                                st.success(f"완료: {cnt}개 저장")
                                for e in errs:
                                    st.warning(e)
                                _load_comments_ig.clear()
                                st.rerun()
