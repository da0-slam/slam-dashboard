import streamlit as st
from utils.auth import require_auth, sidebar_user_info, block_if_demo
from utils.supabase_client import (
    get_brands,
    get_brand_selections,
    get_influencers,
    select_influencer,
    update_selection_status,
    remove_selection,
)

st.set_page_config(page_title="인플루언서 선택 관리", page_icon="👥", layout="wide")

require_auth()
block_if_demo()
sidebar_user_info()

st.title("👥 인플루언서 선택 관리")

brands = get_brands()
if not brands:
    st.warning("먼저 브랜드사를 등록하세요.")
    st.page_link("pages/1_brands.py", label="브랜드사 관리로 이동 →")
    st.stop()

brand_options = {b["name"]: b["id"] for b in brands}
selected_brand_name = st.selectbox("브랜드사 선택", options=list(brand_options.keys()))
selected_brand_id = brand_options[selected_brand_name]

STATUS_LABEL = {"candidate": "후보", "confirmed": "확정", "rejected": "제외"}
STATUS_COLOR = {"candidate": "🟡", "confirmed": "🟢", "rejected": "🔴"}


def _clean_name(inf_id: str) -> str:
    """* 마크다운 기호 제거 후 공백 trim."""
    return inf_id.replace("*", "").strip()


st.divider()
col_selected, col_search = st.columns(2)

# ─── 선택된 인플루언서 ────────────────────────────────────────────────────────
with col_selected:
    st.subheader("🎯 선택된 인플루언서")

    tab_all, tab_candidate, tab_confirmed, tab_rejected = st.tabs(
        ["전체", "후보", "확정", "제외"]
    )

    selections = get_brand_selections(selected_brand_id)
    selected_ids = {s["influencer_id"] for s in selections}

    def render_selections(items: list, prefix: str):
        if not items:
            st.info("해당 항목이 없습니다.")
            return
        st.caption(f"총 {len(items)}명")
        for item in items:
            inf     = item.get("influencer_master") or {}
            inf_id  = inf.get("influencer_id") or item.get("influencer_id", "")
            name    = _clean_name(inf_id)
            status  = item.get("status", "candidate")
            url     = inf.get("account_url") or ""
            platform = inf.get("platform", "")

            cover_url = inf.get("cover_url") or ""
            with st.container(border=True):
                c0, c1, c2, c3 = st.columns([1, 4, 2, 1])
                with c0:
                    if cover_url:
                        st.image(cover_url, width=50)
                with c1:
                    name_md = f"[{name}]({url})" if url and name else (name or inf_id)
                    st.markdown(
                        f"{STATUS_COLOR[status]} {name_md}  "
                        f"`{STATUS_LABEL[status]}`"
                    )
                    st.caption(platform)
                    if item.get("note"):
                        st.caption(f"📝 {item['note']}")
                with c2:
                    next_status = {
                        "candidate": "confirmed",
                        "confirmed": "rejected",
                        "rejected": "candidate",
                    }[status]
                    next_label = {
                        "candidate": "✅ 확정",
                        "confirmed": "🔴 제외",
                        "rejected":  "🟡 후보로",
                    }[status]
                    st.write("")
                    if st.button(next_label, key=f"{prefix}_status_{item['id']}", use_container_width=True):
                        update_selection_status(item["id"], next_status)
                        st.rerun()
                with c3:
                    st.write("")
                    if st.button("삭제", key=f"{prefix}_remove_{item['id']}", use_container_width=True):
                        remove_selection(item["id"])
                        st.rerun()

    with tab_all:
        render_selections(selections, "all")
    with tab_candidate:
        render_selections([s for s in selections if s["status"] == "candidate"], "cand")
    with tab_confirmed:
        render_selections([s for s in selections if s["status"] == "confirmed"], "conf")
    with tab_rejected:
        render_selections([s for s in selections if s["status"] == "rejected"], "rej")

# ─── 인플루언서 검색 및 선택 ──────────────────────────────────────────────────
with col_search:
    st.subheader("🔍 인플루언서 검색")
    search_term = st.text_input("인플루언서 ID 검색", placeholder="username 입력")

    if search_term:
        influencers = get_influencers(search_term.lstrip("@"), limit=200)
    else:
        influencers = get_influencers(limit=50)

    # *만으로 이루어진 결측 데이터 필터링
    influencers = [i for i in influencers if _clean_name(i["influencer_id"])]

    if influencers:
        st.caption(f"검색 결과 {len(influencers)}명")
        for inf in influencers:
            inf_id   = inf["influencer_id"]
            name     = _clean_name(inf_id)
            url      = inf.get("account_url") or ""
            platform = inf.get("platform", "")
            selected = inf_id in selected_ids

            cover_url = inf.get("cover_url") or ""
            with st.container(border=True):
                c0, c1, c2 = st.columns([1, 4, 1])
                with c0:
                    if cover_url:
                        st.image(cover_url, width=50)
                with c1:
                    name_md = f"[{name}]({url})" if url else name
                    st.markdown(name_md)
                    st.caption(platform)
                with c2:
                    if selected:
                        st.caption("선택됨")
                    else:
                        if st.button(
                            "선택", key=f"select_{inf_id}",
                            use_container_width=True, type="primary"
                        ):
                            select_influencer(selected_brand_id, inf_id)
                            st.rerun()
    elif search_term:
        st.info("검색 결과가 없습니다.")
