"""전략 페이지 — 브랜드별 콘텐츠 가이드 문서 (여러 개 생성 가능)."""
import streamlit as st
import re
import os as _os
from collections import Counter

from utils.auth import require_auth, sidebar_user_info, get_active_brand_id, block_if_demo
from utils.supabase_client import (
    get_brands,
    get_user_profile,
    get_brand_strategies,
    get_brand_strategy_by_id,
    create_brand_strategy,
    update_brand_strategy,
    delete_brand_strategy,
    get_strategy_files,
    add_strategy_file,
    delete_strategy_file,
)
from utils.storage_client import (
    upload_strategy_file,
    create_strategy_token,
    revoke_strategy_token,
)

st.set_page_config(page_title="전략", page_icon="🎯", layout="wide")

user = require_auth()
block_if_demo()
sidebar_user_info()

profile = get_user_profile(user.id)
is_admin = profile.get("role") == "admin"
_user_brand_ids = set(
    (profile.get("brand_ids") or [])
    + ([profile["brand_id"]] if profile.get("brand_id") else [])
)

if not is_admin and not _user_brand_ids:
    st.error("접근 권한이 없습니다.")
    st.stop()

# ── 브랜드 선택 ───────────────────────────────────────────────────────────────
if is_admin:
    brands = get_brands()
    if not brands:
        st.warning("등록된 브랜드가 없습니다.")
        st.stop()
    _cnt = Counter(b["name"] for b in brands)
    _bmap = {
        (f"{b['name']}  [{b['id'][:8]}]" if _cnt[b["name"]] > 1 else b["name"]): b["id"]
        for b in brands
    }
    sel_label = st.sidebar.selectbox("브랜드 (관리자)", list(_bmap.keys()), key="strat_brand_sel")
    brand_id: str = _bmap[sel_label]
    brand_name = sel_label.split("  [")[0]
else:
    brand_id = get_active_brand_id(profile)
    if not brand_id or brand_id not in _user_brand_ids:
        st.error("접근 권한이 없습니다.")
        st.stop()
    brand_name = brand_id
    try:
        brands = get_brands()
        brand_name = next((b["name"] for b in brands if b["id"] == brand_id), brand_id)
    except Exception:
        pass

# 브랜드가 바뀌면 열려있던 문서를 닫는다
if st.session_state.get("strat_brand_ctx") != brand_id:
    st.session_state["strat_brand_ctx"] = brand_id
    st.session_state.pop("strat_open_id", None)

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def _load_docs(bid: str) -> list[dict]:
    return get_brand_strategies(bid)

@st.cache_data(ttl=30, show_spinner=False)
def _load_doc(sid: str) -> dict:
    return get_brand_strategy_by_id(sid)

@st.cache_data(ttl=30, show_spinner=False)
def _load_files(sid: str, section: str) -> list[dict]:
    return get_strategy_files(sid, section)


st.title(f"🎯 전략  ·  {brand_name}")

open_id = st.session_state.get("strat_open_id")

# ═══════════════════════════════════════════════════════════════════════════
# 목록 뷰
# ═══════════════════════════════════════════════════════════════════════════

