import streamlit as st


def require_auth():
    if not st.session_state.get("user"):
        st.warning("로그인이 필요합니다.")
        st.stop()
    return st.session_state.user


def sidebar_user_info() -> None:
    user = st.session_state.get("user")
    if not user:
        return
    with st.sidebar:
        # 어드민 전용 메뉴
        from utils.supabase_client import get_user_profile
        profile = get_user_profile(user.id)
        if profile.get("role") == "admin":
            st.markdown("**🔧 관리자 메뉴**")
            st.page_link("pages/_dashboard.py", label="📊 어드민 대시보드", use_container_width=True)
            st.page_link("pages/_brands.py",   label="🏢 브랜드 관리",     use_container_width=True)
            st.divider()

        st.caption(f"👤 {user.email}")
        if st.button("로그아웃", use_container_width=True, key="_sidebar_logout"):
            from utils.supabase_client import sign_out
            from utils.session import clear_session
            sign_out()
            clear_session()
            st.session_state.clear()
            st.rerun()
