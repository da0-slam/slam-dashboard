"""공개 콘텐츠 성과 리포트 뷰어 — 토큰 링크로 로그인 없이 접근 가능.
읽기 전용 — 게시물 관리/댓글 등 편집 기능은 포함하지 않음."""
import streamlit as st
import pandas as pd

from utils.storage_client import resolve_content_report_token  # noqa: E402
from utils.supabase_client import (  # noqa: E402
    aweme_id_from_url, aweme_id_from_url_fast, get_brands, get_campaigns, get_campaign_posts,
    get_influencer_cover_map, get_post_comments, get_post_comments_batch,
)
from utils.comment_ui import (  # noqa: E402
    render_comment_distribution_charts, render_comments,
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


@st.cache_data(ttl=60, max_entries=300, show_spinner=False)
def _load_comments_tt(aweme_id: str) -> list[dict]:
    return get_post_comments(aweme_id=aweme_id)


@st.cache_data(ttl=60, max_entries=300, show_spinner=False)
def _load_comments_ig(post_url: str) -> list[dict]:
    return get_post_comments(post_url=post_url)


@st.dialog("💬 댓글", width="large")
def _show_comments_dialog(orig_post: dict) -> None:
    is_tt = orig_post.get("platform") == "tiktok"
    st.caption(f"{'TikTok' if is_tt else 'Instagram'} · {orig_post.get('influencer_name','')} · [게시물 열기]({orig_post.get('post_url','')})")
    if is_tt:
        aweme = aweme_id_from_url(orig_post["post_url"])
        cmts  = _load_comments_tt(aweme) if aweme else []
    else:
        cmts = _load_comments_ig(orig_post["post_url"])

    if not cmts:
        st.info("이 게시물에 수집된 댓글이 없습니다.")
        return

    st.caption(f"총 {len(cmts)}개")
    st.divider()
    render_comments(cmts)


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

# ── 목차 (비로그인 공개 페이지 — 사이드바 내부 메뉴 대신 페이지 내 이동용) ──────
with st.sidebar:
    st.markdown(f"**{brand_name}**")
    st.caption(camp["name"])
    st.markdown("#### 목차")
    st.markdown("""
<a href="#sec-kpi" style="display:block;padding:6px 0;text-decoration:none;">📊 요약 지표</a>
<a href="#sec-chart" style="display:block;padding:6px 0;text-decoration:none;">📈 차트</a>
<a href="#sec-comments" style="display:block;padding:6px 0;text-decoration:none;">💬 댓글 분석</a>
<a href="#sec-posts" style="display:block;padding:6px 0;text-decoration:none;">🖼️ 게시물</a>
<a href="#sec-summary" style="display:block;padding:6px 0;text-decoration:none;">👥 인플루언서 요약</a>
<a href="#sec-top" style="display:block;padding:6px 0;text-decoration:none;">⭐ 우수 콘텐츠</a>
""", unsafe_allow_html=True)

st.divider()

if df.empty:
    st.info("아직 등록된 게시물 데이터가 없습니다.")
    st.stop()

# ── KPI ───────────────────────────────────────────────────────────────────
st.markdown('<div id="sec-kpi"></div>', unsafe_allow_html=True)

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
x_posts        = int((df["platform"] == "x").sum())
xhs_posts      = int((df["platform"] == "xiaohongshu").sum())
other_posts    = int((df["platform"] == "other").sum())
total_views    = int(df["views"].sum())
total_likes    = int(df["likes"].sum())
total_comments = int(df["comments"].sum())
total_saves    = int(df["saves"].sum())
total_shares   = int(df["shares"].sum())
avg_er         = round(float(df["engagement_rate"].mean()), 2)

p_count = camp.get("participant_count")
if p_count:
    u_rate = round(total_influencers / p_count * 100, 1)
    ur1, ur2, ur3 = st.columns(3)
    ur1.metric("📦 발송 인원", f"{p_count:,}명")
    ur2.metric("📤 업로드 인원", f"{total_influencers:,}명")
    ur3.metric("📊 업로드율", f"{u_rate:.1f}%")
    st.divider()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("참여 인플루언서", f"{total_influencers:,}")
c2.metric("총 게시물", f"{total_posts:,}")
c3.metric("Instagram", f"{ig_posts:,}")
c4.metric("TikTok", f"{tt_posts:,}")
c5.metric("X / 기타", f"{x_posts + xhs_posts + other_posts:,}")

c6, c7, c8, c9, c10 = st.columns(5)
c6.metric("평균 참여율", f"{avg_er:.1f}%")
c7.metric("총 조회수", f"{total_views:,}")
c8.metric("총 좋아요", f"{total_likes:,}")
c9.metric("총 댓글", f"{total_comments:,}")
c10.metric("총 저장", f"{total_saves:,}")

st.divider()

# ── 차트 ──────────────────────────────────────────────────────────────────
st.markdown('<div id="sec-chart"></div>', unsafe_allow_html=True)
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
        .agg(총_조회수=("views", "sum"), 총_좋아요=("likes", "sum"))
        .reset_index()
    )
    plat_df["platform"] = plat_df["platform"].map(_plat_label_map)
    plat_df = plat_df.set_index("platform")
    st.bar_chart(plat_df[["총_조회수", "총_좋아요"]])

st.divider()

# ── 틱톡 댓글 분석 (지역/언어 분포) ──────────────────────────────────────────
st.markdown('<div id="sec-comments"></div>', unsafe_allow_html=True)
st.subheader("💬 틱톡 댓글 분석")

_tt_aweme_ids = [
    aweme_id_from_url_fast(p.get("post_url", ""))
    for p in posts if p.get("platform") == "tiktok"
]
_tt_aweme_ids = [a for a in _tt_aweme_ids if a]