if not open_id:
    docs = _load_docs(brand_id)

    if not docs:
        st.info("아직 생성된 가이드 문서가 없습니다. 아래에서 첫 문서를 만들어보세요.")
    else:
        for d in docs:
            did = d["id"]
            name = d.get("name") or "(이름 없음)"
            updated = (d.get("updated_at") or "")[:16].replace("T", " ")

            rename_key = f"strat_rename_{did}"
            if st.session_state.get(rename_key):
                rc1, rc2, rc3 = st.columns([5, 1, 1])
                new_name = rc1.text_input(
                    "이름", value=name, key=f"strat_rename_input_{did}", label_visibility="collapsed",
                )
                if rc2.button("💾", key=f"strat_rename_save_{did}", use_container_width=True):
                    if new_name.strip():
                        update_brand_strategy(did, {"name": new_name.strip()})
                        _load_docs.clear()
                    st.session_state[rename_key] = False
                    st.rerun()
                if rc3.button("취소", key=f"strat_rename_cancel_{did}", use_container_width=True):
                    st.session_state[rename_key] = False
                    st.rerun()
            else:
                c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
                c1.markdown(f"**📄 {name}**" + (f"  \n`수정: {updated}`" if updated else ""))
                if c2.button("열기", key=f"strat_open_{did}", use_container_width=True):
                    st.session_state["strat_open_id"] = did
                    st.rerun()
                if c3.button("✏️", key=f"strat_rename_btn_{did}", use_container_width=True):
                    st.session_state[rename_key] = True
                    st.rerun()

                del_key = f"strat_del_confirm_{did}"
                if st.session_state.get(del_key):
                    if c4.button("⚠️확인", key=f"strat_del_ok_{did}", use_container_width=True):
                        delete_brand_strategy(did)
                        _load_docs.clear()
                        st.session_state.pop(del_key, None)
                        st.rerun()
                else:
                    if c4.button("🗑️", key=f"strat_del_{did}", use_container_width=True):
                        st.session_state[del_key] = True
                        st.rerun()
            st.divider()

    with st.expander("➕ 새 가이드 만들기", expanded=not docs):
        new_doc_name = st.text_input(
            "문서 이름", placeholder="예: NAD+ 가이드, 아젤리산성 가이드", key="strat_new_name",
        )
        if st.button("만들기", key="strat_new_create", type="primary"):
            if not new_doc_name.strip():
                st.error("문서 이름을 입력해주세요.")
            else:
                created = create_brand_strategy(brand_id, new_doc_name.strip())
                if created:
                    _load_docs.clear()
                    st.session_state["strat_open_id"] = created["id"]
                    st.rerun()
                else:
                    st.error("생성에 실패했습니다.")

    st.stop()

# ═══════════════════════════════════════════════════════════════════════════
# 상세 뷰 (open_id가 설정된 상태)
# ═══════════════════════════════════════════════════════════════════════════

strategy_id = open_id
data = _load_doc(strategy_id)

if not data:
    st.error("문서를 찾을 수 없습니다.")
    if st.button("← 목록으로"):
        st.session_state.pop("strat_open_id", None)
        st.rerun()
    st.stop()

doc_name = data.get("name") or "(이름 없음)"

top1, top2 = st.columns([1, 5])
if top1.button("← 목록으로", use_container_width=True):
    st.session_state.pop("strat_open_id", None)
    st.rerun()
top2.markdown(f"### 📄 {doc_name}")

