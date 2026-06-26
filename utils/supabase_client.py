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
    """env var에 개행이 섞인 경우 첫 번째 줄만 사용. st.secrets fallback 포함."""
    val = os.environ.get(name, "")
    if not val:
        try:
            val = str(st.secrets.get(name, ""))
        except Exception:
            pass
    return val.split("\n")[0].strip()


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


def _detect_platform(url: str) -> str:
    url = (url or "").lower()
    if "tiktok.com" in url:    return "tiktok"
    if "instagram.com" in url: return "instagram"
    if "youtube.com" in url:   return "youtube"
    return "other"


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


def get_brand_strategy(brand_id: str) -> dict:
    res = (get_supabase().table("brand_strategy")
           .select("brand_guide,campaign_goals,competitor_refs,updated_at")
           .eq("brand_id", brand_id).limit(1).execute())
    return res.data[0] if res.data else {}


def upsert_brand_strategy(brand_id: str, updates: dict) -> bool:
    sb = get_supabase()
    existing = sb.table("brand_strategy").select("id").eq("brand_id", brand_id).limit(1).execute()
    if existing.data:
        res = (sb.table("brand_strategy")
               .update({**updates, "updated_at": "now()"})
               .eq("brand_id", brand_id).execute())
    else:
        res = sb.table("brand_strategy").insert({"brand_id": brand_id, **updates}).execute()
    return bool(res.data)


def get_strategy_files(brand_id: str, section: str | None = None) -> list[dict]:
    q = (get_supabase().table("brand_strategy_files")
         .select("*").eq("brand_id", brand_id))
    if section:
        q = q.eq("section", section)
    res = q.order("uploaded_at", desc=True).execute()
    return res.data or []


def add_strategy_file(brand_id: str, file_name: str, file_url: str,
                       file_type: str, file_size: int | None = None,
                       section: str = "general") -> dict | None:
    res = (get_supabase().table("brand_strategy_files")
           .insert({"brand_id": brand_id, "file_name": file_name,
                    "file_url": file_url, "file_type": file_type,
                    "file_size": file_size, "section": section}).execute())
    return res.data[0] if res.data else None


def delete_strategy_file(file_id: str) -> bool:
    res = (get_supabase().table("brand_strategy_files")
           .delete().eq("id", file_id).execute())
    return True


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
    try:
        get_supabase().table("brands").insert(clean).execute()
    except Exception:
        # 스키마에 없는 컬럼이 있으면 name만 저장
        get_supabase().table("brands").insert({"name": clean["name"]}).execute()


def update_brand(brand_id: str, data: dict) -> None:
    payload = {k: v for k, v in data.items() if k != "updated_at"}
    get_supabase().table("brands").update(payload).eq("id", brand_id).execute()


def delete_brand(brand_id: str) -> None:
    get_supabase().table("brands").delete().eq("id", brand_id).execute()


# ─── Influencers ─────────────────────────────────────────────────────────────

def get_influencers(search: str = "", limit: int = 200, ids: list[str] | None = None) -> list[dict]:
    q = get_supabase().table("influencer_master").select(
        "influencer_id,account_url,platform,apify_status,cover_url,instagram_url,instagram_followers"
    )
    if ids is not None:
        q = q.in_("influencer_id", ids)
    elif search:
        q = q.ilike("influencer_id", f"%{search}%")
    return (q.order("influencer_id").limit(max(limit, len(ids) if ids else limit)).execute()).data or []


@st.cache_data(ttl=3600, show_spinner=False)
def get_influencer_cover_map() -> dict:
    """influencer_id → cover_url 딕셔너리. 커버 이미지 있는 항목만."""
    res = (
        get_supabase()
        .table("influencer_master")
        .select("influencer_id,cover_url")
        .not_.is_("cover_url", "null")
        .execute()
    )
    return {r["influencer_id"].lower(): r["cover_url"] for r in (res.data or []) if r.get("cover_url")}


def get_brand_selections(brand_id: str, status: str | None = None) -> list[dict]:
    q = (
        get_supabase()
        .table("brand_selections")
        .select("id,influencer_id,status,note,selected_at,influencer_master(influencer_id,account_url,platform,apify_status,cover_url)")
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


def get_all_user_profiles() -> list[dict]:
    return get_supabase().table("user_profiles").select("*").execute().data or []


def get_all_auth_users() -> list[dict]:
    """Supabase Auth Admin API로 전체 유저 이메일 목록 조회."""
    import requests as _req
    key = _clean_env("SUPABASE_KEY")
    url = f"{os.environ.get('SUPABASE_URL', '').rstrip('/')}/auth/v1/admin/users?per_page=1000"
    resp = _req.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=10)
    if resp.status_code != 200:
        return []
    data = resp.json()
    users = data.get("users") or (data if isinstance(data, list) else [])
    return [{"id": u.get("id", ""), "email": u.get("email", "")} for u in users]


