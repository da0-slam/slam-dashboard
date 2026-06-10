import uuid
import streamlit as st

_QP_KEY = "_s"
_LS_KEY = "slam_sid"


@st.cache_resource
def _store() -> dict:
    """서버 메모리 세션 저장소. Streamlit 프로세스가 살아있는 동안 유지."""
    return {}


def _save_to_storage(sid: str) -> None:
    """브라우저 localStorage에 세션 ID 저장 (페이지 이동 후 복원용)."""
    try:
        import streamlit.components.v1 as components
        components.html(
            f'<script>try{{localStorage.setItem("{_LS_KEY}","{sid}")}}catch(e){{}}</script>',
            height=0,
        )
    except Exception:
        pass


def inject_restore_js() -> None:
    """URL에 _s가 없으면 localStorage에서 읽어 URL에 추가 후 리다이렉트."""
    if st.query_params.get(_QP_KEY):
        return
    try:
        import streamlit.components.v1 as components
        components.html(
            f"""<script>
(function(){{
  try{{
    var sid=localStorage.getItem("{_LS_KEY}");
    if(!sid) return;
    var p=new URLSearchParams(window.parent.location.search);
    if(p.get("{_QP_KEY}")) return;
    p.set("{_QP_KEY}",sid);
    window.parent.location.replace(window.parent.location.pathname+"?"+p.toString());
  }}catch(e){{}}
}})();
</script>""",
            height=0,
        )
    except Exception:
        pass


def restore_session() -> bool:
    if st.session_state.get("user"):
        return True

    sid = st.query_params.get(_QP_KEY)
    if not sid:
        return False

    data = _store().get(sid)
    if not data:
        return False

    try:
        from utils.supabase_client import refresh_session
        res = refresh_session(data["access"], data["refresh"])
        if res and res.user:
            st.session_state.user         = res.user
            st.session_state.access_token = res.session.access_token
            _store()[sid]["access"]        = res.session.access_token
            _save_to_storage(sid)
            return True
    except Exception:
        clear_session()

    return False


def save_session(access_token: str, refresh_token: str) -> None:
    sid = str(uuid.uuid4())
    _store()[sid] = {"access": access_token, "refresh": refresh_token}
    st.query_params[_QP_KEY] = sid


def save_pkce_verifier(verifier: str, tid: str) -> None:
    _store()[f"pkce_{tid}"] = verifier


def pop_pkce_verifier(tid: str) -> str | None:
    return _store().pop(f"pkce_{tid}", None)


def clear_session() -> None:
    sid = st.query_params.get(_QP_KEY)
    if sid:
        _store().pop(sid, None)
    try:
        del st.query_params[_QP_KEY]
    except Exception:
        pass
    try:
        import streamlit.components.v1 as components
        components.html(
            f'<script>try{{localStorage.removeItem("{_LS_KEY}")}}catch(e){{}}</script>',
            height=0,
        )
    except Exception:
        pass
