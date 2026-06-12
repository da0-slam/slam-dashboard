import streamlit as st


def require_auth():
    if not st.session_state.get("user"):
        from utils.session import restore_session
        restore_session()
    if not st.session_state.get("user"):
        st.warning("로그인이 필요합니다.")
        st.stop()
    # 페이지 이동으로 URL에서 _s가 사라진 경우 재주입 → 새로고침 후 복원 가능
    from utils.session import ensure_session_in_url
    ensure_session_in_url()
    return st.session_state.user


def get_active_brand_id(profile: dict) -> str | None:
    """brand_user의 현재 활성 brand_id 반환 (멀티브랜드 switcher 반영)."""
    active = st.session_state.get("active_brand_id")
    if active:
        brand_ids = profile.get("brand_ids") or []
        if active in brand_ids:
            return active
    return profile.get("brand_id")


def sidebar_user_info() -> None:
    user = st.session_state.get("user")
    if not user:
        return
    with st.sidebar:
        from utils.supabase_client import get_user_profile, get_brands
        profile = get_user_profile(user.id)
        is_admin = profile.get("role") == "admin"

        if is_admin:
            st.markdown("**🔧 관리자 메뉴**")
            st.page_link("pages/_dashboard.py", label="📊 어드민 대시보드", use_container_width=True)
            st.page_link("pages/_brands.py",   label="🏢 브랜드 관리",     use_container_width=True)
            st.divider()
        else:
            # 비관리자: 어드민 전용 페이지를 자동 생성 네비에서 숨김
            st.markdown("""
<style>
[data-testid="stSidebarNav"] a[href*="_dashboard"],
[data-testid="stSidebarNav"] li:has(a[href*="_dashboard"]) { display:none!important; }
</style>
""", unsafe_allow_html=True)

            brand_ids = profile.get("brand_ids") or []
            if len(brand_ids) > 1:
                all_brands = get_brands()
                bmap = {b["id"]: b["name"] for b in all_brands}
                options = [bid for bid in brand_ids if bid in bmap]
                if options:
                    labels = [bmap[bid] for bid in options]
                    primary = profile.get("brand_id")
                    default_idx = options.index(primary) if primary in options else 0
                    selected = st.selectbox(
                        "브랜드", labels, index=default_idx, key="_active_brand"
                    )
                    st.session_state["active_brand_id"] = options[labels.index(selected)]
                    st.divider()

        st.caption(f"👤 {user.email}")
        if st.button("로그아웃", use_container_width=True, key="_sidebar_logout"):
            from utils.supabase_client import sign_out
            from utils.session import clear_session
            sign_out()
            clear_session()
            st.session_state.clear()
            st.rerun()
