import io
from datetime import date

import pandas as pd
import streamlit as st

from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    create_campaign_post,
    delete_campaign_post,
    get_brands,
    get_campaign_participants_info,
    get_campaign_post_by_id,
    get_campaign_posts,
    get_campaigns,
    get_user_profile,
    migrate_google_sheet_rows,
    post_url_exists,
    update_campaign_post,
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

is_admin = profile.role == "admin"
brand_id: str | None = profile.brand_id

if is_admin:
    brands = get_brands()
    if not brands:
        st.warning("등록된 브랜드가 없습니다.")
        st.stop()
    brand_map = {b["name"]: b["id"] for b in brands}
    sel_brand_name = st.sidebar.selectbox("브랜드 (관리자)", list(brand_map.keys()), key="cp_brand_sel")
    brand_id = brand_map[sel_brand_name]
    if "cp_prev_brand" not in st.session_state:
        st.session_state.cp_prev_brand = brand_id
    if st.session_state.cp_prev_brand != brand_id:
        st.session_state.cp_prev_brand = brand_id
        st.session_state.pop("cp_editing_post", None)

if not brand_id:
    st.warning("브랜드가 연결되지 않은 계정입니다. 관리자에게 문의하세요.")
    st.stop()

campaigns = get_campaigns(brand_id)
campaign_map: dict[str, str] = {c["id"]: c["name"] for c in campaigns}
campaign_name_to_id: dict[str, str] = {c["name"]: c["id"] for c in campaigns}

# ── 사이드바 필터 ─────────────────────────────────────────────────────────────

st.sidebar.header("필터")

camp_choices = {"전체 캠페인": None}
camp_choices.update({c["name"]: c["id"] for c in campaigns})
sel_camp_label = st.sidebar.selectbox("캠페인", list(camp_choices.keys()), key="cp_camp")
filter_campaign_id: str | None = camp_choices[sel_camp_label]

platform_choice = st.sidebar.selectbox("플랫폼", ["전체", "Instagram", "TikTok"], key="cp_plat")
filter_platform = {"전체": None, "Instagram": "instagram", "TikTok": "tiktok"}[platform_choice]

st.sidebar.markdown("**업로드 기간**")
sc1, sc2 = st.sidebar.columns(2)
filter_start: date | None = sc1.date_input("시작일", value=None, key="cp_start")
filter_end: date | None   = sc2.date_input("종료일",  value=None, key="cp_end")

filter_name = st.sidebar.text_input("인플루언서명 검색", key="cp_name")
filter_url  = st.sidebar.text_input("URL 검색",         key="cp_url")

sort_options = {
    "업로드일":  "upload_date",
    "조회수":    "views",
    "참여율":    "engagement_rate",
    "저장 수":   "saves",
    "댓글 수":   "comments",
    "좋아요":    "likes",
}
sort_label = st.sidebar.selectbox("정렬 기준", list(sort_options.keys()), key="cp_sort")
sort_by = sort_options[sort_label]

# ── 데이터 로드 ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load(brand_id, campaign_id, platform, s_date, e_date, name, url, col):
    db_col = col if col != "engagement_rate" else "views"
    return get_campaign_posts(
        brand_id=brand_id,
        campaign_id=campaign_id,
        platform=platform,
        start_date=str(s_date) if s_date else None,
        end_date=str(e_date) if e_date else None,
        search_name=name or None,
        search_url=url or None,
        sort_by=db_col,
    )


raw = _load(brand_id, filter_campaign_id, filter_platform,
            filter_start, filter_end, filter_name, filter_url, sort_by)


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
if sel_camp_label != "전체 캠페인":
    st.caption(f"캠페인: {sel_camp_label}  ·  플랫폼: {platform_choice}")

# ── 탭 ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📈 성과 대시보드",
    "👥 인플루언서 요약",
    "⭐ 우수 콘텐츠",
    "➕ 게시물 관리",
])

# ═══════════════════════════════════════════════════════════════
# Tab 1 – 성과 대시보드
# ═══════════════════════════════════════════════════════════════

