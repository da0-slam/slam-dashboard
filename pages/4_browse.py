import io
import re
import requests
import pandas as pd
import streamlit as st
from utils.auth import require_auth, sidebar_user_info, get_active_brand_id
from utils.supabase_client import (
    get_brands, get_brand_by_id, get_campaigns,
    get_browse_contents, get_influencer_contents,
    get_brand_selection_map, get_campaign_selection_map,
    select_influencer, update_selection_status, remove_selection,
    add_to_campaign, update_campaign_selection, remove_campaign_selection,
    get_user_profile, get_note_counts, get_recent_notes,
    bulk_upsert_koc_contents,
)
from utils.notes_ui import show_notes_dialog, render_notes_inline, _avatar_color, _time_label

st.set_page_config(page_title="KOC Intelligence Viewer", page_icon="🎬", layout="wide")
user = require_auth()
sidebar_user_info()

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.koc-card{position:relative;border-radius:12px;overflow:hidden;background:#111;
          aspect-ratio:9/16;width:100%;}
.koc-card img{width:100%;height:100%;object-fit:cover;display:block;}
.koc-placeholder{width:100%;height:100%;display:flex;align-items:center;
                 justify-content:center;font-size:3rem;background:#1a1a2e;}
.koc-grade{position:absolute;top:10px;left:10px;border-radius:6px;
           padding:3px 10px;color:#fff;font-weight:700;font-size:13px;}
.koc-rank{position:absolute;top:10px;right:10px;background:rgba(0,0,0,.65);
          border-radius:6px;padding:3px 10px;color:#fff;font-size:12px;}
.koc-info{position:absolute;bottom:0;left:0;right:0;
          background:linear-gradient(transparent,rgba(0,0,0,.8));
          padding:20px 10px 10px;}
.koc-name{color:#fff;font-weight:700;font-size:13px;margin:0;}
.koc-stat{color:rgba(255,255,255,.8);font-size:11px;margin:2px 0 0;}
.koc-ig{display:inline-flex;align-items:center;gap:4px;margin-top:4px;
        background:rgba(255,255,255,.12);border-radius:4px;padding:2px 6px;
        color:#fff;font-size:10px;font-weight:600;text-decoration:none;}
.koc-ig:hover{background:rgba(255,255,255,.22);}
.koc-plat{display:inline-block;border-radius:3px;padding:1px 5px;
          font-size:9px;font-weight:700;margin-bottom:2px;letter-spacing:.3px;}
.koc-plat-tt{background:#ff0050;color:#fff;}
.koc-plat-ig{background:linear-gradient(45deg,#f09433,#dc2743,#bc1888);color:#fff;}
.grade-s{background:#FF6B2C;} .grade-a{background:#3B82F6;}
.grade-b{background:#6B7280;} .grade-c{background:#374151;}
div[data-testid="stHorizontalBlock"] > div {padding: 0 4px;}
</style>
""", unsafe_allow_html=True)

# ─── 사용자 프로필 및 브랜드 확인 ────────────────────────────────────────────
profile       = get_user_profile(user.id)
user_brand_id = get_active_brand_id(profile)
user_role     = profile.get("role", "brand_user")
is_admin      = user_role == "admin"

if not user_brand_id and not is_admin:
    st.error("브랜드 계정이 연결되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

# ─── 헤더 ─────────────────────────────────────────────────────────────────────
_panel_open = st.session_state.get("show_comment_panel", False)

col_logo, col_brand, col_camp = st.columns([3, 2, 2])
with col_logo:
    st.markdown("### 🎯 Slam Global · 인플루언서 탐색")

with col_brand:
    if is_admin:
        brands = get_brands()
        if not brands:
            st.warning("먼저 브랜드사를 등록하세요.")
            st.stop()
        brand_options  = {b["name"]: b["id"] for b in brands}
        sel_brand_name = st.selectbox("브랜드사", list(brand_options.keys()), label_visibility="collapsed")
        sel_brand_id   = brand_options[sel_brand_name]
    else:
        brand = get_brand_by_id(user_brand_id)
        if not brand:
            st.error("브랜드 정보를 불러올 수 없습니다.")
            st.stop()
        sel_brand_id   = user_brand_id
        sel_brand_name = brand.get("name", "")
        st.markdown(f"**{sel_brand_name}**")

with col_camp:
    campaigns     = get_campaigns(sel_brand_id)
    camp_opts     = {"── 즐겨찾기 모드 ──": None} | {c["name"]: c["id"] for c in campaigns}
    sel_camp_name = st.selectbox("캠페인", list(camp_opts.keys()), label_visibility="collapsed")
    sel_camp_id   = camp_opts[sel_camp_name]

st.divider()

# ─── 데이터 로드 + 지표 계산 ─────────────────────────────────────────────────
with st.spinner("데이터 로딩 중..."):
    all_contents = get_browse_contents()


def calc_er(r):
    play = r.get("play_count") or 0
    if play == 0: return 0.0
    eng = sum(r.get(k) or 0 for k in ("like_count","comment_count","share_count","save_count"))
    return eng / play * 100

def calc_grade(er):
    if er >= 10: return "S"
    if er >= 5:  return "A"
    if er >= 2:  return "B"
    return "C"

import re as _re

_LANG_ORDER = [
    "🌐 English",
    "🇰🇷 Korean",
    "🇯🇵 Japanese",
    "🇸🇦 Arabic",
    "🇨🇳 Chinese",
    "❓ Others",
]
# #fypシ / #fypシ゚ 등 영어권도 사용하는 TikTok 바이럴 태그 제거용
_FYP_RE = _re.compile(r'#fyp\S*', _re.IGNORECASE)

def detect_lang(caption: str) -> str:
    if not caption or not caption.strip():
        return "❓ Others"
    text = _FYP_RE.sub('', caption)
    counts = {"🇰🇷 Korean": 0, "🇯🇵 Japanese": 0, "🇸🇦 Arabic": 0, "🇨🇳 Chinese": 0}
    for c in text:
        if '가' <= c <= '힣' or 'ㄱ' <= c <= 'ㆎ':
            counts["🇰🇷 Korean"] += 1
        elif '぀' <= c <= 'ゟ' or '゠' <= c <= 'ヿ':
            counts["🇯🇵 Japanese"] += 1
        elif '؀' <= c <= 'ۿ' or 'ݐ' <= c <= 'ݿ':
            counts["🇸🇦 Arabic"] += 1
        elif '一' <= c <= '鿿':
            counts["🇨🇳 Chinese"] += 1
    valid = {lang: cnt for lang, cnt in counts.items() if cnt >= 3}
    if valid:
        return max(valid, key=valid.get)
    return "🌐 English"

for r in all_contents:
    r["er"]    = calc_er(r)
    r["grade"] = calc_grade(r["er"])
    r["lang"]  = detect_lang(r.get("caption") or "")

# 업로드 연도 파싱
for r in all_contents:
    pt = r.get("posted_at") or ""
    r["year"] = pt[:4] if pt else "?"

# fav_map은 필터에서도 필요하므로 미리 로드
fav_map  = get_brand_selection_map(sel_brand_id)

# ─── 필터 바 ──────────────────────────────────────────────────────────────────
fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([3, 2, 2, 1.5, 1.5, 1])

with fc1:
    grade_filter = st.multiselect(
        "Grade", ["S","A","B","C"], default=["S","A","B","C"],
        label_visibility="collapsed",
        placeholder="Grade 선택"
    )
with fc2:
    all_years = sorted({r["year"] for r in all_contents if r["year"] != "?"}, reverse=True)
    year_filter = st.selectbox(
        "Year", ["ALL"] + all_years,
        label_visibility="collapsed"
    )
with fc3:
    search_kw = st.text_input("검색", placeholder="@username 검색", label_visibility="collapsed")
with fc4:
    sort_by = st.selectbox(
        "정렬", ["Rank","ER %","Date (최신순)","Date (오래된순)"],
        label_visibility="collapsed"
    )
with fc5:
    n_cols = st.selectbox("열", [4, 3, 5], label_visibility="collapsed")
with fc6:
    if st.button("↺", help="최신 데이터로 새로고침", use_container_width=True):
        get_browse_contents.clear()
        st.rerun()

fl1, fl2, fl3 = st.columns([3, 2, 1])
with fl1:
    caption_search = st.text_input(
        "캡션 검색",
        placeholder="Search captions (e.g. skincare, nightroutine, unboxing...)",
        label_visibility="collapsed",
    )
with fl2:
    _langs_in_data = {r["lang"] for r in all_contents}
    _avail_langs = [l for l in _LANG_ORDER if l in _langs_in_data]
    lang_filter = st.multiselect(
        "언어",
        _avail_langs,
        default=[],
        placeholder="언어 필터 (전체)",
        label_visibility="collapsed",
    )
with fl3:
    fav_only = st.toggle("⭐ 즐겨찾기만", value=False)

# ─── 필터 적용 ────────────────────────────────────────────────────────────────
contents = all_contents[:]

if grade_filter:
    contents = [r for r in contents if r["grade"] in grade_filter]
if year_filter and year_filter != "ALL":
    contents = [r for r in contents if r["year"] == year_filter]
if search_kw:
    kw = search_kw.lstrip("@").lower()
    contents = [r for r in contents if kw in r["influencer_id"].lower()]
if caption_search:
    kw = caption_search.lower()
    contents = [r for r in contents if kw in (r.get("caption") or "").lower()]
if lang_filter:
    contents = [r for r in contents if r["lang"] in lang_filter]
if fav_only:
    contents = [r for r in contents if r["influencer_id"] in fav_map]

if sort_by == "ER %":
    contents.sort(key=lambda r: r["er"], reverse=True)
elif sort_by == "Date (최신순)":
    contents.sort(key=lambda r: r.get("posted_at") or "", reverse=True)
elif sort_by == "Date (오래된순)":
    contents.sort(key=lambda r: r.get("posted_at") or "")
else:  # Rank (기본) — 영어권 먼저, 그룹 내 원래 랭크 순서 유지 (stable sort)
    contents.sort(key=lambda r: 0 if r["lang"] == "🌐 English" else 1)

# ─── 페이지네이션 상태 ────────────────────────────────────────────────────────
PAGE_SIZE = 48  # 4열×12행 or 3열×16행

_filter_sig = (tuple(grade_filter), year_filter, search_kw, caption_search, tuple(lang_filter), sort_by, sel_camp_id, fav_only)
if st.session_state.get("_browse_filter_sig") != _filter_sig:
    st.session_state["_browse_filter_sig"] = _filter_sig
    st.session_state["browse_page"] = 0

page        = st.session_state.get("browse_page", 0)
total_pages = max(1, (len(contents) + PAGE_SIZE - 1) // PAGE_SIZE)
page        = min(page, total_pages - 1)

# ─── 상단 통계 ────────────────────────────────────────────────────────────────
total_views = sum(r.get("play_count") or 0 for r in contents)
avg_er      = (sum(r["er"] for r in contents) / len(contents)) if contents else 0
s_cnt       = sum(1 for r in contents if r["grade"] == "S")

def _fmt(n):
    n = n or 0
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:     return f"{n/1_000_000:.1f}M"
    if n >= 1_000:         return f"{n/1_000:.1f}K"
    return str(n)

@st.dialog("인플루언서 영상 전체보기", width="large")
def show_influencer_videos(inf_id: str, brand_id: str, author_email: str, camp_id=None):
    videos = get_influencer_contents(inf_id)
    if not videos:
        st.info("영상 데이터가 없습니다.")
        return

    total_plays = sum(v.get("play_count") or 0 for v in videos)
    avg_plays   = total_plays // len(videos) if videos else 0
    avg_er_val  = sum(
        (sum(v.get(k) or 0 for k in ("like_count","comment_count","share_count","save_count"))
         / (v.get("play_count") or 1) * 100)
        for v in videos
    ) / len(videos)

    # ── 2-컬럼: 영상(좌) + 댓글(우) ─────────────────────────────────────────
    v_col, n_col = st.columns([6, 4], gap="large")

    with v_col:
        st.markdown(
            f"<p style='font-size:18px;font-weight:700;margin:0 0 12px;'>@{inf_id}</p>",
            unsafe_allow_html=True,
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("총 영상 수",  len(videos))
        m2.metric("평균 조회수", _fmt(avg_plays))
        m3.metric("평균 ER",    f"{avg_er_val:.1f}%")
        st.divider()

        COLS = 2
        for chunk_start in range(0, len(videos), COLS):
            row_vids = videos[chunk_start:chunk_start + COLS]
            cols = st.columns(COLS)
            for col, v in zip(cols, row_vids):
                play      = v.get("play_count") or 0
                eng       = sum(v.get(k) or 0 for k in ("like_count","comment_count","share_count","save_count"))
                er        = eng / play * 100 if play else 0.0
                thumbnail = v.get("thumbnail_url") or ""
                video_url = v.get("video_url") or ""
                posted    = (v.get("posted_at") or "")[:10]
                caption   = v.get("caption") or ""

                with col:
                    if thumbnail and video_url:
                        st.markdown(
                            f'<a href="{video_url}" target="_blank">'
                            f'<img src="{thumbnail}" style="width:100%;border-radius:8px;"></a>',
                            unsafe_allow_html=True,
                        )
                    elif thumbnail:
                        st.image(thumbnail, use_container_width=True)
                    else:
                        st.markdown(
                            '<div style="background:#1a1a2e;aspect-ratio:9/16;display:flex;'
                            'align-items:center;justify-content:center;font-size:2rem;'
                            'border-radius:8px;">🎬</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f"<p style='font-size:11px;color:#6b7280;margin:4px 0 0;'>"
                        f"👁 {_fmt(play)} &nbsp;·&nbsp; ER {er:.1f}% &nbsp;·&nbsp; {posted}</p>",
                        unsafe_allow_html=True,
                    )
                    if caption:
                        st.caption(caption[:55] + ("…" if len(caption) > 55 else ""))

    with n_col:
        render_notes_inline(inf_id, brand_id, author_email, camp_id)

def _render_comment_panel(brand_id: str, author_email: str, camp_id):
    """Figma 스타일 오른쪽 댓글 패널."""
    st.markdown("""
    <style>
    .cp-header{font-size:15px;font-weight:700;color:#111;margin:0 0 2px;}
    .cp-sub{font-size:12px;color:#9ca3af;margin:0 0 12px;}
    .cp-entry{display:flex;gap:9px;padding:10px 12px;border-radius:8px;
              cursor:pointer;transition:background .15s;}
    .cp-entry:hover{background:#f3f4f6;}
    .cp-av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;
           justify-content:center;color:#fff;font-size:12px;font-weight:700;flex-shrink:0;margin-top:1px;}
    .cp-inf{font-size:12px;font-weight:700;color:#111;margin:0 0 1px;}
    .cp-meta{font-size:11px;color:#9ca3af;margin:0 0 3px;}
    .cp-text{font-size:12px;color:#374151;margin:0;
             white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;}
    .cp-divider{border:none;border-top:1px solid #f3f4f6;margin:4px 0;}
    </style>
    """, unsafe_allow_html=True)

    recent = get_recent_notes(brand_id, limit=40)

    st.markdown("<p class='cp-header'>💬 댓글</p>", unsafe_allow_html=True)
    st.markdown(
        f"<p class='cp-sub'>{len(recent)}개의 최근 댓글</p>",
        unsafe_allow_html=True,
    )

    # 검색 필터
    _cp_search = st.text_input(
        "댓글 검색",
        placeholder="🔍  인플루언서 또는 내용 검색",
        label_visibility="collapsed",
        key="cp_search",
    )

    st.markdown("<hr class='cp-divider'>", unsafe_allow_html=True)

    if not recent:
        st.markdown(
            "<div style='text-align:center;padding:32px 0;color:#9ca3af;font-size:13px;'>"
            "아직 댓글이 없습니다.</div>",
            unsafe_allow_html=True,
        )
        return

    filtered = recent
    if _cp_search:
        kw = _cp_search.lower()
        filtered = [
            n for n in recent
            if kw in n["influencer_id"].lower() or kw in (n.get("content") or "").lower()
        ]

    for note in filtered:
        inf_id      = note["influencer_id"]
        author_name = (note.get("author_email") or "").split("@")[0]
        initial     = author_name[0].upper() if author_name else "?"
        color       = _avatar_color(author_name)
        time_str    = _time_label(note.get("created_at", ""))
        content_raw = (note.get("content") or "")
        preview     = content_raw[:55] + ("…" if len(content_raw) > 55 else "")

        st.markdown(
            f"""<div class='cp-entry'>
                <div class='cp-av' style='background:{color};'>{initial}</div>
                <div style='flex:1;min-width:0;'>
                    <p class='cp-inf'>@{inf_id}</p>
                    <p class='cp-meta'>{author_name} &nbsp;·&nbsp; {time_str}</p>
                    <p class='cp-text'>{preview}</p>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        if st.button(
            "🎬 영상 + 댓글 보기",
            key=f"cp_open_{note['id']}",
            use_container_width=True,
        ):
            show_influencer_videos(inf_id, brand_id, author_email, camp_id)
        st.markdown("<hr class='cp-divider'>", unsafe_allow_html=True)


m1, m2, m3, m4 = st.columns(4)
m1.metric("Showing",     len(contents))
m2.metric("S Grade",     s_cnt)
m3.metric("Avg ER",      f"{avg_er:.1f}%")
m4.metric("Total Views", _fmt(total_views))

st.divider()

# ─── 선택 상태 로드 ────────────────────────────────────────────────────────────
camp_map = get_campaign_selection_map(sel_camp_id) if sel_camp_id else {}

# 캠페인 모드: 확정 → 후보 → 미선택 → 제외 순서로 정렬
if sel_camp_id:
    status_order = {"confirmed": 0, "candidate": 1, "rejected": 3}
    contents.sort(key=lambda r: status_order.get(
        camp_map.get(r["influencer_id"], {}).get("status", ""), 2
    ))
    st.caption(f"📌 캠페인 모드: **{sel_camp_name}** — 확정된 인플루언서가 우선 표시됩니다.")

GRADE_CSS = {"S":"grade-s","A":"grade-a","B":"grade-b","C":"grade-c"}
STATUS_COLOR = {"candidate":"🟡","confirmed":"🟢","rejected":"🔴"}
STATUS_LABEL = {"candidate":"후보","confirmed":"확정","rejected":"제외"}

# ─── 카드 그리드 ──────────────────────────────────────────────────────────────
if not contents:
    st.info("조건에 맞는 인플루언서가 없습니다.")
    st.stop()

# 페이지 네비게이션 렌더링 함수
def _page_nav(suffix: str):
    c_prev, c_num, c_slash, c_total, c_next = st.columns([1, 1, 0.3, 2, 1])
    with c_prev:
        if st.button("◀ 이전", disabled=(page == 0), key=f"prev_{suffix}", use_container_width=True):
            st.session_state["browse_page"] = page - 1
            st.rerun()
    with c_num:
        jumped = st.number_input(
            "페이지", min_value=1, max_value=total_pages,
            value=page + 1, step=1,
            key=f"page_input_{suffix}",
            label_visibility="collapsed",
        )
        if jumped - 1 != page:
            st.session_state["browse_page"] = jumped - 1
            st.rerun()
    with c_slash:
        st.markdown(
            f"<div style='text-align:center;padding:8px 0;color:#888;'>/</div>",
            unsafe_allow_html=True,
        )
    with c_total:
        st.markdown(
            f"<div style='padding:8px 0;color:#666;'>"
            f"{total_pages} 페이지 &nbsp;·&nbsp; 총 <b>{len(contents):,}</b>명</div>",
            unsafe_allow_html=True,
        )
    with c_next:
        if st.button("다음 ▶", disabled=(page >= total_pages - 1), key=f"next_{suffix}", use_container_width=True):
            st.session_state["browse_page"] = page + 1
            st.rerun()

# ─── 데이터 슬라이스 (레이아웃 이전) ─────────────────────────────────────────
page_offset   = page * PAGE_SIZE
page_contents = contents[page_offset : page_offset + PAGE_SIZE]
_page_inf_ids = [r["influencer_id"] for r in page_contents]
_note_counts  = get_note_counts(_page_inf_ids, sel_brand_id)

# ─── 그리드 / 핸들(토글) / 패널 레이아웃 ────────────────────────────────────
# 핸들 컬럼이 항상 노출되어 Streamlit 사이드바처럼 여닫기 가능
if _panel_open:
    _grid_col, _handle_col, _panel_col = st.columns([6.7, 0.3, 3])
else:
    _grid_col, _handle_col = st.columns([9.7, 0.3])
    _panel_col = None

with _handle_col:
    st.markdown(
        "<style>.panel-toggle button{padding:4px 2px!important;font-size:16px;"
        "line-height:1;border-radius:6px;}</style>"
        "<div class='panel-toggle' style='padding-top:4px;'>",
        unsafe_allow_html=True,
    )
    _arrow = "‹" if _panel_open else "›"
    if st.button(_arrow, key="panel_toggle_handle", use_container_width=True,
                 help="댓글 패널 열기/닫기"):
        st.session_state["show_comment_panel"] = not _panel_open
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

with _grid_col:
    _page_nav("top")
    st.markdown("")

    for chunk_start in range(0, len(page_contents), n_cols):
        row_items = page_contents[chunk_start:chunk_start + n_cols]
        cols = st.columns(n_cols)

        global_start = page_offset + chunk_start + 1
        for col, item, rank in zip(cols, row_items, range(global_start, global_start + n_cols)):
            inf_id        = item["influencer_id"]
            thumbnail     = item.get("thumbnail_url") or item.get("cover_url") or ""
            play          = item.get("play_count") or 0
            avg_play      = item.get("avg_play_count") or 0
            er            = item["er"]
            grade         = item["grade"]
            video_url     = item.get("video_url","")
            grade_cls     = GRADE_CSS[grade]
            fav           = fav_map.get(inf_id)
            in_camp       = camp_map.get(inf_id)
            ig_url        = item.get("instagram_url") or ""
            ig_followers  = item.get("instagram_followers") or 0
            us_followers  = item.get("us_db_followers") or ""

            ig_badge = ""
            if ig_url:
                ig_label = f"📸 {_fmt(ig_followers)}" if ig_followers else "📸 Instagram"
                ig_badge = f'<a href="{ig_url}" target="_blank" class="koc-ig">{ig_label}</a>'

            platform = (item.get("platform") or "tiktok").lower()
            if "instagram" in platform:
                plat_badge = '<span class="koc-plat koc-plat-ig">Instagram</span>'
            else:
                plat_badge = '<span class="koc-plat koc-plat-tt">TikTok</span>'

            img_inner = f'<img src="{thumbnail}">' if thumbnail else '<div class="koc-placeholder">🎬</div>'
            if video_url:
                img_tag = f'<a href="{video_url}" target="_blank" style="display:block;width:100%;height:100%;">{img_inner}</a>'
            else:
                img_tag = img_inner

            with col:
                st.markdown(f"""
<div class="koc-card">
  {img_tag}
  <div class="koc-grade {grade_cls}">{grade}</div>
  <div class="koc-rank">#{rank}</div>
  <div class="koc-info">
    {plat_badge}
    <p class="koc-name">@{inf_id}</p>
    <p class="koc-stat">👁 {_fmt(avg_play)} &nbsp;·&nbsp; ER {er:.1f}%{"&nbsp;·&nbsp; 👥 " + us_followers if us_followers else ""}</p>
    {ig_badge}
  </div>
</div>
""", unsafe_allow_html=True)

                st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
                b_vid, b_note = st.columns([3, 1])
                with b_vid:
                    if st.button("🎬 전체 영상 보기", key=f"detail_{inf_id}", use_container_width=True):
                        show_influencer_videos(inf_id, sel_brand_id, user.email, sel_camp_id)
                with b_note:
                    nc = _note_counts.get(inf_id, 0)
                    if st.button(f"💬 {nc}" if nc else "💬", key=f"note_{inf_id}", use_container_width=True, help="메모/댓글"):
                        show_notes_dialog(inf_id, sel_brand_id, user.email, sel_camp_id)

                # 캠페인 모드
                if sel_camp_id:
                    if in_camp:
                        status = in_camp["status"]
                        b1, b2 = st.columns(2)
                        next_s = {"candidate":"confirmed","confirmed":"rejected","rejected":"candidate"}[status]
                        next_l = {"candidate":"✅확정","confirmed":"🔴제외","rejected":"🟡후보"}[status]
                        with b1:
                            if st.button(next_l, key=f"cn_{inf_id}", use_container_width=True):
                                update_campaign_selection(in_camp["id"], next_s); st.rerun()
                        with b2:
                            if st.button("삭제", key=f"cr_{inf_id}", use_container_width=True):
                                remove_campaign_selection(in_camp["id"]); st.rerun()
                        st.caption(f"{STATUS_COLOR[status]} {STATUS_LABEL[status]}")
                    else:
                        if st.button("＋ 캠페인 추가", key=f"ca_{inf_id}", use_container_width=True, type="primary"):
                            add_to_campaign(sel_camp_id, inf_id); st.rerun()
                # 즐겨찾기 모드
                else:
                    if fav:
                        status = fav["status"]
                        b1, b2 = st.columns(2)
                        next_s = {"candidate":"confirmed","confirmed":"rejected","rejected":"candidate"}[status]
                        next_l = {"candidate":"✅확정","confirmed":"🔴제외","rejected":"🟡후보"}[status]
                        with b1:
                            if st.button(next_l, key=f"fn_{inf_id}", use_container_width=True):
                                update_selection_status(fav["id"], next_s); st.rerun()
                        with b2:
                            if st.button("삭제", key=f"fr_{inf_id}", use_container_width=True):
                                remove_selection(fav["id"]); st.rerun()
                        st.caption(f"{STATUS_COLOR[status]} {STATUS_LABEL[status]}")
                    else:
                        if st.button("💛 즐겨찾기", key=f"fa_{inf_id}", use_container_width=True, type="primary"):
                            select_influencer(sel_brand_id, inf_id); st.rerun()

    # ─── 하단 페이지 네비게이션 ─────────────────────────────────────────────
    st.markdown("")
    _page_nav("bottom")


# ─── 어드민 전용: koc_contents 데이터 임포트 ──────────────────────────────────
if is_admin:
    st.divider()
    with st.expander("🔧 [Admin] 게시물 데이터 임포트 (Apify → koc_contents)"):
        st.markdown("""
Google Sheet 또는 CSV 파일에서 Apify TikTok 스크래퍼 데이터를 바로 업로드합니다.

**자동 인식 컬럼** (Apify 원본명 그대로 사용 가능):
`authorMeta.name` → influencer_id · `webVideoUrl` → video_url · `playCount` → play_count ·
`diggCount` → like_count · `commentCount` → comment_count · `shareCount` → share_count ·
`collectCount` → save_count · `text` → caption · `createTimeISO` → posted_at · `authorMeta.avatar` → thumbnail_url
""")

        _sheet_url = st.text_input(
            "Google Sheet URL (링크 공유된 시트)",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key="koc_import_sheet_url",
        )

        _csv_bytes = None
        if _sheet_url and "docs.google.com/spreadsheets" in _sheet_url:
            _m = re.search(r"/spreadsheets/d/([^/]+)", _sheet_url)
            _g = re.search(r"[#&?]gid=(\d+)", _sheet_url)
            if _m:
                _export_url = (
                    f"https://docs.google.com/spreadsheets/d/{_m.group(1)}"
                    f"/export?format=csv&gid={_g.group(1) if _g else '0'}"
                )
                try:
                    with st.spinner("시트 불러오는 중..."):
                        _r = requests.get(_export_url, timeout=15)
                    if _r.status_code == 200:
                        _csv_bytes = _r.content
                        st.success("시트 불러오기 완료")
                    else:
                        st.error(f"불러오기 실패 ({_r.status_code}). 시트 공유 설정 확인.")
                except Exception as _e:
                    st.error(f"네트워크 오류: {_e}")

        st.caption("또는 CSV 직접 업로드")
        _uploaded = st.file_uploader("CSV 파일", type=["csv"], key="koc_import_csv")
        if _uploaded:
            _csv_bytes = _uploaded.getvalue()

        if _csv_bytes:
            try:
                _df = pd.read_csv(io.StringIO(_csv_bytes.decode("utf-8-sig")))
                _df.columns = [c.strip().lower().replace(".", "_") for c in _df.columns]

                def _fc(candidates):
                    return next((c for c in _df.columns if any(k in c for k in candidates)), None)

                _id_col    = _fc(["authormeta_name", "author_name", "influencer_id", "username"])
                _url_col   = _fc(["webvideourl", "video_url", "videourl"])
                _play_col  = _fc(["playcount", "play_count"])
                _like_col  = _fc(["diggcount", "likecount", "like_count"])
                _cmt_col   = _fc(["commentcount", "comment_count"])
                _shr_col   = _fc(["sharecount", "share_count"])
                _save_col  = _fc(["collectcount", "save_count"])
                _cap_col   = _fc(["text", "caption"])
                _date_col  = _fc(["createtimeiso", "createtime", "posted_at"])
                _thumb_col = _fc(["thumbnail_url", "authormeta_avatar", "avatar", "cover"])

                st.caption(f"인식된 컬럼: influencer_id={_id_col}, video_url={_url_col}, play={_play_col}, like={_like_col}")

                if not _id_col or not _url_col:
                    st.error("influencer_id 또는 video_url 컬럼을 찾을 수 없습니다. 컬럼명을 확인하세요.")
                else:
                    def _int(val):
                        try: return int(float(str(val).replace(",", "")))
                        except: return None

                    def _clean(val):
                        s = str(val).strip() if val is not None else ""
                        return None if s.lower() in ("nan", "none", "") else s

                    rows = []
                    for _, row in _df.iterrows():
                        iid = _clean(row.get(_id_col))
                        vurl = _clean(row.get(_url_col))
                        if not iid or not vurl:
                            continue
                        rows.append({
                            "influencer_id": iid,
                            "video_url":     vurl,
                            "play_count":    _int(row[_play_col])  if _play_col  else None,
                            "like_count":    _int(row[_like_col])  if _like_col  else None,
                            "comment_count": _int(row[_cmt_col])   if _cmt_col   else None,
                            "share_count":   _int(row[_shr_col])   if _shr_col   else None,
                            "save_count":    _int(row[_save_col])  if _save_col  else None,
                            "caption":       (_clean(row[_cap_col]) or "")[:500] if _cap_col else None,
                            "posted_at":     _clean(row[_date_col]) if _date_col else None,
                            "thumbnail_url": _clean(row[_thumb_col]) if _thumb_col else None,
                        })

                    st.markdown(f"**미리보기** — {len(rows)}행")
                    st.dataframe(
                        pd.DataFrame(rows)[["influencer_id", "video_url", "play_count", "like_count"]].head(10),
                        use_container_width=True, hide_index=True,
                    )

                    if rows and st.button(f"✅ {len(rows)}행 koc_contents에 업로드", type="primary", key="koc_import_run"):
                        with st.spinner("업로드 중..."):
                            _cnt, _errs = bulk_upsert_koc_contents(rows)
                        st.success(f"완료: {_cnt}행 업로드")
                        if _errs:
                            with st.expander(f"오류 {len(_errs)}건"):
                                for e in _errs: st.warning(e)

            except Exception as _ex:
                st.error(f"파싱 오류: {_ex}")

# ─── 댓글 패널 ────────────────────────────────────────────────────────────────
if _panel_open and _panel_col:
    with _panel_col:
        _render_comment_panel(sel_brand_id, user.email, sel_camp_id)