# ── 파일 업로드/뷰어 공통 렌더러 ─────────────────────────────────────────────
def _render_files(section: str):
    st.divider()
    st.markdown("##### 📎 첨부파일")

    files = _load_files(strategy_id, section)
    viewing_key = f"strat_viewing_{strategy_id}_{section}"

    # 파일 목록
    if files:
        for f in files:
            fid      = f["id"]
            fname    = f["file_name"]
            furl     = f["file_url"]
            ftype    = f.get("file_type", "")
            fsize    = f.get("file_size") or 0
            size_str = f"{fsize/1024:.0f} KB" if fsize > 0 else ""
            is_pdf   = "pdf" in ftype.lower()
            is_image = any(t in ftype.lower() for t in ["png","jpg","jpeg","gif","webp","image"])

            icon = "📄" if is_pdf else ("🖼️" if is_image else "📎")
            col_a, col_b, col_c = st.columns([6, 1, 1])
            col_a.markdown(f"{icon} **{fname}**" + (f"  `{size_str}`" if size_str else ""))

            if is_pdf or is_image:
                is_viewing = st.session_state.get(viewing_key) == fid
                if col_b.button("🔼 닫기" if is_viewing else "👁️ 보기",
                                key=f"view_{fid}", use_container_width=True):
                    st.session_state[viewing_key] = None if is_viewing else fid
                    st.rerun()
            else:
                col_b.markdown(f"[⬇️ 다운로드]({furl})")

            if col_c.button("🗑️", key=f"del_file_{fid}", use_container_width=True):
                delete_strategy_file(fid)
                _load_files.clear()
                if st.session_state.get(viewing_key) == fid:
                    st.session_state[viewing_key] = None
                st.rerun()

            if st.session_state.get(viewing_key) == fid:
                if is_pdf:
                    st.markdown(
                        f'<iframe src="{furl}" width="100%" height="780" '
                        f'style="border:1px solid #ddd;border-radius:8px;margin-top:4px;"></iframe>',
                        unsafe_allow_html=True,
                    )
                elif is_image:
                    st.image(furl, use_container_width=True)
                st.markdown("---")

    # 업로드 폼
    with st.expander("➕ 파일 업로드", expanded=False):
        uploaded = st.file_uploader(
            "PDF, 이미지, 문서",
            type=["pdf", "png", "jpg", "jpeg", "gif", "webp", "pptx", "docx", "xlsx"],
            key=f"strat_uploader_{strategy_id}_{section}",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            if st.button("⬆️ 업로드", key=f"strat_upload_btn_{section}", type="primary"):
                with st.spinner("업로드 중..."):
                    file_bytes = uploaded.read()
                    file_url = upload_strategy_file(
                        brand_id, file_bytes, uploaded.name, uploaded.type
                    )
                    if file_url:
                        add_strategy_file(
                            strategy_id, brand_id, uploaded.name, file_url,
                            uploaded.type, len(file_bytes), section=section,
                        )
                        _load_files.clear()
                        st.success(f"'{uploaded.name}' 업로드 완료")
                        st.rerun()
                    else:
                        st.error("업로드 실패. Supabase Storage `strategy-files` 버킷을 확인하세요.")


# ── 탭 렌더러 ─────────────────────────────────────────────────────────────────
SECTION_META = {
    "brand_guide": {
        "label": "📖 브랜드 가이드",
        "placeholder": (
            "브랜드의 핵심 가치, 톤앤매너, 슬로건, 금지 표현 등을 마크다운으로 작성하세요.\n\n"
            "예시:\n## 핵심 가치\n- 신뢰, 혁신, 건강\n\n## 톤앤매너\n- 친근하되 전문적인 말투 사용\n\n## 슬로건\n> 당신의 건강한 하루를 응원합니다"
        ),
    },
    "campaign_goals": {
        "label": "🎯 캠페인 목표",
        "placeholder": (
            "캠페인 KPI, 목표 수치, 핵심 메시지 등을 작성하세요.\n\n"
            "예시:\n## KPI\n| 지표 | 목표 |\n|---|---|\n| 총 조회수 | 500만 |\n\n## 핵심 메시지\n1. 제품 체험 후기 중심"
        ),
    },
    "competitor_refs": {
        "label": "🔍 경쟁사 레퍼런스",
        "placeholder": (
            "참고할 경쟁사 계정, 콘텐츠 URL, 특징 분석 등을 작성하세요.\n\n"
            "예시:\n## 경쟁사 A — @competitor_a\n- [참고 릴스](https://www.instagram.com/reel/...)\n- 특징: 일상 브이로그 형식"
        ),
    },
}


_TT_RE = re.compile(r'https?://(?:www\.)?tiktok\.com/@[\w.]+/video/(\d+)')
_IG_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/([\w-]+)/?')


def _embed_html(platform: str, vid_id: str) -> str:
    if platform == "tiktok":
        return (
            f'<iframe src="https://www.tiktok.com/embed/v2/{vid_id}" '
            f'style="width:100%;height:700px;border:none;" allowfullscreen></iframe>'
        )
    return (
        f'<iframe src="https://www.instagram.com/p/{vid_id}/embed/" '
        f'style="width:100%;height:560px;border:none;" scrolling="no" allowtransparency="true"></iframe>'
    )


def _render_with_videos(content: str):
    """마크다운 렌더링 — TikTok/Instagram URL은 2열 그리드로 임베드."""
    segments: list[tuple] = []
    buf: list[str] = []
    for line in content.split("\n"):
        tt = _TT_RE.search(line)
        ig = _IG_RE.search(line)
        if tt or ig:
            if buf:
                segments.append(("text", "\n".join(buf)))
                buf = []
            segments.append(("video", "tiktok" if tt else "instagram", tt.group(1) if tt else ig.group(1)))
        else:
            buf.append(line)
    if buf:
        segments.append(("text", "\n".join(buf)))

    i = 0
    while i < len(segments):
        seg = segments[i]
        if seg[0] == "text":
            st.markdown(seg[1], unsafe_allow_html=True)
            i += 1
        else:
            # 빈 줄 사이에 있는 영상도 한 그룹으로 묶어서 2열 배치
            videos = []
            while i < len(segments):
                if segments[i][0] == "video":
                    videos.append(segments[i])
                    i += 1
                elif segments[i][0] == "text" and segments[i][1].strip() == "":
                    i += 1  # 영상 사이 빈 줄 건너뜀
                else:
                    break
            for j in range(0, len(videos), 2):
                pair = videos[j : j + 2]
                cols = st.columns(len(pair))
                for k, (_, platform, vid_id) in enumerate(pair):
                    with cols[k]:
                        st.markdown(_embed_html(platform, vid_id), unsafe_allow_html=True)


def _render_section(field: str):
    meta = SECTION_META[field]
    edit_key = f"strat_edit_{field}_{strategy_id}"
    content: str = data.get(field) or ""

    if st.session_state.get(edit_key):
        new_val = st.text_area(
            "내용",
            value=content,
            height=380,
            placeholder=meta["placeholder"],
            key=f"strat_input_{field}_{strategy_id}",
            label_visibility="collapsed",
        )
        st.caption("💡 TikTok 또는 Instagram 링크를 붙여넣으면 저장 후 영상이 자동으로 임베드됩니다.")
        col_s, col_c, _ = st.columns([1, 1, 6])
        if col_s.button("💾 저장", key=f"save_{field}_{strategy_id}", type="primary", use_container_width=True):
            update_brand_strategy(strategy_id, {field: new_val})
            _load_docs.clear()
            _load_doc.clear()
            st.session_state[edit_key] = False
            st.rerun()
        if col_c.button("취소", key=f"cancel_{field}_{strategy_id}", use_container_width=True):
            st.session_state[edit_key] = False
            st.rerun()
    else:
        if st.button("✏️ 편집", key=f"editbtn_{field}_{strategy_id}"):
            st.session_state[edit_key] = True
            st.rerun()
        if content.strip():
            _render_with_videos(content)
        else:
            st.info("아직 내용이 없습니다. 편집 버튼을 눌러 추가하세요.")

    # 해당 탭의 파일들
    _render_files(field)


# ── 탭 레이아웃 ───────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab_export = st.tabs([
    SECTION_META["brand_guide"]["label"],
    SECTION_META["campaign_goals"]["label"],
    SECTION_META["competitor_refs"]["label"],
    "📤 내보내기",
])