if not _tt_aweme_ids:
    st.info("분석할 TikTok 게시물이 없습니다.")
else:
    _tt_comments = get_post_comments_batch(_tt_aweme_ids)
    if not _tt_comments:
        st.info("아직 수집된 TikTok 댓글이 없습니다.")
    else:
        st.caption(f"TikTok 게시물 {len(_tt_aweme_ids)}건 · 댓글 {len(_tt_comments):,}개 기준")
        render_comment_distribution_charts(_tt_comments)

st.divider()

st.markdown('<div id="sec-posts"></div>', unsafe_allow_html=True)
# ── 게시물 그리드 / 목록 ────────────────────────────────────────────────────


def _is_displayable_thumb(url) -> bool:
    """브라우저에서 실제로 표시 가능한 썸네일 URL인지 확인."""
    if not url or not isinstance(url, str) or url != url:
        return False
    if "supabase" in url:
        return True
    if "tiktokcdn" in url or "tiktok.com" in url:
        return True
    if "imginn.com" in url or "picuki.com" in url:
        return True
    if "pbs.twimg.com" in url or "twimg.com" in url:
        return True
    if url.lower().split("?")[0].endswith((".js", ".css", ".json")):
        return False
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


disp = df.copy()
_plat_map = {"instagram": "Instagram", "tiktok": "TikTok", "x": "X", "other": "기타"}
disp["플랫폼"] = disp["platform"].map(_plat_map).fillna("기타")

show_cols = ["influencer_name", "플랫폼", "post_url",
             "views", "likes", "comments", "saves", "shares", "engagement_rate"]
if "thumbnail_url" in disp.columns:
    show_cols = ["thumbnail_url"] + show_cols
show_cols = [c for c in show_cols if c in disp.columns]
_rename = {
    "influencer_name": "인플루언서", "post_url": "게시물 URL", "views": "조회수",
    "likes": "좋아요", "comments": "댓글", "saves": "저장", "shares": "공유",
    "engagement_rate": "참여율(%)", "thumbnail_url": "썸네일",
}
disp = disp[show_cols].rename(columns=_rename)

view_mode = st.radio("게시물 보기 방식", ["그리드", "목록"], horizontal=True, key="crv_view_mode")

if view_mode == "그리드":
    _cover_map_all = get_influencer_cover_map()
    _name_to_cover: dict = {}
    for _p in posts:
        _iid   = (_p.get("influencer_id")   or "").strip().lower()
        _iname = (_p.get("influencer_name") or "").strip()
        _cv = _cover_map_all.get(_iid) or _cover_map_all.get(_iname.lower())
        if _cv and _iname:
            _name_to_cover[_iname] = _cv

    _all_records = disp.to_dict(orient="records")
    rows = []
    for _r in _all_records:
        _thumb = _r.get("썸네일") or ""
        if _is_displayable_thumb(_thumb):
            rows.append({**_r, "_img": _thumb})
        else:
            _cv = _name_to_cover.get(_r.get("인플루언서") or "")
            if _cv:
                rows.append({**_r, "_img": _cv})

    rows.sort(key=lambda r: (
        1 if r.get("플랫폼") == "X" else 0,
        -(r.get("조회수", 0) or 0),
    ))
    _seen_keys: set = set()
    _deduped: list = []
    for _r in rows:
        _url_key   = (_r.get("게시물 URL") or "").split("?")[0].rstrip("/")
        _thumb_key = (_r.get("_img") or _r.get("썸네일") or "").split("?")[0]
        _dup = (_url_key and _url_key in _seen_keys) or (_thumb_key and _thumb_key in _seen_keys)
        if _dup:
            continue
        if _url_key:   _seen_keys.add(_url_key)
        if _thumb_key: _seen_keys.add(_thumb_key)
        _deduped.append(_r)
    rows = _deduped

    if not rows:
        st.info("썸네일이 있는 게시물이 없습니다. 목록 보기를 이용하세요.")
    else:
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
                _norm_url = url.split("?")[0].rstrip("/")
                _orig = _url_to_post.get(_norm_url)
                _has_comments = bool(
                    (_orig and _orig.get("platform") == "tiktok" and aweme_id_from_url_fast(url))
                    or (_orig and _orig.get("platform") == "instagram")
                )
                if _has_comments and _orig:
                    if col.button("💬 댓글 보기", key=f"crv_cmt_{idx}_{cidx}", use_container_width=True):
                        _show_comments_dialog(_orig)
else:
    st.subheader("게시물 목록")
    list_disp = disp[[c for c in disp.columns if c != "썸네일"]]
    st.dataframe(
        list_disp, use_container_width=True, hide_index=True,
        column_config={
            "게시물 URL": st.column_config.LinkColumn("게시물 URL", display_text="🔗 열기"),
            "조회수":     st.column_config.NumberColumn("조회수", format="%d"),
            "좋아요":     st.column_config.NumberColumn("좋아요", format="%d"),
            "댓글":       st.column_config.NumberColumn("댓글",   format="%d"),
            "저장":       st.column_config.NumberColumn("저장",   format="%d"),
            "공유":       st.column_config.NumberColumn("공유",   format="%d"),
            "참여율(%)":  st.column_config.NumberColumn("참여율(%)", format="%.2f%%"),
        },
    )

st.divider()

# ── 인플루언서별 성과 요약 ────────────────────────────────────────────────
st.markdown('<div id="sec-summary"></div>', unsafe_allow_html=True)
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
grp["커버"] = grp["influencer_name"].apply(lambda n: _cover.get(n.lower()) or "")
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
st.markdown('<div id="sec-top"></div>', unsafe_allow_html=True)
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
