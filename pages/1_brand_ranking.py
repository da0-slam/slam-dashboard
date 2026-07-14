"""브랜드 랭킹 (UI 목업) — OWM 입점 브랜드 글로벌 영향력 스코어링.

로그인 없이 볼 수 있는 공개 페이지 (전략 문서 공개 뷰어 _strategy_view.py와 동일한
성격 — 우선 로그인 게이트 없이 열어두고, 필요해지면 _strategy_view.py처럼
토큰 기반 접근 제어를 추가할 수 있다).

실제 데이터 연동은 추후 구현 예정. 지금은 _MOCK_BRANDS의 하드코딩된
값으로 화면 구조만 보여준다.

추천 스코어 공식 (0~100, 코호트 내 상대 정규화):
    40% Total Reach(조회수 합) + 25% Total Engagement(좋아요+댓글+공유+저장)
  + 15% Engagement Rate(참여/조회) + 10% Content Volume(게시물 수)
  + 10% Creator Diversity(고유 인플루언서 수)
실제 연동 시 campaign_posts/koc_contents를 brand_id 기준으로 집계하면
새 스크래핑 없이 바로 계산 가능. 감성(Content Emotions/AI 요약)은
댓글 텍스트에 대한 별도 LLM 분석이 필요해 2차 확장 항목으로 둔다.
"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="브랜드 랭킹", page_icon="🏆", layout="wide")

# 앱 전체에서 재사용 중인 팔레트(_comment_avatar_color, 6_content_performance.py)와 동일 —
# 브랜드별 색을 화면 전체에서 고정 배정 (순위가 바뀌어도 색은 브랜드에 고정)
_PALETTE = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444"]

# ── MOCK 데이터 (추후 campaign_posts/koc_contents 집계로 교체) ──────────────
_MOCK_BRANDS = [
    {
        "name": "23yearsold", "score": 92.4,
        "total_views": 18_400_000, "total_engagement": 612_000,
        "mentions": 342, "creators": 58,
        "sentiment": {"positive": 71, "neutral": 22, "negative": 7},
        "trend": [8, 9, 9, 10, 11, 12, 13, 14, 15, 16, 17, 17, 18, 18.4],
        "ugc_pct": 34,
        "emotions": {"신뢰": 62, "설렘": 18, "놀라움": 12, "불만": 8},
    },
    {
        "name": "유이크(UIQ)", "score": 85.6,
        "total_views": 14_200_000, "total_engagement": 471_000,
        "mentions": 276, "creators": 45,
        "sentiment": {"positive": 64, "neutral": 27, "negative": 9},
        "trend": [7, 7.4, 7.8, 8.2, 8.7, 9.3, 9.9, 10.4, 11.2, 11.8, 12.5, 13.1, 13.7, 14.2],
        "ugc_pct": 27,
        "emotions": {"신뢰": 54, "설렘": 22, "놀라움": 14, "불만": 10},
    },
    {
        "name": "리쥬올", "score": 76.3,
        "total_views": 10_500_000, "total_engagement": 318_000,
        "mentions": 214, "creators": 36,
        "sentiment": {"positive": 59, "neutral": 30, "negative": 11},
        "trend": [5, 5.3, 5.6, 6, 6.4, 6.9, 7.3, 7.8, 8.3, 8.9, 9.4, 9.9, 10.2, 10.5],
        "ugc_pct": 21,
        "emotions": {"신뢰": 47, "설렘": 24, "놀라움": 16, "불만": 13},
    },
    {
        "name": "헤브블루", "score": 65.8,
        "total_views": 6_800_000, "total_engagement": 192_000,
        "mentions": 143, "creators": 24,
        "sentiment": {"positive": 52, "neutral": 33, "negative": 15},
        "trend": [3, 3.2, 3.4, 3.7, 4.0, 4.3, 4.6, 5.0, 5.3, 5.7, 6.0, 6.3, 6.6, 6.8],
        "ugc_pct": 14,
        "emotions": {"신뢰": 38, "설렘": 19, "놀라움": 21, "불만": 22},
    },
]
for i, b in enumerate(_MOCK_BRANDS):
    b["color"] = _PALETTE[i % len(_PALETTE)]


def _fmt_num(n: float) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:.0f}"


def _dot(color: str) -> str:
    return f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;background:{color};margin-right:6px;'></span>"


def _sentiment_bar(sent: dict, height: int = 14) -> str:
    total = sum(sent.values()) or 1
    segs = [
        (sent.get("positive", 0), "#10b981"),
        (sent.get("neutral", 0), "#d1d5db"),
        (sent.get("negative", 0), "#ef4444"),
    ]
    bars = "".join(
        f"<div style='width:{v/total*100:.1f}%;background:{c};height:{height}px;'></div>"
        for v, c in segs if v > 0
    )
    return f"<div style='display:flex;width:100%;border-radius:4px;overflow:hidden;'>{bars}</div>"


st.caption("🚧 임시 화면입니다.")

open_brand = st.session_state.get("rank_open_brand")

# ═══════════════════════════════════════════════════════════════════════════
# 랭킹 목록 뷰
# ═══════════════════════════════════════════════════════════════════════════

if not open_brand:
    st.title("🏆 브랜드 랭킹")
    st.caption("OWM(오프라인 매장) 입점 브랜드의 글로벌 영향력을 스코어링해 비교합니다.")

    ranked = sorted(_MOCK_BRANDS, key=lambda b: b["score"], reverse=True)

    # ── Share of Voice ────────────────────────────────────────────────────
    st.markdown("##### 📣 Share of Voice")
    total_eng = sum(b["total_engagement"] for b in ranked) or 1
    sov_bar = "".join(
        f"<div style='width:{b['total_engagement']/total_eng*100:.1f}%;background:{b['color']};"
        f"height:28px;display:flex;align-items:center;justify-content:center;"
        f"color:#fff;font-size:11px;font-weight:600;overflow:hidden;white-space:nowrap;'>"
        f"{b['total_engagement']/total_eng*100:.0f}%</div>"
        for b in ranked
    )
    st.markdown(
        f"<div style='display:flex;width:100%;border-radius:6px;overflow:hidden;margin-bottom:6px;'>{sov_bar}</div>",
        unsafe_allow_html=True,
    )
    legend = "".join(
        f"<span style='margin-right:16px;font-size:12px;color:#374151;'>{_dot(b['color'])}{b['name']}</span>"
        for b in ranked
    )
    st.markdown(f"<div>{legend}</div>", unsafe_allow_html=True)

    st.divider()

    # ── 랭킹 테이블 ──────────────────────────────────────────────────────
    hc = st.columns([1, 3, 2, 2, 2, 2, 3, 1])
    for col, label in zip(hc, ["순위", "브랜드", "스코어", "조회수", "참여수", "언급 영상", "감성", ""]):
        col.markdown(f"**{label}**")

    for rank, b in enumerate(ranked, 1):
        c = st.columns([1, 3, 2, 2, 2, 2, 3, 1])
        c[0].markdown(f"**{rank}**")
        c[1].markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        c[2].markdown(f"**{b['score']:.1f}**")
        c[3].markdown(_fmt_num(b["total_views"]))
        c[4].markdown(_fmt_num(b["total_engagement"]))
        c[5].markdown(f"{b['mentions']:,}건")
        with c[6]:
            st.markdown(_sentiment_bar(b["sentiment"]), unsafe_allow_html=True)
        if c[7].button("열기", key=f"rank_open_{b['name']}", use_container_width=True):
            st.session_state["rank_open_brand"] = b["name"]
            st.rerun()

    st.divider()

    # ── 조회수 추이 (브랜드별) ───────────────────────────────────────────
    st.markdown("##### 📈 브랜드별 조회수 추이 (최근 14일)")
    days = [f"D-{13-i}" for i in range(14)]
    trend_df = pd.DataFrame({b["name"]: b["trend"] for b in ranked}, index=days)
    try:
        st.line_chart(trend_df, use_container_width=True, height=300,
                       color=[b["color"] for b in ranked])
    except TypeError:
        st.line_chart(trend_df, use_container_width=True, height=300)

    st.divider()

    # ── UGC 영상 언급 비중 ───────────────────────────────────────────────
    st.markdown("##### 🎬 UGC 영상 언급 비중")
    st.caption("전체 뷰티/헬스 카테고리 영상 중 해당 브랜드가 언급된 비율")
    for b in ranked:
        lc, rc = st.columns([1, 5])
        lc.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        with rc:
            st.progress(b["ugc_pct"] / 100, text=f"{b['ugc_pct']}%  ·  {b['mentions']}건")

    st.stop()

# ═══════════════════════════════════════════════════════════════════════════
# 브랜드 비교 상세 뷰
# ═══════════════════════════════════════════════════════════════════════════

if st.button("← 랭킹으로"):
    st.session_state.pop("rank_open_brand", None)
    st.rerun()

all_names = [b["name"] for b in _MOCK_BRANDS]
default_sel = [open_brand] + [n for n in all_names if n != open_brand][:2]
selected = st.multiselect("비교할 브랜드", all_names, default=default_sel, key="rank_compare_sel")
compare = [b for b in _MOCK_BRANDS if b["name"] in selected] or _MOCK_BRANDS[:1]

st.title("🏆 브랜드 비교")

cols = st.columns(len(compare))
for col, b in zip(cols, compare):
    with col:
        st.markdown(
            f"<h3 style='margin:0 0 8px'>{_dot(b['color'])}{b['name']}</h3>",
            unsafe_allow_html=True,
        )
        st.metric("글로벌 영향력 스코어", f"{b['score']:.1f}")
        st.metric("총 조회수", _fmt_num(b["total_views"]))
        st.metric("총 참여수", _fmt_num(b["total_engagement"]))
        st.metric("언급 영상", f"{b['mentions']:,}건")
        st.metric("고유 크리에이터", f"{b['creators']:,}명")
        st.markdown("**감성**")
        st.markdown(_sentiment_bar(b["sentiment"], height=18), unsafe_allow_html=True)
        st.caption(
            f"긍정 {b['sentiment']['positive']}%  ·  중립 {b['sentiment']['neutral']}%  ·  "
            f"부정 {b['sentiment']['negative']}%"
        )

st.divider()

st.markdown("##### 🧠 Content Emotions")
st.caption("영상/댓글에서 감지된 감정 비중 (브랜드별)")
emotion_labels = list(compare[0]["emotions"].keys()) if compare else []
emo_df = pd.DataFrame(
    {b["name"]: [b["emotions"].get(e, 0) for e in emotion_labels] for b in compare},
    index=emotion_labels,
)
try:
    st.bar_chart(emo_df, use_container_width=True, height=280,
                 color=[b["color"] for b in compare])
except TypeError:
    st.bar_chart(emo_df, use_container_width=True, height=280)

st.divider()

with st.expander("🤖 AI 요약 (최다 좋아요 댓글 기반)", expanded=True):
    st.caption("아래는 예시 텍스트입니다. 실제 연동 시 좋아요 상위 댓글을 모델에 전달해 요약을 생성합니다.")
    st.markdown(
        "> 소비자들은 전반적으로 **보습력과 흡수 속도**를 가장 많이 언급했습니다. "
        "특히 **글로우랩**과 **더마리페어**는 '끈적임 없음'에 대한 긍정 언급이 두드러졌고, "
        "**코스메디언**은 향에 대한 호불호가 갈리는 댓글이 상대적으로 많았습니다."
    )
