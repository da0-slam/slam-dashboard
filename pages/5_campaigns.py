import io
import re
import requests
import pandas as pd
import streamlit as st
from utils.auth import require_auth, sidebar_user_info, get_active_brand_id
import os
from utils.supabase_client import (
    get_brands, get_brand_by_id, get_influencers,
    get_campaigns, create_campaign, update_campaign, delete_campaign,
    get_campaign_selections, update_campaign_selection, remove_campaign_selection,
    update_selection_note, get_note_counts,
    get_influencer_thumbnails, get_influencer_contents, get_user_profile,
    get_campaign_if_owned, get_brand_access_password_hash,
    set_brand_access_password, verify_password,
    bulk_add_to_campaign, update_influencer_cover,
    get_or_create_invite_token, get_campaign_by_invite_token,
)
from utils.notes_ui import show_notes_dialog

st.set_page_config(page_title="캠페인 관리", page_icon="📋", layout="wide")
user = require_auth()
sidebar_user_info()

# ─── 초대링크 처리 (페이지 로드 시 invite 쿼리 파라미터 확인) ────────────────────
_invite_token = st.query_params.get("invite")
if _invite_token:
    _inv_camp = get_campaign_by_invite_token(_invite_token)
    if _inv_camp:
        # 초대 토큰으로 해당 브랜드 접근 자동 허용
        st.session_state[f"brand_access_{_inv_camp['brand_id']}"] = True
        # 해당 캠페인 바로 열기
        if not st.session_state.get("selected_campaign"):
            st.session_state.selected_campaign = _inv_camp
        st.query_params.clear()
        st.rerun()

st.title("📋 캠페인 관리")

# ─── 사용자 프로필 및 브랜드 확인 ────────────────────────────────────────────
profile       = get_user_profile(user.id)
user_brand_id = get_active_brand_id(profile)
user_role     = profile.get("role", "brand_user")
is_admin      = user_role == "admin"

