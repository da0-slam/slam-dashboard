import streamlit as st
from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    get_brands, get_influencers,
    get_campaigns, create_campaign, update_campaign, delete_campaign,
    get_campaign_selections, update_campaign_selection, remove_campaign_selection,
    get_influencer_thumbnails,
)

st.set_page_config(page_title="캠페인 관리", page_icon="📋", layout="wide")
require_auth()
sidebar_user_info()

st.title("📋 캠페인 관리")

brands = get_brands()
if not brands:
    st.warning("먼저 브랜드사를 등록하세요.")
    st.stop()

brand_options     = {b["name"]: b["id"] for b in brands}
selected_brand_name = st.selectbox("브랜드사", list(brand_options.keys()))
selected_brand_id   = brand_options[selected_brand_name]

st.divider()

STATUS_COLOR = {"candidate": "🟡", "confirmed": "🟢", "rejected": "🔴"}
STATUS_LABEL = {"candidate": "후보",  "confirmed": "확정",  "rejected": "제외"}
CAMP_STATUS  = {"draft": "⚫ 준비중", "active": "🟢 진행중", "closed": "⚪ 종료"}
GRADE_CSS    = {"S": "grade-s", "A": "grade-a", "B": "grade-b", "C": "grade-c"}

st.markdown("""
<style>
.koc-mini{position:relative;border-radius:10px;overflow:hidden;background:#111;aspect-ratio:9/16;}
.koc-mini img{width:100%;height:100%;object-fit:cover;display:block;}
.koc-mini-ph{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
             font-size:2rem;background:#1a1a2e;}
.koc-mini .g{position:absolute;top:6px;left:6px;border-radius:5px;padding:2px 7px;
             color:#fff;font-weight:700;font-size:12px;}
.koc-mini .r{position:absolute;top:6px;right:6px;background:rgba(0,0,0,.65);
             border-radius:5px;padding:2px 7px;color:#fff;font-size:11px;}
.koc-mini .info{position:absolute;bottom:0;left:0;right:0;
                background:linear-gradient(transparent,rgba(0,0,0,.8));padding:14px 8px 8px;}
.koc-mini .n{color:#fff;font-weight:700;font-size:12px;margin:0;}
.koc-mini .s{color:rgba(255,255,255,.8);font-size:10px;margin:2px 0 0;}
.grade-s{background:#FF6B2C;} .grade-a{background:#3B82F6;}
.grade-b{background:#6B7280;} .grade-c{background:#374151;}
</style>
""", unsafe_allow_html=True)


def calc_er(play, likes, comments, shares, saves):
    play = play or 0
    if play == 0: return 0.0
    return ((likes or 0) + (comments or 0) + (shares or 0) + (saves or 0)) / play * 100

def calc_grade(er):
    if er >= 10: return "S"
    if er >= 5:  return "A"
    if er >= 2:  return "B"
    return "C"

def _fmt(n):
    n = n or 0
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(n)


