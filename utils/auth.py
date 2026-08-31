import streamlit as st

# 데모 리포트 계정 — 콘텐츠 성과 관리 페이지만 접근 가능 (user_profiles.role 체크 제약 때문에
# role 자체는 brand_user로 두고, 이메일로 데모 여부를 판별한다)
_DEMO_EMAILS = {"owm@report.com"}


def _is_demo_user(user) -> bool:
    return (getattr(user, "email", "") or "").strip().lower() in _DEMO_EMAILS


def require_auth():
    if not st.session_state.get("user"):
        from utils.session import restore_session
        restore_session()
    if not st.session_state.get("user"):
        st.warning("로그인이 필요합니다.")
        st.page_link("app.py", label="🔐 로그인 페이지로 이동", use_container_width=True)
        st.stop()
    # 페이지 이동으로 URL에서 _s가 사라진 경우 재주입 → 새로고침 후 복원 가능
    from utils.session import ensure_session_in_url
    ensure_session_in_url()
    return st.session_state.user


def block_if_demo() -> None:
    """데모 계정은 콘텐츠 성과 관리 페이지만 접근 가능 — 다른 페이지 접근 시 리다이렉트."""
    user = st.session_state.get("user")
    if user and _is_demo_user(user):
        st.switch_page("pages/6_content_performance.py")


def get_active_brand_id(profile: dict) -> str | None:
    """brand_user의 현재 활성 brand_id 반환 (멀티브랜드 switcher 반영)."""
    active = st.session_state.get("active_brand_id")
    if active:
        brand_ids = profile.get("brand_ids") or []
        if active in brand_ids:
            return active
    return profile.get("brand_id")


def sidebar_user_info() -> None:
    """사이드바 하단의 사용자 정보 영역(브랜드 전환·이메일·로그아웃)을 그린다.
    페이지 목록 자체(어느 페이지를 누구에게 보여줄지)는 더 이상 여기서 CSS로
    숨기지 않고, app.py의 st.navigation()이 역할별로 직접 구성한다."""
    user = st.session_state.get("user")
    if not user:
        return
    with st.sidebar:
        from utils.supabase_client import get_user_profile, get_brands
        profile = get_user_profile(user.id)

        if _is_demo_user(user):
            st.caption(f"👤 {user.email}")
            if st.button("로그아웃", use_container_width=True, key="_sidebar_logout"):
                from utils.supabase_client import sign_out
                from utils.session import clear_session
                sign_out()
                clear_session()
                st.session_state.clear()
                st.rerun()
            return

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
