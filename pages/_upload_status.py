"""전체 브랜드 · 전체 캠페인의 업로드 현황 취합 (관리자 전용)."""
import pandas as pd
import streamlit as st

from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    get_all_campaigns, get_brands, get_campaign_posts_for_campaigns, get_user_profile,
)

user = require_auth()
sidebar_user_info()

profile = get_user_profile(user.id)
if not profile or profile.get("role") != "admin":
    st.error("관리자 전용 페이지입니다.")
    st.stop()

st.title("📤 전체 프로젝트 업로드 현황")
st.caption("모든 브랜드의 캠페인을 발송 인원 대비 업로드 인원 기준으로 한눈에 봅니다.")

_all_camps = get_all_campaigns()
if not _all_camps:
    st.info("등록된 캠페인이 없습니다.")
    st.stop()

_brand_map = {b["id"]: b["name"] for b in get_brands()}
_all_camp_posts = get_campaign_posts_for_campaigns([c["id"] for c in _all_camps])

_posts_by_camp: dict[str, list[dict]] = {}
for _p in _all_camp_posts:
    _posts_by_camp.setdefault(_p["campaign_id"], []).append(_p)

_UP_HDR = {
    "name", "full name", "인플루언서", "인플루언서명", "influencer",
    "influencer_name", "이름", "계정", "아이디", "id",
}


def _uploaded_count_for(camp_posts: list[dict]) -> int:
    names = set()
    for _pp in camp_posts:
        n = (_pp.get("influencer_name") or "").strip()
        if n and n.lower() not in _UP_HDR:
            names.add(n)
    return len(names)


_UP_STATUS_LABEL = {"draft": "⚪ 미정", "active": "🔵 진행중", "closed": "⚫ 종료"}


def _upload_row(c: dict) -> dict:
    p_count = c.get("participant_count") or 0
    override = c.get("uploaded_count_override")
    u_count = override if override is not None else _uploaded_count_for(_posts_by_camp.get(c["id"], []))
    rate = round(u_count / p_count * 100, 1) if p_count else 0.0
    return {
        "브랜드":      _brand_map.get(c.get("brand_id"), "-"),
        "캠페인":      c.get("name", "-"),
        "상태":        _UP_STATUS_LABEL.get(c.get("status"), c.get("status") or "-"),
        "발송 인원":   p_count,
        "업로드 인원": u_count,
        "달성률(%)":  rate,
        "진행률":      rate,
        "_status_raw": c.get("status"),
    }


_up_rows = [_upload_row(c) for c in _all_camps]
_up_active = [{k: v for k, v in r.items() if k != "_status_raw"}
              for r in _up_rows if r["_status_raw"] != "closed"]
_up_closed = [{k: v for k, v in r.items() if k != "_status_raw"}
              for r in _up_rows if r["_status_raw"] == "closed"]

# ProgressColumn은 셀에 숫자를 표시하지 않고 막대만 그려서 퍼센트가 안 보이는
# 문제가 있었다. 숫자는 NumberColumn으로, 시각적 막대는 별도 ProgressColumn으로
# 나란히 보여준다.
_up_col_config = {
    "발송 인원":   st.column_config.NumberColumn("발송 인원", format="%d명"),
    "업로드 인원": st.column_config.NumberColumn("업로드 인원", format="%d명"),
    "달성률(%)":  st.column_config.NumberColumn("달성률", format="%.1f%%"),
    "진행률":      st.column_config.ProgressColumn("진행률", min_value=0, max_value=100, format="%.0f%%"),
}

if _up_active:
    st.dataframe(
        pd.DataFrame(_up_active), hide_index=True, width="stretch",
        column_config=_up_col_config,
    )
else:
    st.info("진행중/미정 상태의 캠페인이 없습니다.")

if _up_closed:
    with st.expander(f"📁 종료된 캠페인 ({len(_up_closed)}건)"):
        st.dataframe(
            pd.DataFrame(_up_closed), hide_index=True, width="stretch",
            column_config=_up_col_config,
        )