# ─── 캠페인 상세 뷰 ───────────────────────────────────────────────────────────
if st.session_state.get("selected_campaign"):
    camp = st.session_state.selected_campaign

    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← 목록"):
            st.session_state.selected_campaign = None
            st.rerun()
    with col_title:
        st.subheader(f"📌 {camp['name']}  {CAMP_STATUS.get(camp['status'], '')}")

    with st.expander("⚙️ 캠페인 설정"):
        c1, c2 = st.columns(2)
        with c1:
            new_status = st.selectbox("상태", ["draft","active","closed"],
                index=["draft","active","closed"].index(camp["status"]),
                format_func=lambda x: CAMP_STATUS[x])
        with c2:
            new_name = st.text_input("캠페인명", value=camp["name"])
        if st.button("저장", type="primary"):
            update_campaign(camp["id"], {"name": new_name, "status": new_status})
            st.session_state.selected_campaign.update({"name": new_name, "status": new_status})
            st.success("저장했습니다.")
            st.rerun()

    st.divider()

    selections = get_campaign_selections(camp["id"])
    inf_ids    = [s["influencer_id"] for s in selections]
    thumb_map  = get_influencer_thumbnails(inf_ids)
    inf_map    = {r["influencer_id"]: r for r in get_influencers()}

    # 뷰 토글
    view_col, _ = st.columns([2, 6])
    with view_col:
        view_mode = st.radio("보기", ["🔲 그리드", "📋 목록"], horizontal=True, label_visibility="collapsed")

    tab_all, tab_cand, tab_conf, tab_rej = st.tabs([
        f"전체 {len(selections)}",
        f"🟡 후보 {sum(1 for s in selections if s['status']=='candidate')}",
        f"🟢 확정 {sum(1 for s in selections if s['status']=='confirmed')}",
        f"🔴 제외 {sum(1 for s in selections if s['status']=='rejected')}",
    ])

    def render_selections(items, prefix):
        if not items:
            st.info("해당 항목이 없습니다.")
            return

        if "그리드" in view_mode:
            # ── 그리드 뷰 (4열) ────────────────────────────────────────────
            COLS = 4
            for chunk_start in range(0, len(items), COLS):
                row = items[chunk_start:chunk_start+COLS]
                cols = st.columns(COLS)
                for col, item, rank in zip(cols, row, range(chunk_start+1, chunk_start+COLS+1)):
                    inf_id  = item["influencer_id"]
                    status  = item["status"]
                    inf     = inf_map.get(inf_id, {})
                    thumb   = thumb_map.get(inf_id, {})
                    thumbnail = thumb.get("thumbnail", "")
                    video_url = thumb.get("video_url", "")
                    img_tag = f'<img src="{thumbnail}">' if thumbnail else '<div class="koc-mini-ph">🎬</div>'
                    g_cls   = GRADE_CSS.get("B", "grade-b")

                    with col:
                        st.markdown(f"""
<div class="koc-mini">
  {img_tag}
  <div class="g {g_cls}">{STATUS_COLOR[status]}</div>
  <div class="r">#{rank}</div>
  <div class="info">
    <p class="n">@{inf_id}</p>
    <p class="s">{inf.get('platform','')} · {STATUS_LABEL[status]}</p>
  </div>
</div>
""", unsafe_allow_html=True)
                        if video_url:
                            st.markdown(f"[↗ 영상]({video_url})")
                        if item.get("note"):
                            st.caption(f"📝 {item['note']}")
                        b1, b2 = st.columns(2)
                        next_s = {"candidate":"confirmed","confirmed":"rejected","rejected":"candidate"}[status]
                        next_l = {"candidate":"✅확정","confirmed":"🔴제외","rejected":"🟡후보"}[status]
                        with b1:
                            if st.button(next_l, key=f"{prefix}_g_ns_{item['id']}", use_container_width=True):
                                update_campaign_selection(item["id"], next_s); st.rerun()
                        with b2:
                            if st.button("삭제", key=f"{prefix}_g_rm_{item['id']}", use_container_width=True):
                                remove_campaign_selection(item["id"]); st.rerun()
        else:
            # ── 목록 뷰 ───────────────────────────────────────────────────
            for item in items:
                inf_id    = item["influencer_id"]
                status    = item["status"]
                inf       = inf_map.get(inf_id, {})
                thumb     = thumb_map.get(inf_id, {})
                thumbnail = thumb.get("thumbnail", "")
                video_url = thumb.get("video_url", "")

                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([1, 4, 2, 1])
                    with c1:
                        if thumbnail:
                            try: st.image(thumbnail, width=60)
                            except: st.markdown("🎬")
                        else:
                            st.markdown("🎬")
                    with c2:
                        st.markdown(f"{STATUS_COLOR[status]} **@{inf_id}** `{STATUS_LABEL[status]}`")
                        st.caption(f"{inf.get('platform','')}  {f'[↗ 영상]({video_url})' if video_url else ''}")
                        if item.get("note"):
                            st.caption(f"📝 {item['note']}")
                    with c3:
                        next_s = {"candidate":"confirmed","confirmed":"rejected","rejected":"candidate"}[status]
                        next_l = {"candidate":"✅ 확정","confirmed":"🔴 제외","rejected":"🟡 후보로"}[status]
                        if st.button(next_l, key=f"{prefix}_l_ns_{item['id']}", use_container_width=True):
                            update_campaign_selection(item["id"], next_s); st.rerun()
                    with c4:
                        if st.button("삭제", key=f"{prefix}_l_rm_{item['id']}", use_container_width=True):
                            remove_campaign_selection(item["id"]); st.rerun()

    with tab_all:  render_selections(selections, "all")
    with tab_cand: render_selections([s for s in selections if s["status"]=="candidate"], "cand")
    with tab_conf: render_selections([s for s in selections if s["status"]=="confirmed"], "conf")
    with tab_rej:  render_selections([s for s in selections if s["status"]=="rejected"],  "rej")

