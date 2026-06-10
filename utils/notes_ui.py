"""
인플루언서 메모/댓글 공통 UI
browse, campaigns 페이지에서 공통 사용
"""
import streamlit as st
from utils.supabase_client import get_influencer_notes, add_influencer_note, delete_influencer_note


def _time_label(ts: str) -> str:
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        if diff.total_seconds() < 60:
            return "방금 전"
        if diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds()//60)}분 전"
        if diff < timedelta(days=1):
            return f"{int(diff.total_seconds()//3600)}시간 전"
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return ts[:10]


@st.dialog("💬 메모 / 댓글", width="large")
def show_notes_dialog(
    influencer_id: str,
    brand_id: str,
    author_email: str,
    campaign_id: str | None = None,
):
    st.markdown(f"**@{influencer_id}**")
    st.divider()

    notes = get_influencer_notes(influencer_id, brand_id)

    if not notes:
        st.caption("아직 메모가 없습니다.")
    else:
        for note in notes:
            is_mine = note.get("author_email") == author_email
            with st.container():
                c_text, c_del = st.columns([10, 1])
                with c_text:
                    author_short = note["author_email"].split("@")[0]
                    time_str = _time_label(note.get("created_at", ""))
                    st.markdown(
                        f"<div style='background:#1e1e2e;border-radius:8px;padding:10px 14px;margin-bottom:6px;'>"
                        f"<span style='color:#a78bfa;font-size:12px;font-weight:600;'>{author_short}</span>"
                        f"<span style='color:#555;font-size:11px;margin-left:8px;'>{time_str}</span>"
                        f"<p style='margin:6px 0 0;color:#e2e8f0;font-size:13px;'>{note['content']}</p>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with c_del:
                    if is_mine:
                        if st.button("✕", key=f"del_note_{note['id']}", help="삭제"):
                            delete_influencer_note(note["id"])
                            st.rerun()

    st.divider()
    new_content = st.text_area(
        "새 메모",
        placeholder="메모를 입력하세요...",
        label_visibility="collapsed",
        height=80,
        key=f"new_note_{influencer_id}_{brand_id}",
    )
    if st.button("등록", type="primary", use_container_width=True):
        content = new_content.strip()
        if content:
            add_influencer_note(
                influencer_id=influencer_id,
                brand_id=brand_id,
                author_email=author_email,
                content=content,
                campaign_id=campaign_id,
            )
            st.rerun()
        else:
            st.warning("내용을 입력하세요.")
