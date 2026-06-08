import uuid
import streamlit as st

_QP_KEY = "_s"


@st.cache_resource
def _store() -> dict:
    """서버 메모리 세션 저장소. Streamlit 프로세스가 살아있는 동안 유지."""
    return {}


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
