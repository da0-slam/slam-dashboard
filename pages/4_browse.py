import streamlit as st
from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    get_brands, get_brand_by_id, get_campaigns,
    get_browse_contents, get_influencer_contents,
    get_brand_selection_map, get_campaign_selection_map,
    select_influencer, update_selection_status, remove_selection,
    add_to_campaign, update_campaign_selection, remove_campaign_selection,
    get_user_profile,
)

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
.grade-s{background:#FF6B2C;} .grade-a{background:#3B82F6;}
.grade-b{background:#6B7280;} .grade-c{background:#374151;}
div[data-testid="stHorizontalBlock"] > div {padding: 0 4px;}
</style>
""", unsafe_allow_html=True)

# ─── 사용자 프로필 및 브랜드 확인 ────────────────────────────────────────────
profile       = get_user_profile(user.id)
user_brand_id = profile.get("brand_id")
user_role     = profile.get("role", "brand_user")
is_admin      = user_role == "admin"

if not user_brand_id and not is_admin:
    st.error("브랜드 계정이 연결되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

# ─── 헤더 ─────────────────────────────────────────────────────────────────────
col_logo, col_brand, col_camp = st.columns([3, 2, 2])
with col_logo:
    st.markdown("### 🎯 BRANDSLAM · KOC Intelligence Viewer")

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

for r in all_contents:
    r["er"]    = calc_er(r)
    r["grade"] = calc_grade(r["er"])

# 업로드 연도 파싱
for r in all_contents:
    pt = r.get("posted_at") or ""
    r["year"] = pt[:4] if pt else "?"

# ─── 필터 바 ──────────────────────────────────────────────────────────────────
fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([3, 2, 2, 1.5, 1.5, 1])

with fc1:
    grade_filter = st.multiselect(
        "Grade", ["S","A","B","C"], default=["S","A","B"],
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
    if st.button("↺", help="썸네일 업데이트 반영 등 최신 데이터로 새로고침", use_container_width=True):
        get_browse_contents.clear()
        st.rerun()

caption_search = st.text_input(
    "캡션 검색",
    placeholder="캡션 내용으로 검색 (예: 스킨케어, 다이어트, 추천...)",
    label_visibility="collapsed",
)

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

if sort_by == "ER %":
    contents.sort(key=lambda r: r["er"], reverse=True)
elif sort_by == "Date (최신순)":
    contents.sort(key=lambda r: r.get("posted_at") or "", reverse=True)
elif sort_by == "Date (오래된순)":
    contents.sort(key=lambda r: r.get("posted_at") or "")

# ─── 페이지네이션 상태 ────────────────────────────────────────────────────────
PAGE_SIZE = 48  # 4열×12행 or 3열×16행

_filter_sig = (tuple(grade_filter), year_filter, search_kw, caption_search, sort_by, sel_camp_id)
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
def show_influencer_videos(inf_id: str):
    videos = get_influencer_contents(inf_id)
    if not videos:
        st.info("영상 데이터가 없습니다.")
        return

    total_plays = sum(v.get("play_count") or 0 for v in videos)
    avg_er_val  = sum(
        (sum(v.get(k) or 0 for k in ("like_count","comment_count","share_count","save_count"))
         / (v.get("play_count") or 1) * 100)
        for v in videos
    ) / len(videos)

    st.markdown(f"### @{inf_id}")
    m1, m2, m3 = st.columns(3)
    m1.metric("총 영상 수", len(videos))
    m2.metric("총 조회수",  _fmt(total_plays))
    m3.metric("평균 ER",   f"{avg_er_val:.1f}%")
    st.divider()

    COLS = 3
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
                    st.markdown(f'<a href="{video_url}" target="_blank"><img src="{thumbnail}" style="width:100%;border-radius:8px;"></a>', unsafe_allow_html=True)
                elif thumbnail:
                    st.image(thumbnail, use_container_width=True)
                else:
                    st.markdown('<div style="background:#1a1a2e;aspect-ratio:9/16;display:flex;align-items:center;justify-content:center;font-size:2rem;border-radius:8px;">🎬</div>', unsafe_allow_html=True)
                st.caption(f"👁 {_fmt(play)}  ·  ER {er:.1f}%  ·  {posted}")
                if caption:
                    st.caption(caption[:60] + ("…" if len(caption) > 60 else ""))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Showing",     len(contents))
m2.metric("S Grade",     s_cnt)
m3.metric("Avg ER",      f"{avg_er:.1f}%")
m4.metric("Total Views", _fmt(total_views))

st.divider()

# ─── 선택 상태 로드 ────────────────────────────────────────────────────────────
fav_map  = get_brand_selection_map(sel_brand_id)
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
    c_prev, c_info, c_next = st.columns([1, 4, 1])
    with c_prev:
        if st.button("◀ 이전", disabled=(page == 0), key=f"prev_{suffix}", use_container_width=True):
            st.session_state["browse_page"] = page - 1
            st.rerun()
    with c_info:
        st.markdown(
            f"<div style='text-align:center;padding:6px 0;color:#666;'>"
            f"<b>{page+1}</b> / {total_pages} 페이지 &nbsp;·&nbsp; 총 <b>{len(contents):,}</b>명"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c_next:
        if st.button("다음 ▶", disabled=(page >= total_pages - 1), key=f"next_{suffix}", use_container_width=True):
            st.session_state["browse_page"] = page + 1
            st.rerun()

_page_nav("top")
st.markdown("")

# 현재 페이지 항목만 슬라이스
page_offset   = page * PAGE_SIZE
page_contents = contents[page_offset : page_offset + PAGE_SIZE]

for chunk_start in range(0, len(page_contents), n_cols):
    row_items = page_contents[chunk_start:chunk_start + n_cols]
    cols = st.columns(n_cols)

    global_start = page_offset + chunk_start + 1
    for col, item, rank in zip(cols, row_items, range(global_start, global_start + n_cols)):
        inf_id    = item["influencer_id"]
        thumbnail = item.get("thumbnail_url") or item.get("cover_url") or ""
        play      = item.get("play_count") or 0
        er        = item["er"]
        grade     = item["grade"]
        video_url = item.get("video_url","")
        grade_cls = GRADE_CSS[grade]
        fav       = fav_map.get(inf_id)
        in_camp   = camp_map.get(inf_id)

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
    <p class="koc-name">@{inf_id}</p>
    <p class="koc-stat">👁 {_fmt(play)} &nbsp;·&nbsp; ER {er:.1f}%</p>
  </div>
</div>
""", unsafe_allow_html=True)

            if st.button("🎬 전체 영상 보기", key=f"detail_{inf_id}", use_container_width=True):
                show_influencer_videos(inf_id)

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

# ─── 하단 페이지 네비게이션 ───────────────────────────────────────────────────
st.markdown("")
_page_nav("bottom")