if not user_brand_id and not is_admin:
    st.error("브랜드 계정이 연결되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

# ─── 브랜드 선택 (관리자: 전체 목록 / 일반 사용자: 본인 브랜드만) ─────────────
if is_admin:
    brands = get_brands()
    if not brands:
        st.warning("먼저 브랜드사를 등록하세요.")
        st.stop()
    from collections import Counter
    _name_cnt    = Counter(b["name"] for b in brands)
    brand_options = {
        (f"{b['name']}  [{b['id'][:8]}]" if _name_cnt[b["name"]] > 1 else b["name"]): b["id"]
        for b in brands
    }
    selected_brand_label = st.selectbox("브랜드사", list(brand_options.keys()))
    selected_brand_id    = brand_options[selected_brand_label]
    selected_brand_name  = selected_brand_label.split("  [")[0]
else:
    brand = get_brand_by_id(user_brand_id)
    if not brand:
        st.error("브랜드 정보를 불러올 수 없습니다.")
        st.stop()
    selected_brand_id   = user_brand_id
    selected_brand_name = brand.get("name", "")
    st.caption(f"브랜드사: **{selected_brand_name}**")

st.divider()

# ─── 선택된 캠페인이 현재 브랜드 소속인지 사전 검증 ──────────────────────────
# 관리자가 브랜드를 전환하거나 세션 값이 오염된 경우 초기화
if st.session_state.get("selected_campaign"):
    if st.session_state.selected_campaign.get("brand_id") != selected_brand_id:
        st.session_state.selected_campaign = None

# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.koc-mini{position:relative;border-radius:10px;overflow:hidden;background:#111;aspect-ratio:9/16;}
.koc-mini img{width:100%;height:100%;object-fit:cover;display:block;}
.koc-mini-ph{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
             font-size:2rem;background:#1a1a2e;}
.koc-mini .g{position:absolute;top:6px;left:6px;border-radius:5px;padding:2px 7px;
             color:#fff;font-weight:700;font-size:12px;}
.koc-mini .r{position:absolute;top:6px;right:6px;background:rgba(0,0,0,.65);
             border-radius:5px;padding:2px 7px;color:#fff;font-size:11px;}
.koc-mini .info{position:absolute;bottom:0;left:0;right:0;
                background:linear-gradient(transparent,rgba(0,0,0,.8));padding:14px 8px 8px;}
.koc-mini .n{color:#fff;font-weight:700;font-size:12px;margin:0;}
.koc-mini .s{color:rgba(255,255,255,.8);font-size:10px;margin:2px 0 0;}
.grade-s{background:#FF6B2C;} .grade-a{background:#3B82F6;}
.grade-b{background:#6B7280;} .grade-c{background:#374151;}
</style>
""", unsafe_allow_html=True)

STATUS_COLOR = {"candidate": "🟡", "confirmed": "🟢", "rejected": "🔴"}
STATUS_LABEL = {"candidate": "후보",  "confirmed": "확정",  "rejected": "제외"}
CAMP_STATUS  = {"draft": "⚫ 준비중", "active": "🟢 진행중", "closed": "⚪ 종료"}
GRADE_CSS    = {"S": "grade-s", "A": "grade-a", "B": "grade-b", "C": "grade-c"}


def _fmt(n):
    n = n or 0
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(n)




_PLAT_LABEL = {"tiktok": "🎵 TikTok", "instagram": "📸 Instagram", "youtube": "▶ YouTube", "other": "기타"}
_PLAT_ICON  = {"tiktok": "🎵", "instagram": "📸", "youtube": "▶", "other": "🔗"}


def _render_content_grid(items: list[dict]):
    COLS = 4
    for chunk in range(0, len(items), COLS):
        row_items = items[chunk:chunk + COLS]
        cols = st.columns(COLS)
        for col, c in zip(cols, row_items):
            thumb     = c.get("thumbnail_url") or ""
            video_url = c.get("video_url") or ""
            play      = c.get("play_count") or 0
            with col:
                if thumb and video_url:
                    st.markdown(
                        f'<a href="{video_url}" target="_blank">'
                        f'<img src="{thumb}" style="width:100%;border-radius:8px;aspect-ratio:9/16;object-fit:cover;display:block;"></a>',
                        unsafe_allow_html=True,
                    )
                elif thumb:
                    st.image(thumb, use_container_width=True)
                else:
                    st.markdown(
                        '<div style="aspect-ratio:9/16;background:#1a1a2e;border-radius:8px;'
                        'display:flex;align-items:center;justify-content:center;font-size:2rem;">🎬</div>',
                        unsafe_allow_html=True,
                    )
                st.caption(f"▶ {_fmt(play)}")


def _fetch_missing_koc_thumbnails(camp_id: str) -> tuple[int, int]:
    """캠페인 인플루언서의 koc_contents 중 Supabase 썸네일 없는 항목 수집. (ok, fail) 반환."""
    import time
    from utils.storage_client import fetch_and_upload_thumbnail, extract_post_id
    sb = __import__("utils.supabase_client", fromlist=["get_supabase"]).get_supabase()

    sels = sb.table("campaign_selections").select("influencer_id").eq("campaign_id", camp_id).execute().data or []
    inf_ids = [s["influencer_id"] for s in sels]
    if not inf_ids:
        return 0, 0

    # Supabase 썸네일 없는 koc_contents 항목 수집
    rows = sb.table("koc_contents").select("influencer_id,video_url,thumbnail_url").in_("influencer_id", inf_ids).execute().data or []
    targets = [r for r in rows if "supabase" not in (r.get("thumbnail_url") or "")]
    if not targets:
        return 0, 0

    ok = fail = 0
    for r in targets:
        vurl = r.get("video_url") or ""
        iid  = r["influencer_id"]
        post_id = extract_post_id(vurl)
        if not post_id:
            fail += 1
            continue
        try:
            saved = fetch_and_upload_thumbnail(vurl, iid, post_id)
            if saved:
                sb.table("koc_contents").update({"thumbnail_url": saved}).eq("influencer_id", iid).eq("video_url", vurl).execute()
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        time.sleep(3 if "instagram.com" in vurl else 0.5)
    return ok, fail


def _fetch_missing_covers(camp_id: str) -> tuple[int, int]:
    """캠페인 내 cover_url 없는 인플루언서 썸네일 수집. (ok, fail) 반환."""
    from utils.storage_client import fetch_and_upload_thumbnail, extract_post_id
    sb = __import__("utils.supabase_client", fromlist=["get_supabase"]).get_supabase()

    sels = sb.table("campaign_selections").select("influencer_id").eq("campaign_id", camp_id).execute().data or []
    inf_ids = [s["influencer_id"] for s in sels]
    if not inf_ids:
        return 0, 0

    masters = sb.table("influencer_master").select("influencer_id,cover_url").in_("influencer_id", inf_ids).execute().data or []
    targets = [m["influencer_id"] for m in masters if not m.get("cover_url")]
    if not targets:
        return 0, 0

    ok = fail = 0
    for iid in targets:
        # 1순위: koc_contents에 Supabase 썸네일 있으면 재사용
        koc_rows = sb.table("koc_contents").select("video_url,thumbnail_url").eq("influencer_id", iid).limit(10).execute().data or []
        reuse = next((r["thumbnail_url"] for r in koc_rows if r.get("thumbnail_url") and "supabase" in r["thumbnail_url"]), None)
        if reuse:
            sb.table("influencer_master").update({"cover_url": reuse}).eq("influencer_id", iid).execute()
            ok += 1
            continue
        # 2순위: video_url에서 스크랩
        scraped = None
        import time
        for row in koc_rows:
            vurl = row.get("video_url", "")
            post_id = extract_post_id(vurl)
            if not post_id:
                continue
            try:
                saved = fetch_and_upload_thumbnail(vurl, iid, post_id)
                if saved:
                    scraped = saved
                    break
            except Exception:
                pass
            time.sleep(3 if "instagram.com" in vurl else 0.5)
        if scraped:
            sb.table("influencer_master").update({"cover_url": scraped}).eq("influencer_id", iid).execute()
            ok += 1
        else:
            fail += 1
    return ok, fail


@st.dialog("대표 썸네일 선택", width="large")
def pick_thumbnail_dialog(influencer_id: str):
    st.caption(f"@{influencer_id} — 카드에 보여줄 게시물을 선택하세요")
    contents = get_influencer_contents(influencer_id)
    if not contents:
        st.info("등록된 콘텐츠가 없습니다.")
        return

    COLS = 4
    for idx, c in enumerate(contents):
        col_idx = idx % COLS
        if col_idx == 0:
            cols = st.columns(COLS)
        thumb = c.get("thumbnail_url") or ""
        play  = c.get("play_count") or 0
        with cols[col_idx]:
            if thumb:
                st.image(thumb, use_container_width=True)
            else:
                st.markdown(
                    '<div style="aspect-ratio:9/16;background:#1a1a2e;border-radius:8px;'
                    'display:flex;align-items:center;justify-content:center;font-size:2rem;">🎬</div>',
                    unsafe_allow_html=True,
                )
            st.caption(f"▶ {_fmt(play)}")
            if thumb and st.button("✅ 대표로 설정", key=f"pick_{influencer_id}_{idx}", use_container_width=True):
                update_influencer_cover(influencer_id, thumb)
                # session_state에 즉시 저장 → DB 조회 지연과 무관하게 반영
                st.session_state[f"_cover_{influencer_id}"] = thumb
                st.rerun()


@st.dialog("콘텐츠 전체보기", width="large")
def show_contents_dialog(influencer_id: str):
    st.caption(f"@{influencer_id}")
    contents = get_influencer_contents(influencer_id)
    if not contents:
        st.info("등록된 콘텐츠 데이터가 없습니다.")
        return

    # 플랫폼별 분류
    by_plat: dict[str, list] = {}
    for c in contents:
        p = c.get("platform", "other")
        by_plat.setdefault(p, []).append(c)

    plat_order = [p for p in ["tiktok", "instagram", "youtube", "other"] if p in by_plat]

    if len(plat_order) > 1:
        tab_labels = [f"{_PLAT_LABEL.get(p, p)} ({len(by_plat[p])})" for p in plat_order]
        tabs = st.tabs(tab_labels)
        for tab, plat in zip(tabs, plat_order):
            with tab:
                _render_content_grid(by_plat[plat])
    else:
        _render_content_grid(contents)


# ═══════════════════════════════════════════════════════════════════════════════
# 캠페인 상세 뷰
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.get("selected_campaign"):
    camp    = st.session_state.selected_campaign
    camp_id = camp["id"]

    # ── Step 1: DB에서 소유권 재확인 (세션·URL 조작 방어) ────────────────────
    verified_camp = get_campaign_if_owned(camp_id, selected_brand_id)
    if not verified_camp:
        st.error("접근 권한이 없는 캠페인입니다.")
        st.session_state.selected_campaign = None
        st.stop()

    # ── Step 2: 상세 화면 렌더링 ─────────────────────────────────────────────
    camp = verified_camp  # DB에서 재확인된 데이터 사용

    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← 목록"):
            st.session_state.selected_campaign = None
            st.session_state.pop("_invite_url", None)
            st.rerun()
    with col_title:
        st.subheader(f"📌 {camp['name']}  {CAMP_STATUS.get(camp['status'], '')}")

    with st.expander("⚙️ 캠페인 설정"):
        c1, c2 = st.columns(2)
        with c1:
            new_status = st.selectbox(
                "상태", ["draft", "active", "closed"],
                index=["draft", "active", "closed"].index(camp["status"]),
                format_func=lambda x: CAMP_STATUS[x],
            )
        with c2:
            new_name = st.text_input("캠페인명", value=camp["name"])
        if st.button("저장", type="primary"):
            update_campaign(camp["id"], {"name": new_name, "status": new_status})
            st.session_state.selected_campaign = {**camp, "name": new_name, "status": new_status}
            st.success("저장했습니다.")
            st.rerun()

    # ── 초대 링크 (항상 표시) ─────────────────────────────────────────────────
    _invite_key = f"_invite_url_{camp_id}"
    if not st.session_state.get(_invite_key):
        token = get_or_create_invite_token(camp_id)
        if token:
            site = os.environ.get("SITE_URL", "http://localhost:8501").rstrip("/")
            st.session_state[_invite_key] = f"{site}/campaigns?invite={token}"
    if st.session_state.get(_invite_key):
        with st.container(border=True):
            st.markdown("**🔗 초대 링크**")
            st.text_input(
                "팀원이 바로 접근할 수 있습니다.",
                value=st.session_state[_invite_key],
                key=f"invite_display_{camp_id}",
            )

    with st.expander("📥 인플루언서 일괄 등록 (CSV)"):
        st.markdown("""
**CSV 형식 안내** — 헤더 행 필수. Google Sheet에서 그대로 내보내도 됩니다.

| influencer_id | status | followers | contact_email | ratecard | after_nego | usage_rights | platform_url | note |
|---|---|---|---|---|---|---|---|---|
| kelseyohcriner | confirmed | 66300 | kelsey@gmail.com | $700/video | $500 | organic only | tiktok.com/@kelseyohcriner | |

- `influencer_id` (필수): TikTok/IG 유저명 (`@` 제외). Google Sheet의 `Influencer ID` 컬럼 그대로 사용 가능.
- `status`: `candidate` / `confirmed` / `rejected` / `agree` / `nego` (생략 시 `candidate`)
- 나머지 컬럼은 모두 선택사항이며, Google Sheet 원본 컬럼명도 자동 인식합니다.
- 이미 등록된 인플루언서는 자동으로 건너뜁니다.
""")

        sheet_url = st.text_input(
            "Google Sheet URL 붙여넣기 (링크 공유된 시트)",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key=f"sheet_url_{camp_id}",
        )

        _csv_bytes = None
        if sheet_url and sheet_url.startswith("https://docs.google.com/spreadsheets"):
            _m = re.search(r"/spreadsheets/d/([^/]+)", sheet_url)
            _gid = re.search(r"[#&?]gid=(\d+)", sheet_url)
            if _m:
                _sid  = _m.group(1)
                _gid  = _gid.group(1) if _gid else "0"
                _csv_url = f"https://docs.google.com/spreadsheets/d/{_sid}/export?format=csv&gid={_gid}"
                try:
                    with st.spinner("시트 불러오는 중..."):
                        _resp = requests.get(_csv_url, timeout=15)
                    if _resp.status_code == 200:
                        _csv_bytes = _resp.content
                        st.success("시트 불러오기 완료")
                    else:
                        st.error(f"불러오기 실패 ({_resp.status_code}). 시트 공유 설정을 확인하세요.")
                except Exception as _e:
                    st.error(f"네트워크 오류: {_e}")
            else:
                st.warning("올바른 Google Sheets URL이 아닙니다.")

        st.caption("또는 CSV 파일 직접 업로드")
        uploaded_csv = st.file_uploader("CSV 파일 업로드", type=["csv"], key=f"bulk_csv_{camp_id}")
        if uploaded_csv:
            _csv_bytes = uploaded_csv.getvalue()

        if _csv_bytes:
            try:
                df_csv = pd.read_csv(io.StringIO(_csv_bytes.decode("utf-8-sig")))
                df_csv.columns = [c.strip().lower() for c in df_csv.columns]

                def _find_col(candidates):
                    return next((c for c in df_csv.columns if any(k in c for k in candidates)), None)

                # 컬럼명 유연하게 인식 (Google Sheet 원본명 포함)
                # "tiktok" 단독은 tiktok_url 컬럼도 매칭하므로 제외, tiktok_id만 허용
                _explicit_id_col = _find_col(["influencer_id", "influencer id", "username", "tiktok_id", "유저명", "아이디"])
                id_col           = _explicit_id_col or df_csv.columns[0]
                status_col  = _find_col(["status"])
                note_col    = _find_col(["note", "memo", "메모"])
                follow_col  = _find_col(["follower"])
                # "Contact DM TT"(체크박스)보다 순수 "contact" 또는 email 컬럼 우선
                contact_col = (
                    next((c for c in df_csv.columns if c in ("contact", "email", "contact email", "컨택", "이메일")), None)
                    or next((c for c in df_csv.columns if "email" in c), None)
                    or next((c for c in df_csv.columns if "contact" in c and "dm" not in c), None)
                )
                rate_col    = _find_col(["ratecard", "rate card", "rate"])
                nego_col    = _find_col(["after nego", "after_nego", "nego"])
                usage_col   = _find_col(["usage"])
                # 플랫폼별 URL 컬럼 (Instagram 팔로워보다 먼저 정의해야 충돌 없음)
                tt_url_col  = _find_col(["tiktok_url", "tiktok url", "tt_url"])
                ig_fol_col  = _find_col(["instagram_f", "instagram_followers", "ig_followers"])
                ig_url_col  = _find_col(["instagram_l", "instagram_url", "ig_url"])
                url_col     = _find_col(["url"]) if not tt_url_col else None  # tt_url_col 있으면 url_col 불필요

                # "agree"는 인플루언서가 협업 의향 표시일 뿐 → 캠페인 내 상태는 후보로 시작
                _STATUS_MAP = {"confirmed": "confirmed", "rejected": "rejected", "nego": "candidate", "negotiating": "candidate"}

                def _clean(val):
                    s = str(val).strip() if val is not None else ""
                    return "" if s.lower() in ("nan", "none", "") else s

                def _followers(val):
                    s = _clean(val).replace(",", "").replace("K", "000").replace("k", "000").replace("M", "000000").replace("m", "000000")
                    try:
                        return int(float(s))
                    except Exception:
                        return None

                entries = []
                for _, row in df_csv.iterrows():
                    iid = str(row.get(id_col) or "").strip().lstrip("@")
                    # 명시적 username 컬럼이 없거나, 값이 비어있거나 URL/공백 포함이면
                    # → TikTok URL에서 @username 추출 시도
                    if tt_url_col and (
                        not _explicit_id_col
                        or not iid or iid.lower() in ("nan", "none", "")
                        or iid.startswith("http") or " " in iid
                    ):
                        tt_val = _clean(row.get(tt_url_col, ""))
                        m = re.search(r'tiktok\.com/@([\w.]+)', tt_val)  # @ 필수 — 단축URL(/t/xxx) 오추출 방지
                        if m:
                            iid = m.group(1)
                    if not iid or iid.lower() in ("nan", "none", ""):
                        continue

                    raw_status = _clean(row[status_col]) if status_col else ""
                    status = _STATUS_MAP.get(raw_status.lower(), raw_status)
                    if status not in ("candidate", "confirmed", "rejected"):
                        status = "candidate"

                    _tt_url = _clean(row[tt_url_col]) if tt_url_col else ""
                    _url    = _clean(row[url_col])    if url_col    else ""

                    entries.append({
                        "influencer_id":      iid,
                        "status":             status,
                        "note":               _clean(row[note_col])    if note_col    else "",
                        "followers":          _followers(row[follow_col]) if follow_col else None,
                        "contact_email":      _clean(row[contact_col]) if contact_col else "",
                        "ratecard":           _clean(row[rate_col])    if rate_col    else "",
                        "after_nego":         _clean(row[nego_col])    if nego_col    else "",
                        "usage_rights":       _clean(row[usage_col])   if usage_col   else "",
                        "platform_url":       _tt_url or _url,
                        "instagram_url":      _clean(row[ig_url_col])  if ig_url_col  else "",
                        "instagram_followers": _followers(row[ig_fol_col]) if ig_fol_col else None,
                    })

                if not entries:
                    st.warning("유효한 influencer_id 행이 없습니다.")
                else:
                    st.markdown(f"**미리보기** — {len(entries)}명")
                    st.dataframe(
                        pd.DataFrame(entries).head(10),
                        use_container_width=True, hide_index=True,
                    )

                    if st.button(f"✅ {len(entries)}명 캠페인에 추가", key=f"bulk_run_{camp_id}", type="primary"):
                        with st.spinner("등록 중..."):
                            added, skipped, errs = bulk_add_to_campaign(camp_id, entries)
                        st.success(f"등록 완료: **{added}명** 추가, {skipped}명 중복 건너뜀")
                        if errs:
                            with st.expander(f"오류 {len(errs)}건"):
                                for e in errs:
                                    st.warning(e)
                        st.rerun()

            except Exception as ex:
                st.error(f"CSV 파싱 오류: {ex}")

    # ── 어드민: 썸네일 없는 인플루언서 일괄 수집 ─────────────────────────────────
    if is_admin:
        _ac1, _ac2 = st.columns(2)
        with _ac1:
            if st.button("🖼️ 프로필 썸네일 수집 (어드민)", key=f"fetch_covers_{camp_id}", use_container_width=True):
                with st.spinner("프로필 썸네일 수집 중..."):
                    _ok, _fail = _fetch_missing_covers(camp_id)
                if _ok + _fail == 0:
                    st.info("수집할 항목이 없습니다.")
                else:
                    st.success(f"완료: 성공 **{_ok}명** / 실패 {_fail}명")
                st.rerun()
        with _ac2:
            if st.button("🎬 콘텐츠 썸네일 수집 (어드민)", key=f"fetch_koc_thumb_{camp_id}", use_container_width=True):
                with st.spinner("콘텐츠 썸네일 수집 중... (영상 수에 따라 시간이 걸릴 수 있습니다)"):
                    _ok, _fail = _fetch_missing_koc_thumbnails(camp_id)
                if _ok + _fail == 0:
                    st.info("수집할 항목이 없습니다.")
                else:
                    st.success(f"완료: 성공 **{_ok}건** / 실패 {_fail}건")
                st.rerun()

    st.divider()

    # ── Undo 배너 ─────────────────────────────────────────────────────────────
    _undo_key = f"_undo_{camp_id}"
    if st.session_state.get(_undo_key):
        _ud = st.session_state[_undo_key]
        _ua, _ub, _uc = st.columns([5, 1, 1])
        with _ua:
            st.warning(f"🗑️ **@{_ud['influencer_id']}** 삭제됨")
        with _ub:
            if st.button("실행 취소", key=f"undo_btn_{camp_id}", use_container_width=True, type="primary"):
                bulk_add_to_campaign(camp_id, [{
                    "influencer_id": _ud["influencer_id"],
                    "status":        _ud["status"],
                    "followers":     _ud.get("followers"),
                    "contact_email": _ud.get("contact_email", ""),
                    "ratecard":      _ud.get("ratecard", ""),
                    "after_nego":    _ud.get("after_nego", ""),
                    "usage_rights":  _ud.get("usage_rights", ""),
                    "platform_url":  _ud.get("platform_url", ""),
                    "note":          _ud.get("note", ""),
                }])
                del st.session_state[_undo_key]
                st.rerun()
        with _uc:
            if st.button("닫기", key=f"undo_close_{camp_id}", use_container_width=True):
                del st.session_state[_undo_key]
                st.rerun()

    selections    = get_campaign_selections(camp["id"])
    inf_ids       = [s["influencer_id"] for s in selections]
    thumb_map     = get_influencer_thumbnails(inf_ids)
    inf_map       = {r["influencer_id"]: r for r in get_influencers(ids=inf_ids)}
    # pick_thumbnail_dialog에서 저장한 cover_url 즉시 반영 (DB 재조회 지연 우회)
    for _k in [k for k in st.session_state if k.startswith("_cover_")]:
        _iid = _k[len("_cover_"):]
        inf_map.setdefault(_iid, {})["cover_url"] = st.session_state.pop(_k)
    note_cnt_map  = get_note_counts(inf_ids, selected_brand_id)

    # ── 검색 + 플랫폼 필터 ─────────────────────────────────────────────────────
    sf1, sf2 = st.columns([3, 2])
    with sf1:
        _search = st.text_input(
            "인플루언서 검색", placeholder="@username",
            key=f"inf_search_{camp_id}", label_visibility="collapsed",
        )
    with sf2:
        _plat_filter = st.selectbox(
            "플랫폼", ["전체", "🎵 TikTok", "📸 Instagram"],
            key=f"plat_filter_{camp_id}", label_visibility="collapsed",
        )

    if _search:
        _q = _search.lstrip("@").lower()
        selections = [s for s in selections if _q in s["influencer_id"].lower()]
    if _plat_filter != "전체":
        _plat_kw = "tiktok" if "TikTok" in _plat_filter else "instagram"
        selections = [
            s for s in selections
            if _plat_kw in (thumb_map.get(s["influencer_id"], {}).get("platforms") or [])
            or _plat_kw in (inf_map.get(s["influencer_id"], {}).get("platform") or "").lower()
        ]

    view_col, _ = st.columns([2, 6])
    with view_col:
        view_mode = st.radio("보기", ["🔲 그리드", "📋 목록"], horizontal=True, label_visibility="collapsed")

    tab_all, tab_cand, tab_conf, tab_rej = st.tabs([
        f"전체 {len(selections)}",
        f"🟡 후보 {sum(1 for s in selections if s['status']=='candidate')}",
        f"🟢 확정 {sum(1 for s in selections if s['status']=='confirmed')}",
        f"🔴 제외 {sum(1 for s in selections if s['status']=='rejected')}",
    ])

    def render_selections(items, prefix):
        if not items:
            st.info("해당 항목이 없습니다.")
            return

        if "그리드" in view_mode:
            COLS = 5
            for chunk_start in range(0, len(items), COLS):
                row  = items[chunk_start:chunk_start + COLS]
                cols = st.columns(COLS)
                for col, item, rank in zip(cols, row, range(chunk_start + 1, chunk_start + COLS + 1)):
                    inf_id    = item["influencer_id"]
                    status    = item["status"]
                    inf       = inf_map.get(inf_id, {})
                    thumb     = thumb_map.get(inf_id, {})
                    thumbnail = inf.get("cover_url") or thumb.get("thumbnail") or ""
                    video_url = thumb.get("video_url", "")
                    # 플랫폼 아이콘: URL이 있으면 클릭 가능한 링크로, 없으면 텍스트 아이콘
                    _tt_url  = item.get("platform_url") or ""
                    _ig_url  = inf.get("instagram_url") or ""
                    _plat_html = ""
                    if _tt_url:
                        _plat_html += f'<a href="{_tt_url}" target="_blank" style="color:#fff;text-decoration:none;margin-right:4px;">🎵</a>'
                    if _ig_url:
                        _plat_html += f'<a href="{_ig_url}" target="_blank" style="color:#fff;text-decoration:none;margin-right:4px;">📸</a>'
                    if not _plat_html:
                        _plats = thumb.get("platforms") or ([inf.get("platform")] if inf.get("platform") else [])
                        _plat_html = "  ".join(_PLAT_ICON.get(p, p) for p in _plats) if _plats else ""
                    _img_inner = f'<img src="{thumbnail}">' if thumbnail else '<div class="koc-mini-ph">🎬</div>'
                    img_tag = (
                        f'<a href="{video_url}" target="_blank" style="display:block;width:100%;height:100%;">{_img_inner}</a>'
                        if video_url else _img_inner
                    )
                    with col:
                        st.markdown(f"""
<div class="koc-mini">
  {img_tag}
  <div class="g grade-b">{STATUS_COLOR[status]}</div>
  <div class="r">#{rank}</div>
  <div class="info">
    <p class="n">@{inf_id}</p>
    <p class="s">{_plat_html} {STATUS_LABEL[status]}</p>
  </div>
</div>
""", unsafe_allow_html=True)
                        if status == "confirmed":
                            b1, b2, b3 = st.columns(3)
                            with b1:
                                if st.button("후보", key=f"{prefix}_g_cand_{item['id']}", use_container_width=True):
                                    update_campaign_selection(item["id"], "candidate")
                                    st.rerun()
                            with b2:
                                if st.button("제외", key=f"{prefix}_g_rej_{item['id']}", use_container_width=True):
                                    update_campaign_selection(item["id"], "rejected")
                                    st.rerun()
                            with b3:
                                if st.button("삭제", key=f"{prefix}_g_rm_{item['id']}", use_container_width=True):
                                    st.session_state[f"_undo_{camp_id}"] = dict(item)
                                    remove_campaign_selection(item["id"])
                                    st.rerun()
                        else:
                            b1, b2 = st.columns(2)
                            next_s = {"candidate": "confirmed", "rejected": "candidate"}[status]
                            next_l = {"candidate": "확정", "rejected": "후보"}[status]
                            with b1:
                                if st.button(next_l, key=f"{prefix}_g_ns_{item['id']}", use_container_width=True):
                                    update_campaign_selection(item["id"], next_s)
                                    st.rerun()
                            with b2:
                                if st.button("삭제", key=f"{prefix}_g_rm_{item['id']}", use_container_width=True):
                                    st.session_state[f"_undo_{camp_id}"] = dict(item)
                                    remove_campaign_selection(item["id"])
                                    st.rerun()
                        if is_admin:
                            ba, bb, bc = st.columns(3)
                            with ba:
                                nc = note_cnt_map.get(inf_id, 0)
                                if st.button(f"💬 {nc}" if nc else "💬", key=f"{prefix}_g_note_{item['id']}", use_container_width=True):
                                    show_notes_dialog(inf_id, selected_brand_id, user.email, camp_id)
                            with bb:
                                if st.button("📷 전체", key=f"{prefix}_g_all_{item['id']}", use_container_width=True):
                                    show_contents_dialog(inf_id)
                            with bc:
                                if st.button("🖼️", key=f"{prefix}_g_thumb_{item['id']}", use_container_width=True, help="대표 썸네일 게시물 선택"):
                                    pick_thumbnail_dialog(inf_id)
                        else:
                            b3, b4 = st.columns(2)
                            with b3:
                                nc = note_cnt_map.get(inf_id, 0)
                                if st.button(f"💬 {nc}" if nc else "💬", key=f"{prefix}_g_note_{item['id']}", use_container_width=True):
                                    show_notes_dialog(inf_id, selected_brand_id, user.email, camp_id)
                            with b4:
                                if st.button("📷 전체", key=f"{prefix}_g_all_{item['id']}", use_container_width=True):
                                    show_contents_dialog(inf_id)
                        if is_admin and (item.get("ratecard") or item.get("after_nego")):
                            _p = "  →  ".join(filter(None, [item.get("ratecard"), item.get("after_nego")]))
                            st.caption(f"💰 {_p}")
        else:
            for item in items:
                inf_id    = item["influencer_id"]
                status    = item["status"]
                inf       = inf_map.get(inf_id, {})
                thumb     = thumb_map.get(inf_id, {})
                thumbnail = inf.get("cover_url") or thumb.get("thumbnail") or ""
                video_url = thumb.get("video_url", "")
                with st.container(border=True):
                    c1, c2, c3, c4, c5, c6 = st.columns([1, 4, 2, 1, 1, 1])
                    with c1:
                        if thumbnail:
                            try:
                                st.image(thumbnail, width=60)
                            except Exception:
                                st.markdown("🎬")
                        else:
                            st.markdown("🎬")
                    with c2:
                        st.markdown(f"{STATUS_COLOR[status]} **@{inf_id}** `{STATUS_LABEL[status]}`")
                        _purl  = item.get("platform_url") or ""
                        _igurl = inf.get("instagram_url") or ""
                        # 플랫폼별 클릭 가능한 아이콘 링크 (한 사람이 여러 SNS를 가질 수 있음)
                        _icon_links = []
                        if _purl:
                            _icon_links.append(f"[🎵 TikTok]({_purl})")
                        if _igurl:
                            _icon_links.append(f"[📸 Instagram]({_igurl})")
                        if not _icon_links and video_url:
                            _icon_links.append(f"[↗ 영상]({video_url})")
                        _fol = f"👥 {_fmt(item['followers'])}" if item.get("followers") else ""
                        st.caption("  ".join(filter(None, _icon_links + [_fol])))
                        _price_info = [
                            f"💰 {item['ratecard']}" if item.get("ratecard") else "",
                            f"→ {item['after_nego']}" if item.get("after_nego") else "",
                        ] if is_admin else []
                        _meta = "  |  ".join(filter(None, _price_info + [
                            item.get("usage_rights"),
                        ]))
                        if _meta:
                            st.caption(_meta)
                        if item.get("note"):
                            st.caption(f"📝 {item['note']}")
                    with c3:
                        if status == "confirmed":
                            la, lb = st.columns(2)
                            with la:
                                if st.button("후보", key=f"{prefix}_l_cand_{item['id']}", use_container_width=True):
                                    update_campaign_selection(item["id"], "candidate")
                                    st.rerun()
                            with lb:
                                if st.button("제외", key=f"{prefix}_l_rej_{item['id']}", use_container_width=True):
                                    update_campaign_selection(item["id"], "rejected")
                                    st.rerun()
                        else:
                            next_s = {"candidate": "confirmed", "rejected": "candidate"}[status]
                            next_l = {"candidate": "확정", "rejected": "후보로"}[status]
                            if st.button(next_l, key=f"{prefix}_l_ns_{item['id']}", use_container_width=True):
                                update_campaign_selection(item["id"], next_s)
                                st.rerun()
                    with c4:
                        nc = note_cnt_map.get(inf_id, 0)
                        if st.button(f"💬{nc}" if nc else "💬", key=f"{prefix}_l_note_{item['id']}", use_container_width=True, help="메모/댓글"):
                            show_notes_dialog(inf_id, selected_brand_id, user.email, camp_id)
                    with c5:
                        if st.button("삭제", key=f"{prefix}_l_rm_{item['id']}", use_container_width=True):
                            st.session_state[f"_undo_{camp_id}"] = dict(item)
                            remove_campaign_selection(item["id"])
                            st.rerun()
                    with c6:
                        if st.button("📷", key=f"{prefix}_l_all_{item['id']}", use_container_width=True, help="콘텐츠 전체보기"):
                            show_contents_dialog(inf_id)
                        if is_admin:
                            if st.button("🖼️", key=f"{prefix}_l_thumb_{item['id']}", use_container_width=True, help="대표 썸네일 선택"):
                                pick_thumbnail_dialog(inf_id)

    with tab_all:  render_selections(selections, "all")
    with tab_cand: render_selections([s for s in selections if s["status"] == "candidate"], "cand")
    with tab_conf: render_selections([s for s in selections if s["status"] == "confirmed"], "conf")
    with tab_rej:  render_selections([s for s in selections if s["status"] == "rejected"],  "rej")


# ═══════════════════════════════════════════════════════════════════════════════
# 캠페인 목록 뷰
# ═══════════════════════════════════════════════════════════════════════════════
else:
    # 로그인 유저의 brand_id 기준으로만 조회 — 다른 브랜드 캠페인은 DB 쿼리 자체에서 차단
    campaigns = get_campaigns(selected_brand_id)

    col_hd, col_btn = st.columns([6, 2])
    with col_hd:
        st.subheader(f"{selected_brand_name}의 캠페인")
    with col_btn:
        if st.button("＋ 새 캠페인", use_container_width=True, type="primary"):
            st.session_state.show_create = True

    if st.session_state.get("show_create"):
        with st.form("create_campaign_form"):
            camp_name = st.text_input("캠페인명 *", placeholder="예: brandslam 2025 Summer")
            camp_desc = st.text_area("설명", height=80)
            c1, c2 = st.columns(2)
            with c1:
                if st.form_submit_button("생성", type="primary", use_container_width=True):
                    if not camp_name:
                        st.error("캠페인명을 입력하세요.")
                    else:
                        # brand_id는 로그인 유저의 브랜드로 자동 설정 — 임의 변경 불가
                        create_campaign(selected_brand_id, camp_name, camp_desc)
                        st.session_state.show_create = False
                        st.rerun()
            with c2:
                if st.form_submit_button("취소", use_container_width=True):
                    st.session_state.show_create = False
                    st.rerun()

    st.divider()

    if not campaigns:
        st.info("아직 캠페인이 없습니다. 새 캠페인을 만들어보세요.")
    else:
        cols = st.columns(3)
        for i, camp in enumerate(campaigns):
            with cols[i % 3]:
                sels     = get_campaign_selections(camp["id"])
                cnt_all  = len(sels)
                cnt_conf = sum(1 for s in sels if s["status"] == "confirmed")
                with st.container(border=True):
                    st.markdown(f"### {camp['name']}")
                    st.caption(CAMP_STATUS.get(camp["status"], camp["status"]))
                    ca, cb = st.columns(2)
                    ca.metric("전체", cnt_all)
                    cb.metric("확정", cnt_conf)
                    if camp.get("description"):
                        st.caption(camp["description"])
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("관리하기 →", key=f"open_{camp['id']}", use_container_width=True, type="primary"):
                            st.session_state.selected_campaign = camp
                            st.rerun()
                    with b2:
                        if st.button("삭제", key=f"del_{camp['id']}", use_container_width=True):
                            st.session_state[f"confirm_del_{camp['id']}"] = True
                    if st.session_state.get(f"confirm_del_{camp['id']}"):
                        st.warning(f"**'{camp['name']}'** 삭제하시겠습니까?")
                        y, n = st.columns(2)
                        with y:
                            if st.button("삭제 확인", key=f"yes_{camp['id']}", type="primary"):
                                delete_campaign(camp["id"])
                                st.session_state.pop(f"confirm_del_{camp['id']}", None)
                                st.rerun()
                        with n:
                            if st.button("취소", key=f"no_{camp['id']}"):
                                st.session_state.pop(f"confirm_del_{camp['id']}", None)
                                st.rerun()