with tab1:
    _render_section("brand_guide")

with tab2:
    _render_section("campaign_goals")

with tab3:
    _render_section("competitor_refs")

with tab_export:
    st.subheader("📤 전략 문서 내보내기")

    brand_guide     = data.get("brand_guide") or ""
    campaign_goals  = data.get("campaign_goals") or ""
    competitor_refs = data.get("competitor_refs") or ""

    export_title = f"{brand_name} · {doc_name}"

    md_content = f"""# 🎯 {export_title}

---

## 📖 브랜드 가이드

{brand_guide or "_아직 내용이 없습니다._"}

---

## 🎯 캠페인 목표

{campaign_goals or "_아직 내용이 없습니다._"}

---

## 🔍 경쟁사 레퍼런스

{competitor_refs or "_아직 내용이 없습니다._"}
"""

    st.download_button(
        label="⬇️ Markdown (.md) 다운로드",
        data=md_content.encode("utf-8"),
        file_name=f"{brand_name}_{doc_name}.md",
        mime="text/markdown",
        use_container_width=True,
    )

    st.divider()

    try:
        import markdown as _md_lib
        html_body = _md_lib.markdown(md_content, extensions=["tables", "fenced_code"])
    except ImportError:
        import re as _re
        html_body = md_content
        html_body = _re.sub(r"^## (.+)$", r"<h2>\1</h2>", html_body, flags=_re.MULTILINE)
        html_body = _re.sub(r"^# (.+)$",  r"<h1>\1</h1>", html_body, flags=_re.MULTILINE)
        html_body = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_body)
        html_body = _re.sub(r"\*(.+?)\*",     r"<em>\1</em>", html_body)
        html_body = _re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html_body)
        html_body = "<br>".join(html_body.split("\n"))

    html_full = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{export_title}</title>
  <style>
    body {{ font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
            max-width: 860px; margin: 40px auto; padding: 0 24px;
            color: #1a1a1a; line-height: 1.7; }}
    h1 {{ color: #222; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
    h2 {{ color: #333; margin-top: 36px; border-left: 4px solid #ff6b35; padding-left: 10px; }}
    h3 {{ color: #555; }}
    a  {{ color: #1a73e8; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 32px 0; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
    blockquote {{ border-left: 4px solid #ccc; margin: 0; padding-left: 16px; color: #666; }}
    @media print {{
      body {{ margin: 20px; }}
      a[href]:after {{ content: " (" attr(href) ")"; font-size: 0.8em; color: #888; }}
    }}
  </style>
</head>
<body>
{html_body}
</body>
</html>"""

    st.download_button(
        label="⬇️ HTML 다운로드 (브라우저에서 PDF 인쇄 가능)",
        data=html_full.encode("utf-8"),
        file_name=f"{brand_name}_{doc_name}.html",
        mime="text/html",
        use_container_width=True,
    )

    st.caption("HTML 파일을 브라우저로 열고 **Ctrl+P → PDF로 저장**하면 한국어가 깨지지 않는 PDF를 만들 수 있습니다.")

    st.divider()
    st.markdown("**🔗 웹 공유 링크**")
    st.caption("로그인 없이 열람 가능합니다. 링크 생성 후 콘텐츠를 수정해도 같은 링크에서 항상 최신 내용을 볼 수 있습니다.")

    _site = (_os.environ.get("SITE_URL") or "").rstrip("/")
    _token_key = f"share_token_{strategy_id}"

    _col_btn, _col_del = st.columns([3, 1])
    if _col_btn.button("🔗 공유 링크 생성 (새 링크)", key="share_gen", type="primary", use_container_width=True):
        with st.spinner("링크 생성 중..."):
            _tok = create_strategy_token(brand_id, strategy_id)
        if _tok:
            st.session_state[_token_key] = _tok
        else:
            st.error("링크 생성 실패. Supabase Storage `strategy-files` 버킷을 확인하세요.")

    _cur_token = st.session_state.get(_token_key)
    if _cur_token:
        if _col_del.button("🔌 링크 연결 끊기", key="share_del", use_container_width=True):
            revoke_strategy_token(_cur_token)
            del st.session_state[_token_key]
            st.rerun()
        if _site:
            _share_url = f"{_site}/strategy_view?token={_cur_token}"
        else:
            _share_url = f"/strategy_view?token={_cur_token}"
        st.code(_share_url, language=None)
        st.caption("⚠️ 이 링크를 가진 누구나 로그인 없이 열람 가능합니다. '링크 연결 끊기' 버튼으로 즉시 차단할 수 있습니다.")
