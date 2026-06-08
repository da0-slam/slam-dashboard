import os
import hashlib
import base64
from os import urandom
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests as _req
import streamlit as st
from supabase import create_client, Client
from types import SimpleNamespace


# ─── 비밀번호 해시 유틸 (표준 라이브러리만 사용) ─────────────────────────────

def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256으로 해시. salt(16B) + digest를 base64 인코딩하여 반환."""
    salt = urandom(16)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return base64.b64encode(salt + dk).decode()


def verify_password(password: str, stored: str) -> bool:
    """hash_password()로 생성된 해시와 입력 비밀번호를 비교."""
    try:
        raw  = base64.b64decode(stored.encode())
        salt = raw[:16]
        dk   = raw[16:]
        new_dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return new_dk == dk
    except Exception:
        return False


@st.cache_resource
def _clean_env(name: str) -> str:
    """env var에 개행이 섞인 경우 첫 번째 줄만 사용."""
    return os.environ.get(name, "").split("\n")[0].strip()


@st.cache_resource
def get_supabase() -> Client:
    url = _clean_env("SUPABASE_URL").rstrip("/")
    key = _clean_env("SUPABASE_KEY")
    if not url or not key:
        st.error("환경변수 SUPABASE_URL, SUPABASE_KEY를 설정하세요.")
        st.stop()
    return create_client(url, key)


# ─── Auth 헬퍼 (requests 직접 사용 — Railway HTTP/2 우회) ─────────────────────

def _aurl(path: str) -> str:
    return f"{os.environ.get('SUPABASE_URL', '').rstrip('/')}/auth/v1{path}"

def _aheaders() -> dict:
    return {"apikey": _clean_env("SUPABASE_KEY"), "Content-Type": "application/json"}

def _wrap(data: dict):
    """Supabase auth REST 응답 dict → .user/.session 속성 객체로 변환."""
    user_data = data.get("user") or (data if data.get("id") else {})
    user = SimpleNamespace(
        id=user_data.get("id", ""),
        email=user_data.get("email", ""),
        identities=user_data.get("identities") or [],
    ) if user_data.get("id") else None
    session = SimpleNamespace(
        access_token=data.get("access_token", ""),
        refresh_token=data.get("refresh_token", ""),
    )
    return SimpleNamespace(user=user, session=session)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Auth ────────────────────────────────────────────────────────────────────

def sign_in(email: str, password: str):
    r = _req.post(
        _aurl("/token?grant_type=password"),
        headers=_aheaders(),
        json={"email": email, "password": password},
        timeout=30,
    )
    data = r.json()
    if not r.ok:
        raise Exception(data.get("error_description") or data.get("msg") or data.get("error") or r.text)
    return _wrap(data)


def sign_up(email: str, password: str):
    r = _req.post(
        _aurl("/signup"),
        headers=_aheaders(),
        json={"email": email, "password": password},
        timeout=30,
    )
    data = r.json()
    if not r.ok:
        raise Exception(data.get("error_description") or data.get("msg") or data.get("error") or r.text)
    return _wrap(data)


def sign_out() -> None:
    try:
        _req.post(_aurl("/logout"), headers=_aheaders(), timeout=10)
    except Exception:
        pass


def refresh_session(access_token: str, refresh_token: str):
    """세션 복원용 — refresh_token으로 새 access_token 발급."""
    r = _req.post(
        _aurl("/token?grant_type=refresh_token"),
        headers=_aheaders(),
        json={"refresh_token": refresh_token},
        timeout=30,
    )
    if not r.ok:
        return None
    return _wrap(r.json())


def get_oauth_url(provider: str, redirect_to: str) -> tuple[str, str | None]:
    """OAuth 로그인 URL 생성. (oauth_url, pkce_code_verifier) 반환."""
    res = get_supabase().auth.sign_in_with_oauth({
        "provider": provider,
        "options": {
            "redirect_to": redirect_to,
            "skip_browser_redirect": True,
        },
    })
    return res.url, getattr(res, "pkce_code_verifier", None)


def exchange_oauth_code(auth_code: str, code_verifier: str | None = None):
    """OAuth 인가 코드를 세션으로 교환."""
    params: dict = {"auth_code": auth_code}
    if code_verifier:
        params["code_verifier"] = code_verifier
    return get_supabase().auth.exchange_code_for_session(params)


# ─── Brands ──────────────────────────────────────────────────────────────────

def get_brands() -> list[dict]:
    res = get_supabase().table("brands").select("*").order("name").execute()
    return res.data or []


def get_brand_by_id(brand_id: str) -> dict:
    res = get_supabase().table("brands").select("*").eq("id", brand_id).limit(1).execute()
    return res.data[0] if res.data else {}


def get_brand_access_password_hash(brand_id: str) -> str | None:
    res = get_supabase().table("brands").select("access_password_hash").eq("id", brand_id).limit(1).execute()
    if res.data:
        return res.data[0].get("access_password_hash") or None
    return None


def set_brand_access_password(brand_id: str, password: str) -> None:
    get_supabase().table("brands").update({"access_password_hash": hash_password(password)}).eq("id", brand_id).execute()


def get_campaign_if_owned(campaign_id: str, brand_id: str) -> dict | None:
    """campaign_id + brand_id 동시 일치 시에만 반환 — 소유권 검증용."""
    res = (
        get_supabase()
        .table("campaigns")
        .select("*")
        .eq("id", campaign_id)
        .eq("brand_id", brand_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def create_brand(data: dict) -> None:
    clean = {k: v for k, v in data.items() if v}
    get_supabase().table("brands").insert(clean).execute()


def update_brand(brand_id: str, data: dict) -> None:
    data["updated_at"] = _now()
    get_supabase().table("brands").update(data).eq("id", brand_id).execute()


def delete_brand(brand_id: str) -> None:
    get_supabase().table("brands").delete().eq("id", brand_id).execute()


# ─── Influencers ─────────────────────────────────────────────────────────────

def get_influencers(search: str = "", limit: int = 200) -> list[dict]:
    q = get_supabase().table("influencer_master").select(
        "influencer_id,account_url,platform,apify_status"
    )
    if search:
        q = q.ilike("influencer_id", f"%{search}%")
    return (q.order("influencer_id").limit(limit).execute()).data or []


def get_brand_selections(brand_id: str, status: str | None = None) -> list[dict]:
    q = (
        get_supabase()
        .table("brand_selections")
        .select("id,influencer_id,status,note,selected_at,influencer_master(influencer_id,account_url,platform,apify_status)")
        .eq("brand_id", brand_id)
    )
    if status:
        q = q.eq("status", status)
    return (q.order("selected_at", desc=True).execute()).data or []


def select_influencer(brand_id: str, influencer_id: str) -> None:
    get_supabase().table("brand_selections").upsert(
        {"brand_id": brand_id, "influencer_id": influencer_id, "status": "candidate"},
        on_conflict="brand_id,influencer_id",
    ).execute()


def update_selection_status(selection_id: str, status: str, note: str | None = None) -> None:
    data: dict = {"status": status, "updated_at": _now()}
    if note is not None:
        data["note"] = note
    get_supabase().table("brand_selections").update(data).eq("id", selection_id).execute()


def remove_selection(selection_id: str) -> None:
    get_supabase().table("brand_selections").delete().eq("id", selection_id).execute()


# ─── User Profile ────────────────────────────────────────────────────────────

def get_user_profile(user_id: str) -> dict:
    res = get_supabase().table("user_profiles").select("*").eq("user_id", user_id).limit(1).execute()
    return res.data[0] if res.data else {}


def upsert_user_profile(user_id: str, role: str = "brand_user", brand_id: str | None = None) -> None:
    data: dict = {"user_id": user_id, "role": role}
    if brand_id:
        data["brand_id"] = brand_id
    get_supabase().table("user_profiles").upsert(data, on_conflict="user_id").execute()


def setup_brand_user(user_id: str, brand_name: str) -> str:
    """신규 가입 시 브랜드 + 유저 프로필 + 브랜드 멤버 자동 생성. brand_id 반환."""
    sb = get_supabase()
    brand_res = sb.table("brands").insert({"name": brand_name}).execute()
    brand_id  = brand_res.data[0]["id"]
    sb.table("user_profiles").upsert(
        {"user_id": user_id, "role": "brand_user", "brand_id": brand_id},
        on_conflict="user_id",
    ).execute()
    sb.table("brand_members").insert(
        {"brand_id": brand_id, "user_id": user_id, "role": "owner"}
    ).execute()
    return brand_id


# ─── Campaigns ───────────────────────────────────────────────────────────────

def get_campaigns(brand_id: str) -> list[dict]:
    return (
        get_supabase()
        .table("campaigns")
        .select("*")
        .eq("brand_id", brand_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []


def create_campaign(brand_id: str, name: str, description: str = "") -> dict:
    res = (
        get_supabase()
        .table("campaigns")
        .insert({"brand_id": brand_id, "name": name, "description": description})
        .execute()
    )
    return res.data[0] if res.data else {}


def update_campaign(campaign_id: str, data: dict) -> None:
    data["updated_at"] = _now()
    get_supabase().table("campaigns").update(data).eq("id", campaign_id).execute()


def delete_campaign(campaign_id: str) -> None:
    get_supabase().table("campaigns").delete().eq("id", campaign_id).execute()


def get_campaign_selections(campaign_id: str, status: str | None = None) -> list[dict]:
    q = (
        get_supabase()
        .table("campaign_selections")
        .select("id,influencer_id,status,note,selected_at")
        .eq("campaign_id", campaign_id)
    )
    if status:
        q = q.eq("status", status)
    return (q.order("selected_at", desc=True).execute()).data or []


def add_to_campaign(campaign_id: str, influencer_id: str) -> None:
    get_supabase().table("campaign_selections").upsert(
        {"campaign_id": campaign_id, "influencer_id": influencer_id, "status": "candidate"},
        on_conflict="campaign_id,influencer_id",
    ).execute()


def update_campaign_selection(selection_id: str, status: str, note: str | None = None) -> None:
    data: dict = {"status": status, "updated_at": _now()}
    if note is not None:
        data["note"] = note
    get_supabase().table("campaign_selections").update(data).eq("id", selection_id).execute()


def remove_campaign_selection(selection_id: str) -> None:
    get_supabase().table("campaign_selections").delete().eq("id", selection_id).execute()


def get_campaign_selection_map(campaign_id: str) -> dict[str, dict]:
    rows = (
        get_supabase()
        .table("campaign_selections")
        .select("influencer_id,id,status")
        .eq("campaign_id", campaign_id)
        .execute()
    ).data or []
    return {r["influencer_id"]: r for r in rows}


# ─── Browse ──────────────────────────────────────────────────────────────────

def get_browse_contents(platform: str | None = None, limit: int = 400) -> list[dict]:
    sb = get_supabase()

    # 콘텐츠 (조회수 순)
    contents = (
        sb.table("koc_contents")
        .select("influencer_id,video_url,thumbnail_url,play_count,like_count,comment_count,save_count,caption,posted_at")
        .order("play_count", desc=True)
        .limit(limit)
        .execute()
    ).data or []

    # 인플루언서 메타
    inf_rows = sb.table("influencer_master").select("influencer_id,account_url,platform,apify_status").execute().data or []
    inf_map  = {r["influencer_id"]: r for r in inf_rows}

    # 인플루언서별 최고 조회수 영상 1개만 (중복 제거)
    seen: set[str] = set()
    result = []
    for r in contents:
        iid = r["influencer_id"]
        if iid in seen:
            continue
        inf = inf_map.get(iid, {})
        if platform and inf.get("platform") != platform:
            continue
        seen.add(iid)
        r["influencer_master"] = inf
        result.append(r)
    return result


def get_influencer_thumbnails(influencer_ids: list[str]) -> dict[str, dict]:
    if not influencer_ids:
        return {}
    rows = (
        get_supabase()
        .table("koc_contents")
        .select("influencer_id,thumbnail_url,video_url,play_count")
        .in_("influencer_id", influencer_ids)
        .order("play_count", desc=True)
        .limit(len(influencer_ids) * 5)
        .execute()
    ).data or []
    result: dict[str, dict] = {}
    for r in rows:
        iid = r["influencer_id"]
        if iid not in result:
            result[iid] = {
                "thumbnail": r.get("thumbnail_url") or "",
                "video_url": r.get("video_url") or "",
            }
    return result


def get_brand_selection_map(brand_id: str) -> dict[str, dict]:
    rows = (
        get_supabase()
        .table("brand_selections")
        .select("influencer_id,id,status")
        .eq("brand_id", brand_id)
        .execute()
    ).data or []
    return {r["influencer_id"]: r for r in rows}


# ─── Dashboard ───────────────────────────────────────────────────────────────

def get_pipeline_stats() -> dict[str, int]:
    supabase = get_supabase()
    counts: dict[str, int] = {}
    for status in ("done", "pending", "failed", "no_content"):
        res = (
            supabase.table("influencer_master")
            .select("influencer_id", count="exact")
            .eq("apify_status", status)
            .limit(1)
            .execute()
        )
        counts[status] = res.count or 0
    res = (
        supabase.table("influencer_master")
        .select("influencer_id", count="exact")
        .is_("apify_status", "null")
        .limit(1)
        .execute()
    )
    counts["미수집"] = res.count or 0
    return counts


def get_total_content_count() -> int:
    res = (
        get_supabase()
        .table("koc_contents")
        .select("influencer_id", count="exact")
        .limit(1)
        .execute()
    )
    return res.count or 0


def get_top_contents(limit: int = 20) -> list[dict]:
    res = (
        get_supabase()
        .table("koc_contents")
        .select("influencer_id,video_url,play_count,like_count,comment_count,share_count,save_count,posted_at")
        .order("play_count", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []
