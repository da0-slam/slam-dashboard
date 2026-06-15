import uuid
import os
import requests
import streamlit as st

_QP_KEY = "_s"          # URL param — legacy fallback only (cleared after reading)
_COOKIE_KEY = "slam_s"  # Browser cookie key
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


# ─── Supabase REST (service key로만 접근) ─────────────────────────────────────

def _get_env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        try:
            val = str(st.secrets.get(name, ""))
        except Exception:
            pass
    return val.split("\n")[0].strip()

def _sb_url() -> str:
    return _get_env("SUPABASE_URL").rstrip("/")

def _sb_headers() -> dict:
    key = _get_env("SUPABASE_KEY")
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }

def _db_save(sid: str, refresh_token: str) -> None:
    try:
        requests.post(
            f"{_sb_url()}/rest/v1/slam_sessions",
            headers=_sb_headers(),
            json={"id": sid, "refresh_token": refresh_token},
            timeout=5,
        )
    except Exception:
        pass

def _db_load(sid: str) -> str | None:
    """refresh_token 반환, 없거나 만료됐으면 None."""
    try:
        r = requests.get(
            f"{_sb_url()}/rest/v1/slam_sessions",
            headers={k: v for k, v in _sb_headers().items() if k != "Prefer"},
            params={"id": f"eq.{sid}", "select": "refresh_token,expires_at", "limit": "1"},
            timeout=5,
        )
        rows = r.json()
        if not rows:
            return None
        row = rows[0]
        from datetime import datetime, timezone
        exp = row.get("expires_at", "")
        if exp:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                _db_delete(sid)
                return None
        return row.get("refresh_token")
    except Exception:
        return None

def _db_update_refresh(sid: str, refresh_token: str) -> None:
    try:
        requests.patch(
            f"{_sb_url()}/rest/v1/slam_sessions",
            headers=_sb_headers(),
            params={"id": f"eq.{sid}"},
            json={"refresh_token": refresh_token},
            timeout=5,
        )
    except Exception:
        pass

def _db_delete(sid: str) -> None:
    try:
        requests.delete(
            f"{_sb_url()}/rest/v1/slam_sessions",
            headers={k: v for k, v in _sb_headers().items() if k != "Prefer"},
            params={"id": f"eq.{sid}"},
            timeout=5,
        )
    except Exception:
        pass


# ─── 인메모리 캐시 ────────────────────────────────────────────────────────────

@st.cache_resource
def _mem() -> dict:
    return {}


# ─── 쿠키 읽기/쓰기 ──────────────────────────────────────────────────────────

def _cookie_read(key: str):
    """st.context.cookies로 HTTP 요청 쿠키를 동기적으로 읽음 (Streamlit >= 1.35)."""
    try:
        return st.context.cookies.get(key)
    except AttributeError:
        return None

def _cookie_write(key: str, value: str) -> None:
    """CookieController 컴포넌트로 브라우저에 쿠키 저장."""
    try:
        from streamlit_cookies_controller import CookieController
        ctrl = _get_ctrl()
        ctrl.set(key, value, max_age=_COOKIE_MAX_AGE)
    except Exception:
        pass

def _cookie_delete(key: str) -> None:
    """브라우저 쿠키 삭제."""
    try:
        ctrl = _get_ctrl()
        ctrl.remove(key)
    except Exception:
        pass

def _get_ctrl():
    """CookieController를 session_state에 캐시 (페이지당 1회 렌더링)."""
    if "_cookie_ctrl" not in st.session_state:
        from streamlit_cookies_controller import CookieController
        st.session_state["_cookie_ctrl"] = CookieController()
    return st.session_state["_cookie_ctrl"]


# ─── 공개 API ─────────────────────────────────────────────────────────────────

def save_session(access_token: str, refresh_token: str) -> None:
    sid = str(uuid.uuid4())
    _mem()[sid] = {"access": access_token, "refresh": refresh_token}
    _db_save(sid, refresh_token)
    st.session_state["_session_id"] = sid
    st.session_state.access_token = access_token
    # 쿠키에 세션 ID 저장 (URL 노출 없이 새로고침 복원)
    _cookie_write(_COOKIE_KEY, sid)


def restore_session() -> bool:
    """session_state 우선, 없으면 쿠키(동기) → URL 순으로 복원."""
    if st.session_state.get("user"):
        # 이미 인증됨 — URL에 남은 레거시 토큰 정리
        _clear_url_token()
        return True

    # 1) HTTP 쿠키에서 sid 동기적으로 읽기 (st.context.cookies)
    sid = _cookie_read(_COOKIE_KEY)

    # 2) 레거시 URL 파라미터 fallback
    if not sid:
        sid = st.query_params.get(_QP_KEY)

    if not sid:
        return False

    return _restore_from_sid(sid)


def ensure_session_in_url() -> None:
    """쿠키 기반 세션으로 전환 — URL 토큰 재주입 불필요. 레거시 토큰만 정리."""
    _clear_url_token()


def save_pkce_verifier(verifier: str, tid: str) -> None:
    _mem()[f"pkce_{tid}"] = verifier


def pop_pkce_verifier(tid: str) -> str | None:
    return _mem().pop(f"pkce_{tid}", None)


def clear_session() -> None:
    sid = st.session_state.get("_session_id")
    if sid:
        _mem().pop(sid, None)
        _db_delete(sid)
    st.session_state.pop("_session_id", None)
    _cookie_delete(_COOKIE_KEY)
    _clear_url_token()


# ─── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _clear_url_token() -> None:
    if st.query_params.get(_QP_KEY):
        try:
            del st.query_params[_QP_KEY]
        except Exception:
            pass


def _restore_from_sid(sid: str) -> bool:
    """sid로 인메모리 캐시 또는 DB에서 세션 복원."""
    data = _mem().get(sid)

    if not data:
        refresh_token = _db_load(sid)
        if not refresh_token:
            _clear_url_token()
            return False
        data = {"access": "", "refresh": refresh_token}
        _mem()[sid] = data

    try:
        from utils.supabase_client import refresh_session as _refresh
        res = _refresh(data.get("access", ""), data["refresh"])
        if res and res.user:
            st.session_state.user           = res.user
            st.session_state.access_token   = res.session.access_token
            st.session_state["_session_id"] = sid
            new_refresh = res.session.refresh_token
            _mem()[sid] = {"access": res.session.access_token, "refresh": new_refresh}
            _db_update_refresh(sid, new_refresh)
            # 쿠키 갱신 (만료 연장) + URL 토큰 제거
            _cookie_write(_COOKIE_KEY, sid)
            _clear_url_token()
            return True
    except Exception:
        clear_session()

    return False
