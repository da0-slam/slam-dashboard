"""댓글 표시용 공통 렌더링 함수 — 콘텐츠 성과 페이지와 공개 리포트 페이지에서 함께 사용."""
import streamlit as st
from collections import Counter


def fmt_time(ts: str) -> str:
    if not ts:
        return ""
    try:
        from datetime import datetime as _dt
        dt = _dt.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts[:16]


def comment_avatar_color(name: str) -> str:
    colors = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444", "#8b5cf6", "#14b8a6"]
    return colors[sum(ord(c) for c in (name or "?")) % len(colors)]


def render_comment_summary(comments: list[dict]) -> None:
    r_cnt = Counter(c.get("user_region") or "" for c in comments if c.get("user_region"))
    l_cnt = Counter(c.get("user_language") or "" for c in comments if c.get("user_language"))
    if not r_cnt and not l_cnt:
        return
    sc1, sc2 = st.columns(2)
    with sc1:
        if r_cnt:
            st.markdown("**🌍 댓글 작성 지역 TOP 5**")
            total = sum(r_cnt.values())
            tags = "".join(
                f"<span style='background:#f3f4f6;border-radius:6px;padding:3px 10px;margin:2px;"
                f"font-size:12px;font-weight:600;color:#374151;display:inline-block;'>"
                f"{r} <span style='color:#6b7280;font-weight:400'>{c/total*100:.0f}%</span></span>"
                for r, c in r_cnt.most_common(5)
            )
            st.markdown(f"<div style='margin-bottom:8px'>{tags}</div>", unsafe_allow_html=True)
    with sc2:
        if l_cnt:
            st.markdown("**🗣 사용자 언어 TOP 5**")
            total = sum(l_cnt.values())
            tags = "".join(
                f"<span style='background:#eff6ff;border-radius:6px;padding:3px 10px;margin:2px;"
                f"font-size:12px;font-weight:600;color:#1d4ed8;display:inline-block;'>"
                f"{l.upper()} <span style='color:#6b7280;font-weight:400'>{c/total*100:.0f}%</span></span>"
                for l, c in l_cnt.most_common(5)
            )
            st.markdown(f"<div style='margin-bottom:8px'>{tags}</div>", unsafe_allow_html=True)
    st.divider()


def _pie_chart(counter: Counter, colors: list[str], top_n: int = 5):
    """상위 top_n개 + 나머지는 '기타'로 묶은 도넛형 파이차트.
    슬라이스에는 라벨만 표시하고, 퍼센트·건수는 호버에서만 노출."""
    import plotly.graph_objects as go

    total = sum(counter.values())
    ranked = counter.most_common()
    top, rest = ranked[:top_n], ranked[top_n:]

    labels = [name for name, _ in top]
    values = [cnt for _, cnt in top]
    hover_text = [f"{l} {v/total*100:.1f}% ({v:,}건)" for l, v in zip(labels, values)]

    if rest:
        other_count = sum(cnt for _, cnt in rest)
        labels.append("기타")
        values.append(other_count)
        _names = ", ".join(name for name, _ in rest[:15])
        if len(rest) > 15:
            _names += f" 외 {len(rest) - 15}개"
        hover_text.append(f"기타 {other_count/total*100:.1f}% ({other_count:,}건)<br>{_names}")

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.4,
        text=hover_text,
        hovertemplate="%{text}<extra></extra>",
        textinfo="label",
        marker=dict(colors=colors[:len(labels)]),
    )])
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        showlegend=True,
        height=320,
        # 범례 클릭 시 슬라이스가 사라지는 기본 동작 비활성화 — 여긴 색상 안내용
        legend=dict(itemclick=False, itemdoubleclick=False),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_comment_distribution_charts(comments: list[dict]) -> None:
    """지역/언어 분포를 원형 차트로 시각화 (상위 5개 + 기타, 캠페인 단위 집계 섹션용)."""
    r_cnt = Counter(c.get("user_region") or "" for c in comments if c.get("user_region"))
    l_cnt = Counter((c.get("user_language") or "").upper() for c in comments if c.get("user_language"))
    if not r_cnt and not l_cnt:
        st.info("지역/언어 정보가 있는 댓글이 없습니다.")
        return
    _region_colors   = ["#6366f1", "#818cf8", "#a5b4fc", "#c7d2fe", "#e0e7ff", "#d1d5db"]
    _language_colors = ["#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe", "#d1d5db"]
    dc1, dc2 = st.columns(2)
    with dc1:
        if r_cnt:
            st.markdown("**🌍 지역 분포 (TOP 5 + 기타)**")
            _pie_chart(r_cnt, _region_colors)
    with dc2:
        if l_cnt:
            st.markdown("**🗣 언어 분포 (TOP 5 + 기타)**")
            _pie_chart(l_cnt, _language_colors)


def render_comments(comments: list[dict]) -> None:
    render_comment_summary(comments)
    st.markdown("""
    <style>
    .cmt-card{padding:10px 12px;border-radius:8px;margin-bottom:6px;background:#f9fafb;}
    .cmt-av{width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;
            justify-content:center;color:#fff;font-size:13px;font-weight:700;flex-shrink:0;
            vertical-align:top;margin-right:9px;}
    .cmt-body{display:inline-block;vertical-align:top;max-width:calc(100% - 48px);}
    .cmt-user{font-size:12px;font-weight:700;color:#111;margin:0 0 1px;}
    .cmt-meta{font-size:11px;color:#9ca3af;margin:0 0 4px;}
    .cmt-text{font-size:13px;color:#374151;margin:0;word-break:break-word;}
    .cmt-like{font-size:11px;color:#6b7280;margin-top:4px;}
    </style>
    """, unsafe_allow_html=True)
    for cmt in comments:
        uname     = cmt.get("username") or cmt.get("display_name") or "?"
        dname     = cmt.get("display_name") or uname
        initial   = uname[0].upper() if uname != "?" else "?"
        color     = comment_avatar_color(uname)
        time_str  = fmt_time(cmt.get("created_at") or "")
        text      = (cmt.get("text") or "").replace("<", "&lt;").replace(">", "&gt;")
        likes     = cmt.get("like_count") or 0
        region    = cmt.get("user_region") or ""
        user_lang = (cmt.get("user_language") or "").upper()
        badge_html = ""
        if region:
            badge_html += f"<span style='background:#f3f4f6;border-radius:4px;padding:1px 6px;font-size:10px;color:#374151;margin-right:3px;'>🌍 {region}</span>"
        if user_lang:
            badge_html += f"<span style='background:#eff6ff;border-radius:4px;padding:1px 6px;font-size:10px;color:#1d4ed8;'>🗣 {user_lang}</span>"
        st.markdown(
            f"""<div class='cmt-card'>
                <span class='cmt-av' style='background:{color};'>{initial}</span>
                <span class='cmt-body'>
                    <p class='cmt-user'>@{uname} <span style='font-weight:400;color:#6b7280;'>· {dname}</span>{"&nbsp;&nbsp;" + badge_html if badge_html else ""}</p>
                    <p class='cmt-meta'>{time_str}</p>
                    <p class='cmt-text'>{text}</p>
                    <p class='cmt-like'>❤️ {likes:,}</p>
                </span>
            </div>""",
            unsafe_allow_html=True,
        )
