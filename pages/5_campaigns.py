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
    bulk_add_to_campaign,
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


@st.dialog("콘텐츠 전체보기", width="large")
def show_contents_dialog(influencer_id: str):
    st.caption(f"@{influencer_id}")
    contents = get_influencer_contents(influencer_id)
    if not contents:
        st.info("등록된 콘텐츠 데이터가 없습니다.")
        return
    COLS = 4
    for chunk in range(0, len(contents), COLS):
        row_items = contents[chunk:chunk + COLS]
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
                id_col      = _find_col(["influencer_id", "influencer id", "username", "tiktok_id", "tiktok", "유저명", "아이디"]) or df_csv.columns[0]
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
                url_col     = _find_col(["url"])

                _STATUS_MAP = {"agree": "confirmed", "agreed": "confirmed", "nego": "candidate", "negotiating": "candidate"}

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
                    if not iid or iid.lower() in ("nan", "none", ""):
                        continue

                    raw_status = _clean(row[status_col]) if status_col else ""
                    status = _STATUS_MAP.get(raw_status.lower(), raw_status)
                    if status not in ("candidate", "confirmed", "rejected"):
                        status = "candidate"

                    entries.append({
                        "influencer_id": iid,
                        "status":        status,
                        "note":          _clean(row[note_col])    if note_col    else "",
                        "followers":     _followers(row[follow_col]) if follow_col else None,
                        "contact_email": _clean(row[contact_col]) if contact_col else "",
                        "ratecard":      _clean(row[rate_col])    if rate_col    else "",
                        "after_nego":    _clean(row[nego_col])    if nego_col    else "",
                        "usage_rights":  _clean(row[usage_col])   if usage_col   else "",
                        "platform_url":  _clean(row[url_col])     if url_col     else "",
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

    st.divider()

    selections    = get_campaign_selections(camp["id"])
    inf_ids       = [s["influencer_id"] for s in selections]
    thumb_map     = get_influencer_thumbnails(inf_ids)
    inf_map       = {r["influencer_id"]: r for r in get_influencers()}
    note_cnt_map  = get_note_counts(inf_ids, selected_brand_id)

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
            COLS = 4
            for chunk_start in range(0, len(items), COLS):
                row  = items[chunk_start:chunk_start + COLS]
                cols = st.columns(COLS)
                for col, item, rank in zip(cols, row, range(chunk_start + 1, chunk_start + COLS + 1)):
                    inf_id    = item["influencer_id"]
                    status    = item["status"]
                    inf       = inf_map.get(inf_id, {})
                    thumb     = thumb_map.get(inf_id, {})
                    thumbnail = thumb.get("thumbnail") or inf.get("cover_url") or ""
                    video_url = thumb.get("video_url", "")
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
    <p class="s">{inf.get('platform','')} · {STATUS_LABEL[status]}</p>
  </div>
</div>
""", unsafe_allow_html=True)
                        b1, b2 = st.columns(2)
                        next_s = {"candidate": "confirmed", "confirmed": "rejected", "rejected": "candidate"}[status]
                        next_l = {"candidate": "✅확정", "confirmed": "🔴제외", "rejected": "🟡후보"}[status]
                        with b1:
                            if st.button(next_l, key=f"{prefix}_g_ns_{item['id']}", use_container_width=True):
                                update_campaign_selection(item["id"], next_s)
                                st.rerun()
                        with b2:
                            if st.button("삭제", key=f"{prefix}_g_rm_{item['id']}", use_container_width=True):
                                remove_campaign_selection(item["id"])
                                st.rerun()
                        b3, b4 = st.columns(2)
                        with b3:
                            nc = note_cnt_map.get(inf_id, 0)
                            if st.button(f"💬 {nc}" if nc else "💬", key=f"{prefix}_g_note_{item['id']}", use_container_width=True):
                                show_notes_dialog(inf_id, selected_brand_id, user.email, camp_id)
                        with b4:
                            if st.button("📷 전체", key=f"{prefix}_g_all_{item['id']}", use_container_width=True):
                                show_contents_dialog(inf_id)
        else:
            for item in items:
                inf_id    = item["influencer_id"]
                status    = item["status"]
                inf       = inf_map.get(inf_id, {})
                thumb     = thumb_map.get(inf_id, {})
                thumbnail = thumb.get("thumbnail") or inf.get("cover_url") or ""
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
                        _purl = item.get("platform_url") or ""
                        _plat = inf.get("platform", "")
                        _link = f"[↗ 프로필]({_purl})" if _purl else (f"[↗ 영상]({video_url})" if video_url else "")
                        _fol  = f"👥 {_fmt(item['followers'])}" if item.get("followers") else ""
                        st.caption(f"{_plat}  {_fol}  {_link}".strip())
                        _meta = "  |  ".join(filter(None, [
                            item.get("usage_rights"),
                        ]))
                        if _meta:
                            st.caption(_meta)
                        if item.get("note"):
                            st.caption(f"📝 {item['note']}")
                    with c3:
                        next_s = {"candidate": "confirmed", "confirmed": "rejected", "rejected": "candidate"}[status]
                        next_l = {"candidate": "✅ 확정", "confirmed": "🔴 제외", "rejected": "🟡 후보로"}[status]
                        if st.button(next_l, key=f"{prefix}_l_ns_{item['id']}", use_container_width=True):
                            update_campaign_selection(item["id"], next_s)
                            st.rerun()
                    with c4:
                        nc = note_cnt_map.get(inf_id, 0)
                        if st.button(f"💬{nc}" if nc else "💬", key=f"{prefix}_l_note_{item['id']}", use_container_width=True, help="메모/댓글"):
                            show_notes_dialog(inf_id, selected_brand_id, user.email, camp_id)
                    with c5:
                        if st.button("삭제", key=f"{prefix}_l_rm_{item['id']}", use_container_width=True):
                            remove_campaign_selection(item["id"])
                            st.rerun()
                    with c6:
                        if st.button("📷", key=f"{prefix}_l_all_{item['id']}", use_container_width=True, help="콘텐츠 전체보기"):
                            show_contents_dialog(inf_id)

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
