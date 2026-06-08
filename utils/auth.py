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
        st.divider()
        st.caption(f"👤 {user.email}")
        if st.button("로그아웃", use_container_width=True, key="_sidebar_logout"):
            from utils.supabase_client import sign_out
            from utils.session import clear_session
            sign_out()
            clear_session()
            st.session_state.clear()
            st.rerun()
