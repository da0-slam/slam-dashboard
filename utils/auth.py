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
    user = st.session_state.get("user")
    if not user:
        return
    with st.sidebar:
        from utils.supabase_client import get_user_profile, get_brands
        profile = get_user_profile(user.id)
        is_admin = profile.get("role") == "admin"

        # 브랜드 마케팅 현황 — 속도 이슈로 임시로 전체 사용자에게서 숨김
        # (href가 원문 한글로 나오는지 퍼센트 인코딩으로 나오는지 확실치 않아 둘 다 매칭)
        st.markdown("""
<style>
[data-testid="stSidebarNav"] a[href*="브랜드_마케팅_현황"],
[data-testid="stSidebarNav"] li:has(a[href*="브랜드_마케팅_현황"]),
[data-testid="stSidebarNav"] a[href*="%EB%B8%8C%EB%9E%9C%EB%93%9C_%EB%A7%88%EC%BC%80%ED%8C%85_%ED%98%84%ED%99%A9"],
[data-testid="stSidebarNav"] li:has(a[href*="%EB%B8%8C%EB%9E%9C%EB%93%9C_%EB%A7%88%EC%BC%80%ED%8C%85_%ED%98%84%ED%99%A9"]) { display:none!important; }
</style>
""", unsafe_allow_html=True)

        if _is_demo_user(user):
            # 데모 계정: 콘텐츠 성과 관리 외 모든 페이지를 사이드바 네비에서 숨김
            st.markdown("""
<style>
[data-testid="stSidebarNav"] li:not(:has(a[href*="6_content_performance"])) { display:none!important; }
</style>
""", unsafe_allow_html=True)
            st.caption(f"👤 {user.email}")
            if st.button("로그아웃", use_container_width=True, key="_sidebar_logout"):
                from utils.supabase_client import sign_out
                from utils.session import clear_session
                sign_out()
                clear_session()
                st.session_state.clear()
                st.rerun()
            return

        if is_admin:
            st.markdown("**🔧 관리자 메뉴**")
            st.page_link("pages/_dashboard.py",  label="📊 어드민 대시보드",   use_container_width=True)
            st.page_link("pages/_brands.py",     label="🏢 브랜드 관리",       use_container_width=True)
            st.page_link("pages/_top_posts.py",  label="⭐ 우수 게시물 취합",  use_container_width=True)
            st.page_link("pages/7_strategy.py",  label="🎯 전략",              use_container_width=True)
            st.divider()
            # 관리자도 전략 페이지 자동 nav 중복 숨김
            st.markdown("""
<style>
[data-testid="stSidebarNav"] a[href*="7_strategy"],
[data-testid="stSidebarNav"] li:has(a[href*="7_strategy"]) { display:none!important; }
</style>
""", unsafe_allow_html=True)
        else:
            # 비관리자: 어드민 전용 + 전략 페이지를 자동 생성 네비에서 숨김
            st.markdown("""
<style>
[data-testid="stSidebarNav"] a[href*="_dashboard"],
[data-testid="stSidebarNav"] li:has(a[href*="_dashboard"]),
[data-testid="stSidebarNav"] a[href*="_top_posts"],
[data-testid="stSidebarNav"] li:has(a[href*="_top_posts"]),
[data-testid="stSidebarNav"] a[href*="7_strategy"],
[data-testid="stSidebarNav"] li:has(a[href*="7_strategy"]) { display:none!important; }
</style>
""", unsafe_allow_html=True)

            brand_ids = profile.get("brand_ids") or []
            user_brand_ids = set(brand_ids + ([profile["brand_id"]] if profile.get("brand_id") else []))

            if user_brand_ids:
                st.page_link("pages/7_strategy.py", label="🎯 전략", use_container_width=True)

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
            if user_brand_ids:
                st.divider()

        st.caption(f"👤 {user.email}")
        st.page_link("pages/8_settings.py", label="⚙️ 계정 설정", use_container_width=True)
        if st.button("로그아웃", use_container_width=True, key="_sidebar_logout"):
            from utils.supabase_client import sign_out
            from utils.session import clear_session
            sign_out()
            clear_session()
            st.session_state.clear()
            st.rerun()