with tab1:
    if df.empty:
        st.info("게시물 데이터가 없습니다. '게시물 관리' 탭에서 게시물을 추가해주세요.")
    else:
        # KPI 계산
        total_influencers = df["influencer_name"].nunique()
        total_posts       = len(df)
        ig_posts          = int((df["platform"] == "instagram").sum())
        tt_posts          = int((df["platform"] == "tiktok").sum())
        total_views       = int(df["views"].sum())
        total_likes       = int(df["likes"].sum())
        total_comments    = int(df["comments"].sum())
        total_saves       = int(df["saves"].sum())
        total_shares      = int(df["shares"].sum())
        avg_er            = round(float(df["engagement_rate"].mean()), 2)

        # KPI 카드 (5 + 5)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("참여 인플루언서", f"{total_influencers:,}")
        c2.metric("총 게시물",       f"{total_posts:,}")
        c3.metric("Instagram",      f"{ig_posts:,}")
        c4.metric("TikTok",         f"{tt_posts:,}")
        c5.metric("평균 참여율",    f"{avg_er:.1f}%")

        c6, c7, c8, c9, c10 = st.columns(5)
        c6.metric("총 조회수",  f"{total_views:,}")
        c7.metric("총 좋아요",  f"{total_likes:,}")
        c8.metric("총 댓글",    f"{total_comments:,}")
        c9.metric("총 저장",    f"{total_saves:,}")
        c10.metric("총 공유",   f"{total_shares:,}")

        st.divider()

        # 게시물 목록 테이블
        st.subheader("게시물 목록")

        disp = df.copy()
        disp["플랫폼"] = disp["platform"].map({"instagram": "Instagram", "tiktok": "TikTok"})

        show_cols = ["influencer_name", "플랫폼", "post_url", "upload_date",
                     "views", "likes", "comments", "saves", "shares",
                     "engagement_rate", "last_tracked_at"]
        if sel_camp_label == "전체 캠페인":
            disp["캠페인"] = disp["campaign_id"].map(campaign_map).fillna("–")
            show_cols = ["influencer_name", "캠페인"] + show_cols[1:]

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
        }
        disp = disp[show_cols].rename(columns=rename)

        st.dataframe(
            disp,
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

        col_config = {
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
                ok = update_campaign_post(ep["id"], brand_id, {
                    "influencer_name": e_name.strip(),
                    "platform":        e_plat,
                    "post_url":        e_url.strip(),
                    "upload_date":     str(e_date) if e_date else None,
                    "views":           e_views,
                    "likes":           e_likes,
                    "comments":        e_comments,
                    "saves":           e_saves,
                    "shares":          e_shares,
                })
                if ok:
                    st.success("수정되었습니다.")
                    st.session_state.cp_editing_post = None
                    _load.clear()
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
            participants = get_campaign_participants_info(form_campaign_id, brand_id)
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
                    st.success(f"게시물이 추가되었습니다. ({form_platform.upper()} · {form_name})")
                    _load.clear()
                    st.rerun()
                else:
                    st.error("게시물 추가에 실패했습니다.")

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
                        _load.clear()
                        st.rerun()
                else:
                    if mg3.button("🗑️", key=f"del_{pid}", use_container_width=True):
                        st.session_state[del_key] = True
                        st.rerun()

    # ── Google Sheet 데이터 이관 ──────────────────────────────────────────────

    with st.expander("📥 Google Sheet 데이터 이관", expanded=False):
        st.markdown("""
**CSV 형식 안내**

아래 컬럼 순서로 CSV 파일을 업로드하세요. 헤더 행이 반드시 포함되어야 합니다.

| name | ig_url | tt_url | upload_day | views | likes | comments | saves | shares |
|------|--------|--------|------------|-------|-------|----------|-------|--------|
| Adriana | https://instagram.com/... | https://tiktok.com/... | 2026/05/10 | 5000 | 300 | 40 | 80 | 20 |

**성과 지표 매핑 규칙**
- TikTok URL이 있으면 → TikTok 게시물에 지표 적용, Instagram 게시물은 0
- TikTok URL만 있으면 → TikTok 게시물에 지표 적용
- Instagram URL만 있으면 → Instagram 게시물에 지표 적용
- ig_url, tt_url 모두 비어 있으면 건너뜁니다.
""")

        mi_camp_label = st.selectbox(
            "이관 대상 캠페인 *",
            [c["name"] for c in campaigns],
            key="mi_camp",
        )
        mi_campaign_id = campaign_name_to_id[mi_camp_label]

        uploaded = st.file_uploader("CSV 파일 업로드", type=["csv"], key="mi_csv")

        if uploaded:
            try:
                raw_csv = pd.read_csv(io.StringIO(uploaded.getvalue().decode("utf-8-sig")))
                raw_csv.columns = [c.strip().lower() for c in raw_csv.columns]

                # 컬럼 매핑 (다양한 표기 허용)
                col_aliases = {
                    "name":       ["name", "인플루언서", "influencer", "influencer_name"],
                    "ig_url":     ["ig_url", "posting url (ig)", "ig url", "instagram_url", "instagram url"],
                    "tt_url":     ["tt_url", "posting url (tt)", "tt url", "tiktok_url",    "tiktok url"],
                    "upload_day": ["upload_day", "upload day", "uploadday", "날짜", "date"],
                    "views":      ["views", "view", "조회수", "재생수"],
                    "likes":      ["likes", "like", "좋아요"],
                    "comments":   ["comments", "comment", "댓글"],
                    "saves":      ["saves", "save", "저장"],
                    "shares":     ["shares", "share", "공유"],
                }

                def _find_col(aliases: list[str]) -> str | None:
                    for a in aliases:
                        if a in raw_csv.columns:
                            return a
                    return None

                mapped = {}
                for field, aliases in col_aliases.items():
                    c = _find_col(aliases)
                    mapped[field] = c

                missing = [k for k, v in mapped.items() if v is None and k in ("name",)]
                if missing:
                    st.error(f"필수 컬럼 누락: {missing}. CSV 헤더를 확인해주세요.")
                else:
                    rows_to_migrate = []
                    for _, r in raw_csv.iterrows():
                        rows_to_migrate.append({
                            "name":       str(r[mapped["name"]]) if mapped["name"] else "",
                            "ig_url":     str(r[mapped["ig_url"]]) if mapped["ig_url"] else "",
                            "tt_url":     str(r[mapped["tt_url"]]) if mapped["tt_url"] else "",
                            "upload_day": str(r[mapped["upload_day"]]) if mapped["upload_day"] else "",
                            "views":      r[mapped["views"]]    if mapped["views"]    else 0,
                            "likes":      r[mapped["likes"]]    if mapped["likes"]    else 0,
                            "comments":   r[mapped["comments"]] if mapped["comments"] else 0,
                            "saves":      r[mapped["saves"]]    if mapped["saves"]    else 0,
                            "shares":     r[mapped["shares"]]   if mapped["shares"]   else 0,
                        })

                    st.markdown(f"**미리보기** ({len(rows_to_migrate)}행)")
                    preview_df = pd.DataFrame(rows_to_migrate).head(5)
                    st.dataframe(preview_df, use_container_width=True, hide_index=True)

                    if st.button(f"✅ {len(rows_to_migrate)}개 행 이관 시작", key="mi_run"):
                        with st.spinner("이관 중..."):
                            created, errors = migrate_google_sheet_rows(
                                mi_campaign_id, brand_id, rows_to_migrate
                            )
                        st.success(f"이관 완료: {created}개 게시물 생성")
                        if errors:
                            with st.expander(f"경고 / 건너뜀 ({len(errors)}건)"):
                                for e in errors:
                                    st.warning(e)
                        _load.clear()
                        st.rerun()

            except Exception as ex:
                st.error(f"CSV 파싱 오류: {ex}")
