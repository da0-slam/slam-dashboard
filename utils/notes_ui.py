"""
인플루언서 메모/댓글 공통 UI — Figma 스타일
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


def _avatar_color(name: str) -> str:
    palette = [
        "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
        "#10b981", "#3b82f6", "#14b8a6", "#ef4444",
    ]
    return palette[sum(ord(c) for c in name) % len(palette)]


def _avatar_html(initial: str, color: str, size: int = 32) -> str:
    return (
        f"<div style='width:{size}px;height:{size}px;border-radius:50%;background:{color};"
        f"display:flex;align-items:center;justify-content:center;"
        f"color:#fff;font-size:{size // 2 - 1}px;font-weight:700;flex-shrink:0;'>"
        f"{initial}</div>"
    )


@st.dialog("댓글", width="large")
def show_notes_dialog(
    influencer_id: str,
    brand_id: str,
    author_email: str,
    campaign_id: str | None = None,
):
    # ── 다이얼로그 CSS ─────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .note-row {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 0;
        border-bottom: 1px solid rgba(0,0,0,.06);
    }
    .note-row:last-child { border-bottom: none; }
    .note-body { flex: 1; min-width: 0; }
    .note-meta {
        display: flex;
        align-items: baseline;
        gap: 7px;
        margin-bottom: 3px;
    }
    .note-author {
        font-size: 13px;
        font-weight: 600;
        color: #111827;
    }
    .note-time {
        font-size: 11px;
        color: #9ca3af;
    }
    .note-text {
        font-size: 13px;
        color: #374151;
        line-height: 1.55;
        margin: 0;
        word-break: break-word;
        white-space: pre-wrap;
    }
    .note-input-row {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        margin-top: 14px;
    }
    </style>
    """, unsafe_allow_html=True)

    notes = get_influencer_notes(influencer_id, brand_id)

    # ── 헤더 ──────────────────────────────────────────────────────────────────
    st.markdown(
        f"<p style='font-size:13px;color:#6b7280;margin:0 0 4px;'>"
        f"<b style='color:#111;'>@{influencer_id}</b> &nbsp;·&nbsp; {len(notes)}개의 댓글</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 댓글 목록 ─────────────────────────────────────────────────────────────
    if not notes:
        st.markdown(
            "<div style='text-align:center;padding:28px 0;'>"
            "<span style='font-size:28px;'>💬</span><br>"
            "<span style='font-size:13px;color:#9ca3af;'>아직 댓글이 없습니다.<br>"
            "첫 번째 댓글을 남겨보세요.</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        for note in notes:
            is_mine = note.get("author_email") == author_email
            author_name = (note["author_email"] or "").split("@")[0]
            initial     = author_name[0].upper() if author_name else "?"
            color       = _avatar_color(author_name)
            time_str    = _time_label(note.get("created_at", ""))
            content     = (note.get("content") or "").replace("<", "&lt;").replace(">", "&gt;")

            c_comment, c_del = st.columns([14, 1])
            with c_comment:
                st.markdown(
                    f"""<div class="note-row">
                        {_avatar_html(initial, color)}
                        <div class="note-body">
                            <div class="note-meta">
                                <span class="note-author">{author_name}</span>
                                <span class="note-time">{time_str}</span>
                            </div>
                            <p class="note-text">{content}</p>
                        </div>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with c_del:
                if is_mine:
                    st.markdown("<div style='padding-top:14px;'>", unsafe_allow_html=True)
                    if st.button(
                        "✕",
                        key=f"del_note_{note['id']}",
                        help="삭제",
                        use_container_width=True,
                    ):
                        delete_influencer_note(note["id"])
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # ── 댓글 입력 ─────────────────────────────────────────────────────────────
    my_name    = author_email.split("@")[0]
    my_initial = my_name[0].upper() if my_name else "?"
    my_color   = _avatar_color(my_name)

    c_av, c_input = st.columns([1, 11])
    with c_av:
        st.markdown(
            _avatar_html(my_initial, my_color) +
            "<div style='height:6px;'></div>",
            unsafe_allow_html=True,
        )
    with c_input:
        new_content = st.text_area(
            "댓글 입력",
            placeholder=f"{my_name}(으)로 댓글 남기기...",
            label_visibility="collapsed",
            height=72,
            key=f"new_note_{influencer_id}_{brand_id}",
        )

    _, c_btn = st.columns([9, 2])
    with c_btn:
        if st.button("등록 →", type="primary", use_container_width=True, key=f"submit_{influencer_id}_{brand_id}"):
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
