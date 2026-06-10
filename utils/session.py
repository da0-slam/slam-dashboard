import uuid
import os
import requests
import streamlit as st

_QP_KEY = "_s"

# ─── Supabase REST (service key로만 접근) ─────────────────────────────────────

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")

def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_KEY", "")
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
        # 만료 체크
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
    """rotation 후 새 refresh_token으로 DB 업데이트."""
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


# ─── 인메모리 캐시 (서버 살아있는 동안 빠른 접근용) ──────────────────────────

@st.cache_resource
def _mem() -> dict:
    return {}


# ─── 공개 API ─────────────────────────────────────────────────────────────────

def save_session(access_token: str, refresh_token: str) -> None:
    sid = str(uuid.uuid4())
    _mem()[sid] = {"access": access_token, "refresh": refresh_token}
    _db_save(sid, refresh_token)
    st.query_params[_QP_KEY] = sid
    st.session_state["_session_id"] = sid
    st.session_state.access_token = access_token


def restore_session() -> bool:
    if st.session_state.get("user"):
        return True

    sid = st.query_params.get(_QP_KEY)
    if not sid:
        return False

    # 1) 인메모리 캐시 확인 (서버 재시작 전 빠른 경로)
    data = _mem().get(sid)

    # 2) 메모리 미스 → DB에서 복원 (서버 재시작 후)
    if not data:
        refresh_token = _db_load(sid)
        if not refresh_token:
            return False
        data = {"access": "", "refresh": refresh_token}
        _mem()[sid] = data  # 이후 접근을 위해 캐시에 올림

    try:
        from utils.supabase_client import refresh_session as _refresh
        res = _refresh(data.get("access", ""), data["refresh"])
        if res and res.user:
            st.session_state.user           = res.user
            st.session_state.access_token   = res.session.access_token
            st.session_state["_session_id"] = sid
            # rotation된 새 토큰 모두 업데이트
            new_refresh = res.session.refresh_token
            _mem()[sid] = {"access": res.session.access_token, "refresh": new_refresh}
            _db_update_refresh(sid, new_refresh)  # DB도 최신 refresh token으로 교체
            return True
    except Exception:
        clear_session()

    return False


def ensure_session_in_url() -> None:
    """서브 페이지 이동 후 URL에서 _s가 사라진 경우 복원."""
    if not st.query_params.get(_QP_KEY):
        sid = st.session_state.get("_session_id")
        if sid:
            st.query_params[_QP_KEY] = sid


def save_pkce_verifier(verifier: str, tid: str) -> None:
    _mem()[f"pkce_{tid}"] = verifier


def pop_pkce_verifier(tid: str) -> str | None:
    return _mem().pop(f"pkce_{tid}", None)


def clear_session() -> None:
    sid = st.query_params.get(_QP_KEY) or st.session_state.get("_session_id")
    if sid:
        _mem().pop(sid, None)
        _db_delete(sid)               # DB에서도 삭제
    st.session_state.pop("_session_id", None)
    try:
        del st.query_params[_QP_KEY]
    except Exception:
        pass