def update_user_role(user_id: str, role: str) -> bool:
    res = (
        get_supabase()
        .table("user_profiles")
        .update({"role": role})
        .eq("user_id", user_id)
        .execute()
    )
    return bool(res.data)


def assign_user_to_brand(user_id: str, brand_id: str) -> bool:
    res = (
        get_supabase()
        .table("user_profiles")
        .update({"brand_id": brand_id})
        .eq("user_id", user_id)
        .execute()
    )
    return bool(res.data)


def assign_user_brands(user_id: str, brand_ids: list[str]) -> bool:
    """여러 브랜드를 배정. 첫 번째가 primary brand_id."""
    update: dict = {"brand_ids": brand_ids}
    if brand_ids:
        update["brand_id"] = brand_ids[0]
    res = (
        get_supabase()
        .table("user_profiles")
        .update(update)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(res.data)


def setup_brand_user(user_id: str, brand_name: str) -> str:
    """신규 가입 시 브랜드 + 유저 프로필 + 브랜드 멤버 자동 생성. brand_id 반환.
    이미 brand_id가 연결된 경우 기존 값을 그대로 반환 (중복 생성 방지)."""
    existing = get_user_profile(user_id)
    if existing.get("brand_id"):
        return existing["brand_id"]

    sb = get_supabase()

    # 동일 브랜드명이 이미 존재하면 새로 만들지 않고 기존 브랜드에 연결
    existing_brand = sb.table("brands").select("id").eq("name", brand_name).execute().data
    if existing_brand:
        brand_id = existing_brand[0]["id"]
    else:
        brand_res = sb.table("brands").insert({"name": brand_name}).execute()
        brand_id  = brand_res.data[0]["id"]

    sb.table("user_profiles").upsert(
        {"user_id": user_id, "role": "brand_user", "brand_id": brand_id},
        on_conflict="user_id",
    ).execute()
    # brand_members는 중복 삽입 방지
    already_member = (
        sb.table("brand_members")
        .select("id")
        .eq("brand_id", brand_id)
        .eq("user_id", user_id)
        .execute()
        .data
    )
    if not already_member:
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


def get_or_create_invite_token(campaign_id: str) -> str | None:
    """캠페인 초대 토큰 반환 (없으면 새로 생성). campaigns.invite_token 컬럼 필요."""
    import uuid as _uuid
    sb = get_supabase()
    try:
        row = sb.table("campaigns").select("invite_token").eq("id", campaign_id).execute().data
        if row and row[0].get("invite_token"):
            return row[0]["invite_token"]
        token = _uuid.uuid4().hex[:20]
        sb.table("campaigns").update({"invite_token": token}).eq("id", campaign_id).execute()
        return token
    except Exception:
        return None


def get_campaign_by_invite_token(token: str) -> dict | None:
    """초대 토큰으로 캠페인 조회."""
    try:
        res = get_supabase().table("campaigns").select("*").eq("invite_token", token).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def get_campaign_selections(campaign_id: str, status: str | None = None) -> list[dict]:
    q = (
        get_supabase()
        .table("campaign_selections")
        .select("id,influencer_id,status,note,selected_at,followers,contact_email,ratecard,after_nego,usage_rights,platform_url")
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


def bulk_add_to_campaign(
    campaign_id: str,
    entries: list[dict],
) -> tuple[int, int, list[str]]:
    """CSV 등에서 인플루언서를 일괄 추가합니다.

    entries: [{"influencer_id": str, "status": str, "note": str}, ...]
    returns: (added, skipped, errors)
    """
    sb = get_supabase()
    existing = {
        r["influencer_id"]
        for r in (
            sb.table("campaign_selections")
            .select("influencer_id")
            .eq("campaign_id", campaign_id)
            .execute()
        ).data or []
    }

    to_insert = []
    skipped = 0
    errors: list[str] = []

    for e in entries:
        iid = str(e.get("influencer_id") or "").strip().lstrip("@")
        if not iid:
            errors.append(f"빈 influencer_id → 건너뜀")
            continue
        if iid in existing:
            skipped += 1
            continue
        to_insert.append({
            "campaign_id":   campaign_id,
            "influencer_id": iid,
            "status":        e.get("status", "candidate"),
            "note":          e.get("note") or None,
            "followers":     e.get("followers") or None,
            "contact_email": e.get("contact_email") or None,
            "ratecard":      e.get("ratecard") or None,
            "after_nego":    e.get("after_nego") or None,
            "usage_rights":  e.get("usage_rights") or None,
            "platform_url":  e.get("platform_url") or None,
        })

    # CSV 내부 중복 제거 (같은 influencer_id가 여러 행일 때)
    seen: dict = {}
    for row in to_insert:
        seen[row["influencer_id"]] = row
    to_insert = list(seen.values())

    if to_insert:
        sb.table("campaign_selections").upsert(
            to_insert, on_conflict="campaign_id,influencer_id"
        ).execute()

        # influencer_master 업데이트 (TikTok URL → account_url, Instagram URL/팔로워)
        inserted_ids = {row["influencer_id"] for row in to_insert}
        master_rows = []
        for e in entries:
            iid = str(e.get("influencer_id") or "").strip().lstrip("@")
            if iid not in inserted_ids:
                continue
            mrow: dict = {"influencer_id": iid}
            if e.get("platform_url"):
                mrow["account_url"] = e["platform_url"]
            if e.get("instagram_url"):
                mrow["instagram_url"] = e["instagram_url"]
            if e.get("instagram_followers"):
                mrow["instagram_followers"] = e["instagram_followers"]
            if len(mrow) > 1:
                master_rows.append(mrow)
        if master_rows:
            try:
                sb.table("influencer_master").upsert(
                    master_rows, on_conflict="influencer_id"
                ).execute()
            except Exception:
                pass  # influencer_master 업데이트 실패는 무시

    return len(to_insert), skipped, errors


def update_campaign_selection(selection_id: str, status: str, note: str | None = None) -> None:
    data: dict = {"status": status, "updated_at": _now()}
    if note is not None:
        data["note"] = note
    get_supabase().table("campaign_selections").update(data).eq("id", selection_id).execute()


def update_selection_note(selection_id: str, note: str) -> None:
    get_supabase().table("campaign_selections").update(
        {"note": note, "updated_at": _now()}
    ).eq("id", selection_id).execute()


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

@st.cache_data(ttl=3600, show_spinner=False)
def get_browse_contents(platform: str | None = None) -> list[dict]:
    sb = get_supabase()
    all_rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        q = (
            sb.table("v_browse_contents")
            .select("influencer_id,video_url,thumbnail_url,play_count,like_count,comment_count,share_count,save_count,caption,posted_at,cover_url,platform,instagram_url,instagram_followers,avg_play_count,us_db_followers")
            .order("play_count", desc=True)
        )
        if platform:
            q = q.eq("platform", platform)
        page = q.range(offset, offset + page_size - 1).execute().data or []
        all_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return all_rows


@st.cache_data(ttl=600, show_spinner=False)
def get_influencer_contents(influencer_id: str) -> list[dict]:
    rows = (
        get_supabase()
        .table("koc_contents")
        .select("influencer_id,video_url,thumbnail_url,play_count,like_count,comment_count,share_count,save_count,caption,posted_at")
        .eq("influencer_id", influencer_id)
        .order("play_count", desc=True)
        .execute()
    ).data or []
    for r in rows:
        r["platform"] = _detect_platform(r.get("video_url") or "")
    # 썸네일 있는 영상을 앞으로, 조회수 순 유지
    rows.sort(key=lambda r: (0 if "supabase" in (r.get("thumbnail_url") or "") else 1, -(r.get("play_count") or 0)))
    return rows


def update_influencer_cover(influencer_id: str, cover_url: str) -> None:
    get_supabase().table("influencer_master").upsert(
        {"influencer_id": influencer_id, "cover_url": cover_url},
        on_conflict="influencer_id",
    ).execute()


# ─── 인플루언서 메모/댓글 ─────────────────────────────────────────────────────

def get_influencer_notes(influencer_id: str, brand_id: str) -> list[dict]:
    return (
        get_supabase()
        .table("influencer_notes")
        .select("id,author_email,content,created_at,campaign_id")
        .eq("influencer_id", influencer_id)
        .eq("brand_id", brand_id)
        .order("created_at", desc=False)
        .execute()
    ).data or []


def get_note_counts(influencer_ids: list[str], brand_id: str) -> dict[str, int]:
    """influencer_id → 메모 수 맵 (한 번에 조회)."""
    if not influencer_ids:
        return {}
    rows = (
        get_supabase()
        .table("influencer_notes")
        .select("influencer_id")
        .in_("influencer_id", influencer_ids)
        .eq("brand_id", brand_id)
        .execute()
    ).data or []
    counts: dict[str, int] = {}
    for r in rows:
        iid = r["influencer_id"]
        counts[iid] = counts.get(iid, 0) + 1
    return counts


def add_influencer_note(
    influencer_id: str,
    brand_id: str,
    author_email: str,
    content: str,
    campaign_id: str | None = None,
) -> None:
    get_supabase().table("influencer_notes").insert({
        "influencer_id": influencer_id,
        "brand_id":      brand_id,
        "author_email":  author_email,
        "content":       content,
        "campaign_id":   campaign_id,
    }).execute()


def delete_influencer_note(note_id: str) -> None:
    get_supabase().table("influencer_notes").delete().eq("id", note_id).execute()


def update_influencer_note(note_id: str, content: str) -> None:
    get_supabase().table("influencer_notes").update({"content": content}).eq("id", note_id).execute()


def get_recent_notes(brand_id: str, limit: int = 40) -> list[dict]:
    """브랜드의 최근 댓글 목록 (패널용)."""
    return (
        get_supabase()
        .table("influencer_notes")
        .select("id,influencer_id,author_email,content,created_at")
        .eq("brand_id", brand_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []


def get_influencer_thumbnails(influencer_ids: list[str]) -> dict[str, dict]:
    if not influencer_ids:
        return {}
    rows = (
        get_supabase()
        .table("koc_contents")
        .select("influencer_id,thumbnail_url,video_url,play_count,like_count,comment_count,share_count,save_count,caption")
        .in_("influencer_id", influencer_ids)
        .limit(len(influencer_ids) * 10)
        .execute()
    ).data or []

    # 캠페인 썸네일 우선순위: TikTok 우선 → supabase 저장 썸네일 → ER 높은 순 → 조회수 높은 순
    def _sort_key(r):
        is_tiktok    = 0 if "tiktok" in (r.get("video_url") or "").lower() else 1
        has_supabase = 0 if "supabase" in (r.get("thumbnail_url") or "") else 1
        play = r.get("play_count") or 0
        eng  = sum(r.get(k) or 0 for k in ("like_count", "comment_count", "share_count", "save_count"))
        er   = eng / play if play > 0 else 0
        return (is_tiktok, has_supabase, -er, -play)

    # 인플루언서별 플랫폼 목록 수집 (video_url 기반 감지)
    platforms_map: dict[str, set] = {}
    for r in rows:
        iid  = r["influencer_id"]
        plat = _detect_platform(r.get("video_url") or "")
        platforms_map.setdefault(iid, set()).add(plat)

    # 인플루언서별 집계: 최고 ER
    agg: dict[str, dict] = {}
    for r in rows:
        iid  = r["influencer_id"]
        play = r.get("play_count") or 0
        eng  = sum(r.get(k) or 0 for k in ("like_count", "comment_count", "share_count", "save_count"))
        er   = eng / play if play > 0 else 0
        if iid not in agg:
            agg[iid] = {"max_er": 0.0}
        if er > agg[iid]["max_er"]:
            agg[iid]["max_er"] = er

    result: dict[str, dict] = {}
    for r in sorted(rows, key=_sort_key):
        iid = r["influencer_id"]
        if iid not in result:
            result[iid] = {
                "thumbnail":   r.get("thumbnail_url") or "",
                "video_url":   r.get("video_url") or "",
                "platforms":   sorted(platforms_map.get(iid, set())),
                "er":          agg.get(iid, {}).get("max_er", 0.0),
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


# ── Campaign Posts ────────────────────────────────────────────────────────────

def get_campaign_posts(
    brand_id: str,
    campaign_id: str | None = None,
    platform: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    search_name: str | None = None,
    search_url: str | None = None,
    sort_by: str = "upload_date",
    sort_asc: bool = False,
) -> list[dict]:
    _SORT_COLS = {"upload_date", "views", "likes", "saves", "comments", "shares", "created_at"}
    q = (
        get_supabase()
        .table("campaign_posts")
        .select("*")
        .eq("brand_id", brand_id)
    )
    if campaign_id:
        q = q.eq("campaign_id", campaign_id)
    if platform:
        q = q.eq("platform", platform)
    if start_date:
        q = q.gte("upload_date", start_date)
    if end_date:
        q = q.lte("upload_date", end_date)
    if search_name:
        q = q.ilike("influencer_name", f"%{search_name}%")
    if search_url:
        q = q.ilike("post_url", f"%{search_url}%")
    col = sort_by if sort_by in _SORT_COLS else "upload_date"
    q = q.order(col, desc=not sort_asc)
    res = q.execute()
    return res.data or []


def get_campaign_post_by_id(post_id: str, brand_id: str) -> dict | None:
    res = (
        get_supabase()
        .table("campaign_posts")
        .select("*")
        .eq("id", post_id)
        .eq("brand_id", brand_id)
        .execute()
    )
    return res.data[0] if res.data else None


def post_url_exists(post_url: str, exclude_post_id: str | None = None) -> bool:
    q = get_supabase().table("campaign_posts").select("id").eq("post_url", post_url)
    if exclude_post_id:
        q = q.neq("id", exclude_post_id)
    res = q.execute()
    return bool(res.data)


def create_campaign_post(brand_id: str, data: dict) -> dict | None:
    payload = {**data, "brand_id": brand_id, "created_at": _now(), "updated_at": _now()}
    res = get_supabase().table("campaign_posts").insert(payload).execute()
    return res.data[0] if res.data else None


def update_campaign_post(post_id: str, brand_id: str, data: dict) -> bool:
    payload = {**data, "updated_at": _now()}
    res = (
        get_supabase()
        .table("campaign_posts")
        .update(payload)
        .eq("id", post_id)
        .eq("brand_id", brand_id)
        .execute()
    )
    return bool(res.data)


def update_campaign_post_thumbnail(post_id: str, brand_id: str, thumbnail_url: str) -> bool:
    return update_campaign_post(post_id, brand_id, {"thumbnail_url": thumbnail_url})


def delete_campaign_post(post_id: str, brand_id: str) -> bool:
    get_supabase().table("campaign_posts").delete().eq("id", post_id).eq("brand_id", brand_id).execute()
    return True


def bulk_upsert_koc_contents(rows: list[dict]) -> tuple[int, list[str]]:
    """koc_contents에 Apify 형식 행을 일괄 upsert합니다.
    influencer_master에 없는 influencer_id는 자동 등록 후 삽입합니다.
    rows: [{"influencer_id", "video_url", "play_count", ...}, ...]
    returns: (upserted_count, errors)
    """
    sb = get_supabase()
    errors: list[str] = []
    valid = []
    for r in rows:
        if not r.get("influencer_id") or not r.get("video_url"):
            continue
        valid.append(r)

    if not valid:
        return 0, errors

    # influencer_master에 없는 인플루언서 자동 등록
    unique_ids = list({r["influencer_id"] for r in valid})
    existing_ids: set[str] = set()
    CHUNK = 500
    for i in range(0, len(unique_ids), CHUNK):
        res = (
            sb.table("influencer_master")
            .select("influencer_id")
            .in_("influencer_id", unique_ids[i:i + CHUNK])
            .execute()
        )
        existing_ids.update(r["influencer_id"] for r in (res.data or []))

    missing = [iid for iid in unique_ids if iid not in existing_ids]
    if missing:
        def _platform(row_map: dict, iid: str) -> str:
            vurl = row_map.get(iid, {}).get("video_url", "")
            if "instagram" in vurl: return "instagram"
            if "youtube" in vurl:   return "youtube"
            return "tiktok"

        row_map = {r["influencer_id"]: r for r in valid}
        master_rows = [
            {"influencer_id": iid, "platform": _platform(row_map, iid), "apify_status": "done"}
            for iid in missing
        ]
        for i in range(0, len(master_rows), CHUNK):
            try:
                sb.table("influencer_master").upsert(
                    master_rows[i:i + CHUNK], on_conflict="influencer_id"
                ).execute()
            except Exception as e:
                errors.append(f"influencer_master 등록 오류: {e}")

    # 같은 배치 안에서 video_url 중복 제거 (마지막 행 우선)
    deduped_map: dict[str, dict] = {}
    for r in valid:
        deduped_map[r["video_url"]] = r
    deduped = list(deduped_map.values())

    upserted = 0
    for i in range(0, len(deduped), CHUNK):
        chunk = deduped[i:i + CHUNK]
        try:
            sb.table("koc_contents").upsert(chunk, on_conflict="video_url").execute()
            upserted += len(chunk)
        except Exception as e:
            errors.append(f"청크 {i}~{i+len(chunk)}: {e}")
    return upserted, errors


def get_campaign_participants_info(campaign_id: str, brand_id: str) -> list[dict]:
    """캠페인에 등록된 참여자 목록 + influencer_master 표시 이름."""
    campaign = get_campaign_if_owned(campaign_id, brand_id)
    if not campaign:
        return []
    sel_res = (
        get_supabase()
        .table("campaign_selections")
        .select("id, influencer_id, status")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    selections = sel_res.data or []
    inf_ids = [s["influencer_id"] for s in selections if s.get("influencer_id")]
    inf_map: dict = {}
    if inf_ids:
        inf_res = (
            get_supabase()
            .table("influencer_master")
            .select("influencer_id, account_url, platform")
            .in_("influencer_id", inf_ids)
            .execute()
        )
        inf_map = {i["influencer_id"]: i for i in (inf_res.data or [])}
    for s in selections:
        inf = inf_map.get(s.get("influencer_id") or "", {})
        s["display_name"] = inf.get("account_url") or s.get("influencer_id") or ""
        s["inf_platform"] = inf.get("platform")
    return selections


# ── Apify 자동 트래킹 (Placeholder) ──────────────────────────────────────────

def fetch_metrics_from_apify(post_url: str, platform: str) -> dict | None:
    """Apify에서 게시물 성과 지표를 가져옵니다. (현재 미구현 placeholder)

    향후 구현 방향:
      - platform == 'tiktok'  → actor: clockworks/tiktok-scraper
      - platform == 'instagram' → actor: apify/instagram-scraper
      returns: {views, likes, comments, saves, shares} or None
    """
    # TODO: Implement Apify integration
    # from apify_client import ApifyClient
    # client = ApifyClient(os.environ.get("APIFY_TOKEN"))
    # actor_id = "clockworks/tiktok-scraper" if platform == "tiktok" else "apify/instagram-scraper"
    # run = client.actor(actor_id).call(run_input={"directUrls": [post_url], "maxItems": 1})
    # items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    # if not items: return None
    # item = items[0]
    # return {"views": item.get("playCount",0), "likes": item.get("likesCount",0), ...}
    return None


def refresh_post_metrics(post_id: str, brand_id: str) -> bool:
    """단일 게시물 지표를 Apify로 갱신합니다. (현재 미구현 placeholder)"""
    post = get_campaign_post_by_id(post_id, brand_id)
    if not post:
        return False
    metrics = fetch_metrics_from_apify(post["post_url"], post["platform"])
    if not metrics:
        return False
    metrics["last_tracked_at"] = _now()
    return update_campaign_post(post_id, brand_id, metrics)


def refresh_campaign_posts(campaign_id: str, brand_id: str) -> int:
    """캠페인의 모든 게시물 지표를 Apify로 갱신합니다. (현재 미구현 placeholder)
    Returns: 갱신된 게시물 수"""
    posts = get_campaign_posts(brand_id=brand_id, campaign_id=campaign_id)
    count = 0
    for post in posts:
        if refresh_post_metrics(post["id"], brand_id):
            count += 1
    return count


# ── Google Sheet 데이터 마이그레이션 ─────────────────────────────────────────

def migrate_google_sheet_rows(
    campaign_id: str,
    brand_id: str,
    rows: list[dict],
    overwrite: bool = False,
    participant_count: int | None = None,
    force_participant_count: bool = False,
    progress_callback=None,  # callable(current: int, total: int, name: str)
) -> tuple[int, list[str]]:
    """Google Sheet 형식의 rows를 campaign_posts로 이관합니다.

    row 형식 (플랫폼별 지표 분리):
        name         : 인플루언서 표시 이름
        ig_url       : Instagram 게시물 URL
        tt_url       : TikTok 게시물 URL
        x_url        : X(트위터) 게시물 URL
        lips_url     : LIPS 등 기타 플랫폼 URL
        upload_day   : 업로드 날짜 (YYYY/MM/DD 또는 YYYY-MM-DD)
        tt_*/ig_*/x_*/other_* : 플랫폼별 지표 (views/likes/comments/saves/shares)
        views/likes/... : 단일 지표 (하위 호환, tt_ 없을 때 TikTok에 적용)
    participant_count: 전체 발송 인원 수 (A열 전체 행수). 제공 시 campaigns에 저장.
    """
    import re
    campaign = get_campaign_if_owned(campaign_id, brand_id)
    if not campaign:
        return 0, ["캠페인을 찾을 수 없거나 접근 권한이 없습니다."]

    def _parse_date(val: str) -> str | None:
        if not val:
            return None
        val = str(val).strip()
        val = re.sub(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", r"\1-\2-\3", val)
        try:
            from datetime import datetime as _dt
            return str(_dt.strptime(val, "%Y-%m-%d").date())
        except Exception:
            return None

    def _int(v) -> int:
        try:
            s = str(v).strip()
            return int(float(s)) if s and s.lower() not in ("", "nan", "none", "-") else 0
        except Exception:
            return 0

    def _clean_url(u: str) -> str:
        u = str(u or "").strip()
        return "" if u.lower() in ("nan", "none", "-") else u

    # 헤더 행으로 판단해 건너뛸 이름 목록
    _HEADER_NAMES = {
        "name", "full name", "인플루언서", "인플루언서명", "influencer",
        "influencer_name", "이름", "계정", "아이디", "id",
    }

    created = 0
    errors: list[str] = []

    total = len(rows)
    for i, row in enumerate(rows, 1):
        name = str(row.get("name") or "").strip()
        if progress_callback:
            try:
                progress_callback(i, total, name or f"Row {i}")
            except Exception:
                pass
        if not name:
            errors.append(f"Row {i}: 인플루언서명 누락 → 건너뜀")
            continue
        if name.lower() in _HEADER_NAMES:
            errors.append(f"Row {i}: 헤더 행으로 판단 → 건너뜀 ({name})")
            continue

        ig_url   = _clean_url(row.get("ig_url", ""))
        tt_url   = _clean_url(row.get("tt_url", ""))
        x_url    = _clean_url(row.get("x_url", ""))
        lips_url = _clean_url(row.get("lips_url", ""))

        if not ig_url and not tt_url and not x_url and not lips_url:
            errors.append(f"Row {i} ({name}): URL 없음 → 건너뜀")
            continue

        upload_date = _parse_date(str(row.get("upload_day") or ""))

        # TikTok 지표: tt_* 컬럼 우선, 없으면 공통 컬럼 fallback
        tt_metrics = {
            "views":    _int(row.get("tt_views")    or row.get("views")),
            "likes":    _int(row.get("tt_likes")    or row.get("likes")),
            "comments": _int(row.get("tt_comments") or row.get("comments")),
            "saves":    _int(row.get("tt_saves")    or row.get("saves")),
            "shares":   _int(row.get("tt_shares")   or row.get("shares")),
        }
        # Instagram 지표: ig_* 컬럼 우선
        has_ig_specific = any(row.get(k) for k in ("ig_views", "ig_likes", "ig_comments", "ig_saves"))
        ig_metrics = {
            "views":    _int(row.get("ig_views")),
            "likes":    _int(row.get("ig_likes")),
            "comments": _int(row.get("ig_comments")),
            "saves":    _int(row.get("ig_saves")),
            "shares":   _int(row.get("ig_shares")),
        }
        # IG URL만 있고 ig_* 컬럼도 없으면 공통/tt_* 지표를 IG에 적용
        # (UI에서 "Views" 컬럼이 tt_views로 매핑되므로 tt_* fallback도 확인)
        if ig_url and not tt_url and not has_ig_specific:
            ig_metrics = {
                "views":    _int(row.get("views")    or row.get("tt_views")),
                "likes":    _int(row.get("likes")    or row.get("tt_likes")),
                "comments": _int(row.get("comments") or row.get("tt_comments")),
                "saves":    _int(row.get("saves")    or row.get("tt_saves")),
                "shares":   _int(row.get("shares")   or row.get("tt_shares")),
            }
        # X 지표: x_* 컬럼 우선, X만 있고 x_* 없으면 공통 지표 fallback (3순위)
        has_x_specific = any(row.get(k) for k in ("x_views", "x_likes", "x_comments"))
        x_metrics = {
            "views":    _int(row.get("x_views")),
            "likes":    _int(row.get("x_likes")),
            "comments": _int(row.get("x_comments")),
            "saves":    _int(row.get("x_saves")),
            "shares":   _int(row.get("x_shares")),
        }
        if x_url and not tt_url and not ig_url and not has_x_specific:
            x_metrics = {
                "views":    _int(row.get("views")    or row.get("tt_views")),
                "likes":    _int(row.get("likes")    or row.get("tt_likes")),
                "comments": _int(row.get("comments") or row.get("tt_comments")),
                "saves":    _int(row.get("saves")    or row.get("tt_saves")),
                "shares":   _int(row.get("shares")   or row.get("tt_shares")),
            }

        # 기타(LIPS 등) 지표: other_* 컬럼 우선, 기타만 있고 없으면 공통 지표 fallback (4순위)
        has_other_specific = any(row.get(k) for k in ("other_views", "other_likes", "lips_views"))
        other_metrics = {
            "views":    _int(row.get("other_views") or row.get("lips_views")),
            "likes":    _int(row.get("other_likes") or row.get("lips_likes")),
            "comments": _int(row.get("other_comments") or row.get("lips_comments")),
            "saves":    _int(row.get("other_saves")  or row.get("lips_saves")),
            "shares":   _int(row.get("other_shares") or row.get("lips_shares")),
        }
        if lips_url and not tt_url and not ig_url and not x_url and not has_other_specific:
            other_metrics = {
                "views":    _int(row.get("views")    or row.get("tt_views")),
                "likes":    _int(row.get("likes")    or row.get("tt_likes")),
                "comments": _int(row.get("comments") or row.get("tt_comments")),
                "saves":    _int(row.get("saves")    or row.get("tt_saves")),
                "shares":   _int(row.get("shares")   or row.get("tt_shares")),
            }

        to_create: list[dict] = []
        if tt_url:
            to_create.append({"platform": "tiktok",    "post_url": tt_url,   **tt_metrics})
        if ig_url:
            to_create.append({"platform": "instagram", "post_url": ig_url,   **ig_metrics})
        if x_url:
            to_create.append({"platform": "x",         "post_url": x_url,    **x_metrics})
        if lips_url:
            to_create.append({"platform": "other",     "post_url": lips_url, **other_metrics})

        for post_data in to_create:
            existing = (
                get_supabase()
                .table("campaign_posts")
                .select("id")
                .eq("post_url", post_data["post_url"])
                .execute()
            ).data
            if existing:
                if overwrite:
                    ok = update_campaign_post(existing[0]["id"], brand_id, {
                        "influencer_name": name,
                        "upload_date":     upload_date,
                        **{k: v for k, v in post_data.items() if k != "post_url"},
                    })
                    if ok:
                        created += 1
                    else:
                        errors.append(f"Row {i} ({name}): 업데이트 실패 ({post_data['post_url'][:60]})")
                else:
                    errors.append(f"Row {i} ({name}): URL 중복 → 건너뜀 ({post_data['post_url'][:60]})")
                continue
            result = create_campaign_post(brand_id, {
                "campaign_id":     campaign_id,
                "influencer_name": name,
                "upload_date":     upload_date,
                **post_data,
            })
            if result:
                created += 1
            else:
                errors.append(f"Row {i} ({name}): DB 저장 실패 ({post_data['platform']})")

    # 발송 인원 수 campaigns 테이블에 저장
    # force_participant_count=True(수동 입력)면 항상 업데이트, 아니면 기존 값보다 클 때만
    if participant_count is not None:
        existing_count = (campaign or {}).get("participant_count") or 0
        if force_participant_count or participant_count > existing_count:
            get_supabase().table("campaigns").update({
                "participant_count": participant_count,
                "updated_at": _now(),
            }).eq("id", campaign_id).execute()

    return created, errors


# ── post_comments ────────────────────────────────────────────────────────────

def get_post_comments(aweme_id: str | None = None, post_url: str | None = None) -> list[dict]:
    """TikTok aweme_id 또는 Instagram post_url로 댓글 조회 (좋아요 순)."""
    q = (
        get_supabase()
        .table("post_comments")
        .select("id, text, created_at, like_count, reply_count, language, platform, "
                "username, display_name, avatar_url, user_region, user_language")
        .order("like_count", desc=True)
        .limit(300)
    )
    if aweme_id:
        q = q.eq("aweme_id", aweme_id)
    elif post_url:
        # 쿼리파라미터 제거 후 정규화
        _norm = post_url.split("?")[0].rstrip("/")
        q = q.like("post_url", f"%{_norm}%")
    else:
        return []
    return q.execute().data or []


def bulk_upsert_post_comments(rows: list[dict]) -> tuple[int, list[str]]:
    """post_comments 일괄 upsert (id 충돌 시 업데이트)."""
    if not rows:
        return 0, []
    errors: list[str] = []
    created = 0
    CHUNK = 200
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i : i + CHUNK]
        try:
            get_supabase().table("post_comments").upsert(chunk, on_conflict="id").execute()
            created += len(chunk)
        except Exception as e:
            errors.append(str(e))
    return created, errors
