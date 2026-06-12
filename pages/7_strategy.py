"""전략 페이지 — 브랜드 전용 전략 문서 (브랜드 가이드 / 캠페인 목표 / 경쟁사 레퍼런스)."""
import streamlit as st
from collections import Counter

from utils.auth import require_auth, sidebar_user_info, get_active_brand_id
from utils.supabase_client import (
    get_brands,
    get_user_profile,
    get_brand_strategy,
    upsert_brand_strategy,
)

st.set_page_config(page_title="전략", page_icon="🎯", layout="wide")

user = require_auth()
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
    brand_name = brand_id  # fallback; replaced below
    try:
        brands = get_brands()
        brand_name = next((b["name"] for b in brands if b["id"] == brand_id), brand_id)
    except Exception:
        pass

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def _load(bid: str) -> dict:
    return get_brand_strategy(bid)


st.title(f"🎯 전략  ·  {brand_name}")

data = _load(brand_id)

# ── 공통 섹션 렌더러 ─────────────────────────────────────────────────────────
SECTION_META = {
    "brand_guide": {
        "label": "📖 브랜드 가이드",
        "placeholder": (
            "브랜드의 핵심 가치, 톤앤매너, 슬로건, 금지 표현 등을 마크다운으로 작성하세요.\n\n"
            "예시:\n"
            "## 핵심 가치\n- 신뢰, 혁신, 건강\n\n"
            "## 톤앤매너\n- 친근하되 전문적인 말투 사용\n- 과장 표현 지양\n\n"
            "## 슬로건\n> 당신의 건강한 하루를 응원합니다"
        ),
    },
    "campaign_goals": {
        "label": "🎯 캠페인 목표",
        "placeholder": (
            "캠페인 KPI, 목표 수치, 핵심 메시지 등을 작성하세요.\n\n"
            "예시:\n"
            "## KPI\n| 지표 | 목표 |\n|---|---|\n| 총 조회수 | 500만 |\n| 팔로워 유입 | 5,000명 |\n\n"
            "## 핵심 메시지\n1. 제품 체험 후기 중심\n2. 일상 속 자연스러운 노출"
        ),
    },
    "competitor_refs": {
        "label": "🔍 경쟁사 레퍼런스",
        "placeholder": (
            "참고할 경쟁사 계정, 콘텐츠 URL, 특징 분석 등을 작성하세요.\n\n"
            "예시:\n"
            "## 경쟁사 A — @competitor_a\n"
            "- [참고 릴스](https://www.instagram.com/reel/...)\n"
            "- 특징: 일상 브이로그 형식, 밝은 색감\n\n"
            "## 경쟁사 B — @competitor_b\n"
            "- 특징: 전문가 인터뷰 콘텐츠 강세"
        ),
    },
}


def _render_section(field: str):
    meta = SECTION_META[field]
    edit_key = f"strat_edit_{field}_{brand_id}"
    content: str = data.get(field) or ""

    if st.session_state.get(edit_key):
        new_val = st.text_area(
            "내용",
            value=content,
            height=420,
            placeholder=meta["placeholder"],
            key=f"strat_input_{field}_{brand_id}",
            label_visibility="collapsed",
        )
        col_s, col_c, _ = st.columns([1, 1, 6])
        if col_s.button("💾 저장", key=f"save_{field}_{brand_id}", type="primary", use_container_width=True):
            upsert_brand_strategy(brand_id, {field: new_val})
            _load.clear()
            st.session_state[edit_key] = False
            st.rerun()
        if col_c.button("취소", key=f"cancel_{field}_{brand_id}", use_container_width=True):
            st.session_state[edit_key] = False
            st.rerun()
    else:
        if st.button("✏️ 편집", key=f"editbtn_{field}_{brand_id}"):
            st.session_state[edit_key] = True
            st.rerun()
        if content.strip():
            st.markdown(content)
        else:
            st.info("아직 내용이 없습니다. 편집 버튼을 눌러 추가하세요.")


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

    brand_guide    = data.get("brand_guide") or ""
    campaign_goals = data.get("campaign_goals") or ""
    competitor_refs = data.get("competitor_refs") or ""

    # ── Markdown 다운로드 ─────────────────────────────────────────────────────
    md_content = f"""# 🎯 {brand_name} 전략 문서

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
        file_name=f"{brand_name}_전략.md",
        mime="text/markdown",
        use_container_width=True,
    )

    st.divider()

    # ── HTML → PDF 변환용 HTML 다운로드 ──────────────────────────────────────
    try:
        import markdown as _md_lib
        html_body = _md_lib.markdown(md_content, extensions=["tables", "fenced_code"])
    except ImportError:
        import re as _re
        # 간단한 마크다운 → HTML 변환 (markdown 라이브러리 없을 때)
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{brand_name} 전략 문서</title>
  <style>
    body {{ font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
            max-width: 860px; margin: 40px auto; padding: 0 24px;
            color: #1a1a1a; line-height: 1.7; }}
    h1   {{ color: #222; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
    h2   {{ color: #333; margin-top: 36px; border-left: 4px solid #ff6b35;
            padding-left: 10px; }}
    h3   {{ color: #555; }}
    a    {{ color: #1a73e8; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th   {{ background: #f5f5f5; }}
    hr   {{ border: none; border-top: 1px solid #e0e0e0; margin: 32px 0; }}
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
        file_name=f"{brand_name}_전략.html",
        mime="text/html",
        use_container_width=True,
    )

    st.caption(
        "HTML 파일을 브라우저로 열고 **Ctrl+P → PDF로 저장**하면 한국어가 깨지지 않는 PDF를 만들 수 있습니다."
    )
