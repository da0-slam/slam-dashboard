import os
import uuid
import streamlit as st
from utils.supabase_client import (
    sign_in, sign_up, setup_brand_user,
    get_oauth_url, exchange_oauth_code,
)
from utils.session import (
    restore_session, save_session,
    save_pkce_verifier, pop_pkce_verifier,
    init_cookie_controller,
)

SITE_URL = os.environ.get("SITE_URL", "http://localhost:8501").rstrip("/")

st.set_page_config(
    page_title="Slam Global | 관리 대시보드",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CookieController를 매 렌더마다 실행 — pending set/delete 처리를 위해 최상단에서 호출
init_cookie_controller()

if "user" not in st.session_state:
    st.session_state.user = None

# ─── 공개 리포트 링크 (토큰 기반, 로그인 여부와 무관하게 바로 진입) ──────────────
# st.navigation() 도입 전에는 pages/_content_report_view.py 등이 자동 라우팅으로
# 직접 서빙됐지만, 이제 app.py가 모든 경로의 유일한 진입점이 되므로 여기서
# 명시적으로 처리해야 한다.
if st.query_params.get("token"):
    st.navigation(
        [
            st.Page("pages/_content_report_view.py", title="콘텐츠 성과 리포트",
                    icon="📊", url_path="content_report_view"),
            st.Page("pages/_strategy_view.py", title="전략 문서",
                    icon="📋", url_path="strategy_view"),
        ],
        position="hidden",
    ).run()
    st.stop()

# ─── OAuth 콜백 처리 ──────────────────────────────────────────────────────────
_oauth_code  = st.query_params.get("code")
_pkce_tid    = st.query_params.get("_pkce")
_oauth_error = st.query_params.get("error")

if _oauth_error and not st.session_state.user:
    err_desc = st.query_params.get("error_description", _oauth_error)
    st.error(f"소셜 로그인 오류: {err_desc}")
    for p in ["error", "error_description", "_pkce"]:
        st.query_params.pop(p, None)

if _oauth_code and not st.session_state.user:
    verifier = pop_pkce_verifier(_pkce_tid) if _pkce_tid else None
    with st.spinner("소셜 로그인 처리 중..."):
        try:
            res = exchange_oauth_code(_oauth_code, verifier)
            st.session_state.user         = res.user
            st.session_state.access_token = res.session.access_token
            save_session(res.session.access_token, res.session.refresh_token)
            for p in ["code", "_pkce"]:
                st.query_params.pop(p, None)
            st.rerun()
        except Exception as e:
            st.error(f"소셜 로그인 실패: {e}")
            for p in ["code", "_pkce"]:
                st.query_params.pop(p, None)

# 세션 복원 (새로고침 대응)
if not st.session_state.user:
    restore_session()


# ─── OAuth 로그인 URL 사전 생성 ───────────────────────────────────────────────
def _oauth_link(provider: str) -> str:
    """provider별 OAuth URL을 세션 당 1회 생성해 캐시."""
    key = f"_oauth_url_{provider}"
    if key not in st.session_state:
        tid = str(uuid.uuid4())
        try:
            url, verifier = get_oauth_url(provider, f"{SITE_URL}?_pkce={tid}")
            if verifier:
                save_pkce_verifier(verifier, tid)
            st.session_state[key] = url
        except Exception:
            st.session_state[key] = ""
    return st.session_state[key]


# ─── 로그인 상태: 네비게이션 구성 ─────────────────────────────────────────────
if st.session_state.user:
    from utils.auth import _is_demo_user
    from utils.supabase_client import get_user_profile as _gup

    if _is_demo_user(st.session_state.user):
        # 데모 계정: 콘텐츠 성과 관리 페이지만 라우팅 자체를 허용 (CSS 숨김이 아니라
        # 아예 다른 페이지가 등록되지 않으므로 URL을 직접 쳐도 접근 불가)
        st.navigation(
            [st.Page("pages/6_content_performance.py", title="콘텐츠 성과 관리",
                     icon="📊", url_path="content_performance", default=True)],
            position="hidden",
        ).run()
        st.stop()

    _profile = _gup(st.session_state.user.id)
    is_admin = _profile.get("role") == "admin"

    _main_pages = [
        st.Page("pages/_home.py",             title="홈",              icon="🏠", url_path="home", default=True),
        st.Page("pages/_browse.py",           title="탐색",            icon="🎬", url_path="browse",             visibility="hidden"),
        st.Page("pages/2_influencers.py",     title="즐겨찾기",         icon="👥", url_path="influencers"),
        st.Page("pages/5_campaigns.py",       title="캠페인 관리",      icon="📋", url_path="campaigns"),
        st.Page("pages/6_content_performance.py", title="콘텐츠 성과 관리", icon="📊", url_path="content_performance"),
        st.Page("pages/7_strategy.py",        title="전략",            icon="🎯", url_path="strategy"),
        st.Page("pages/9_hashtags.py",        title="해시태그",         icon="#️⃣", url_path="hashtags"),
        st.Page("pages/8_settings.py",        title="계정 설정",       icon="⚙️", url_path="settings"),
        # 성능 이슈로 사이드바 노출은 보류하되, 필요 시 직접 링크로는 접근 가능하게 유지
        st.Page("pages/1_브랜드_마케팅_현황.py", title="브랜드 마케팅 현황", icon="📊",
                url_path="브랜드_마케팅_현황", visibility="hidden"),
        # 공개 리포트 — 로그인 상태에서도 관리자가 미리보기로 열어볼 수 있게 등록만 해둔다
        st.Page("pages/_content_report_view.py", title="콘텐츠 성과 리포트", icon="📊",
                url_path="content_report_view", visibility="hidden"),
        st.Page("pages/_strategy_view.py",     title="전략 문서",       icon="📋",
                url_path="strategy_view", visibility="hidden"),
    ]

    _pages = {"메인": _main_pages}
    if is_admin:
        _pages["🔧 관리자"] = [
            st.Page("pages/_dashboard.py",      title="어드민 대시보드",     icon="📊", url_path="dashboard"),
            st.Page("pages/_brands.py",         title="브랜드 관리",         icon="🏢", url_path="brands"),
            st.Page("pages/_top_posts.py",      title="우수 게시물 취합",   icon="⭐", url_path="top_posts"),
            st.Page("pages/_upload_status.py",  title="업로드 현황",         icon="📤", url_path="upload_status"),
        ]

    st.navigation(_pages).run()

# ─── 로그아웃 상태: 로그인 / 회원가입 폼 ────────────────────────────────────
else:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("## 🎯 Slam Global")
        st.divider()

        tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

        # ── 로그인 탭 ──────────────────────────────────────────────────────────
        with tab_login:
            with st.form("login_form"):
                email    = st.text_input("이메일", placeholder="이메일 주소를 입력하세요", key="login_email")
                password = st.text_input("비밀번호", type="password", key="login_password")
                submitted = st.form_submit_button("로그인", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("이메일과 비밀번호를 모두 입력하세요.")
                else:
                    with st.spinner("로그인 중..."):
                        try:
                            res = sign_in(email, password)
                            st.session_state.user         = res.user
                            st.session_state.access_token = res.session.access_token
                            save_session(res.session.access_token, res.session.refresh_token)
                            # 이메일 인증 후 첫 로그인 시 브랜드 자동 연결
                            pending_brand = st.session_state.pop("pending_brand_name", None)
                            if pending_brand and res.user:
                                from utils.supabase_client import get_user_profile, setup_brand_user
                                profile = get_user_profile(res.user.id)
                                if not profile.get("brand_id"):
                                    setup_brand_user(res.user.id, pending_brand)
                            st.rerun()
                        except Exception as e:
                            err = str(e)
                            if "Invalid login credentials" in err or "invalid_grant" in err:
                                st.error("이메일 또는 비밀번호가 올바르지 않습니다.")
                            elif "header value" in err or "whitespace" in err:
                                st.error("서버 설정 오류입니다. 관리자에게 문의하세요.")
                            else:
                                st.error("로그인에 실패했습니다. 잠시 후 다시 시도해주세요.")

            # ── 소셜 로그인 ────────────────────────────────────────────────────
            st.divider()
            st.caption("소셜 계정으로 로그인")

            google_url = _oauth_link("google")
            kakao_url  = _oauth_link("kakao")

            col_g, col_k = st.columns(2)
            with col_g:
                if google_url:
                    st.link_button(
                        "G  Google로 로그인",
                        google_url,
                        use_container_width=True,
                    )
                else:
                    st.button("G  Google로 로그인", disabled=True, use_container_width=True,
                              help="Google OAuth가 설정되지 않았습니다.")
            with col_k:
                if kakao_url:
                    st.link_button(
                        "K  카카오로 로그인",
                        kakao_url,
                        use_container_width=True,
                    )
                else:
                    st.button("K  카카오로 로그인", disabled=True, use_container_width=True,
                              help="Kakao OAuth가 설정되지 않았습니다.")

        # ── 회원가입 탭 ────────────────────────────────────────────────────────
        with tab_signup:
            with st.form("signup_form"):
                su_brand     = st.text_input("브랜드명 *", placeholder="브랜드명을 입력하세요", key="signup_brand")
                su_email     = st.text_input("이메일 *", placeholder="이메일 주소를 입력하세요", key="signup_email")
                su_password  = st.text_input("비밀번호 *", type="password", key="signup_password")
                su_password2 = st.text_input("비밀번호 확인 *", type="password", key="signup_password2")
                su_submitted = st.form_submit_button("회원가입", use_container_width=True, type="primary")

            if su_submitted:
                if not su_brand or not su_email or not su_password or not su_password2:
                    st.error("모든 항목을 입력하세요.")
                elif su_password != su_password2:
                    st.error("비밀번호가 일치하지 않습니다.")
                elif len(su_password) < 6:
                    st.error("비밀번호는 6자 이상이어야 합니다.")
                else:
                    with st.spinner("회원가입 중..."):
                        try:
                            res = sign_up(su_email, su_password)
                            if res.user:
                                if res.user.identities:
                                    # 이메일 인증 비활성화 환경 — 즉시 사용 가능
                                    setup_brand_user(res.user.id, su_brand)
                                    st.success(f"'{su_brand}' 브랜드로 가입이 완료되었습니다. 로그인하세요.")
                                else:
                                    # 이메일 인증 필요 — 브랜드는 인증 완료 후 로그인 시 연결
                                    st.info("📧 인증 이메일이 발송되었습니다.")
                                    st.markdown(
                                        f"**{su_email}** 받은편지함을 확인하고 "
                                        "인증 링크를 클릭하세요.  \n"
                                        "스팸함도 확인해보세요.  \n"
                                        "인증 완료 후 이 페이지로 돌아와 로그인하시면 됩니다."
                                    )
                                    # 브랜드명을 세션에 저장 → 첫 로그인 시 자동 연결
                                    st.session_state["pending_brand_name"] = su_brand
                            else:
                                st.warning("이미 가입된 이메일입니다.")
                        except Exception as e:
                            err = str(e)
                            if "already registered" in err or "User already registered" in err:
                                st.error("이미 가입된 이메일입니다.")
                            elif "confirmation email" in err or "sending" in err.lower() or "email" in err.lower():
                                st.error("이메일 발송에 실패했습니다. 잠시 후 다시 시도하거나 관리자에게 문의하세요.")
                            elif "header value" in err or "whitespace" in err:
                                st.error("서버 설정 오류입니다. 관리자에게 문의하세요.")
                            else:
                                st.error("회원가입에 실패했습니다. 잠시 후 다시 시도해주세요.")