# ─── 캠페인 목록 ──────────────────────────────────────────────────────────────
else:
    campaigns = get_campaigns(selected_brand_id)

    col_hd, col_btn = st.columns([6, 2])
    with col_hd:
        st.subheader(f"{selected_brand_name}의 캠페인")
    with col_btn:
        if st.button("＋ 새 캠페인", use_container_width=True, type="primary"):
            st.session_state.show_create = True

    if st.session_state.get("show_create"):
        with st.form("create_campaign_form"):
            camp_name = st.text_input("캠페인명 *", placeholder="예: 23yo Concealer Q3 2025")
            camp_desc = st.text_area("설명", height=80)
            c1, c2 = st.columns(2)
            with c1:
                if st.form_submit_button("생성", type="primary", use_container_width=True):
                    if not camp_name:
                        st.error("캠페인명을 입력하세요.")
                    else:
                        create_campaign(selected_brand_id, camp_name, camp_desc)
                        st.session_state.show_create = False
                        st.rerun()
            with c2:
                if st.form_submit_button("취소", use_container_width=True):
                    st.session_state.show_create = False
                    st.rerun()

    st.divider()

    if not campaigns:
        st.info("아직 캠페인이 없습니다. 새 캠페인을 만들어보세요.")
    else:
        cols = st.columns(3)
        for i, camp in enumerate(campaigns):
            with cols[i % 3]:
                sels     = get_campaign_selections(camp["id"])
                cnt_all  = len(sels)
                cnt_conf = sum(1 for s in sels if s["status"] == "confirmed")
                with st.container(border=True):
                    st.markdown(f"### {camp['name']}")
                    st.caption(CAMP_STATUS.get(camp["status"], camp["status"]))
                    ca, cb = st.columns(2)
                    ca.metric("전체", cnt_all)
                    cb.metric("확정", cnt_conf)
                    if camp.get("description"):
                        st.caption(camp["description"])
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("관리하기 →", key=f"open_{camp['id']}", use_container_width=True, type="primary"):
                            st.session_state.selected_campaign = camp
                            st.rerun()
                    with b2:
                        if st.button("삭제", key=f"del_{camp['id']}", use_container_width=True):
                            st.session_state[f"confirm_del_{camp['id']}"] = True
                    if st.session_state.get(f"confirm_del_{camp['id']}"):
                        st.warning(f"**'{camp['name']}'** 삭제하시겠습니까?")
                        y, n = st.columns(2)
                        with y:
                            if st.button("삭제 확인", key=f"yes_{camp['id']}", type="primary"):
                                delete_campaign(camp["id"])
                                st.session_state.pop(f"confirm_del_{camp['id']}", None)
                                st.rerun()
                        with n:
                            if st.button("취소", key=f"no_{camp['id']}"):
                                st.session_state.pop(f"confirm_del_{camp['id']}", None)
                                st.rerun()
