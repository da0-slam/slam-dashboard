"""해시태그 트렌드 (UI 목업) — 실제 데이터 연동은 추후 구현 예정.

지금은 _MOCK_HASHTAGS의 하드코딩된 값으로 화면 구조만 보여준다.
실제 연동 시 이 목업 데이터를 Apify 해시태그 스크래핑 + 일별 스냅샷
테이블 조회 결과로 교체하면 된다.
"""
import streamlit as st
import pandas as pd

from utils.auth import require_auth, sidebar_user_info, block_if_demo

st.set_page_config(page_title="해시태그", page_icon="#️⃣", layout="wide")
require_auth()
block_if_demo()
sidebar_user_info()

# ── MOCK 데이터 (추후 실제 파이프라인으로 교체) ──────────────────────────────
_MOCK_HASHTAGS = [
    {
        "tag": "loveislandfinale", "category": "Fashion",
        "total_views": 311_700_000, "views_14d_pct": 5,
        "videos": 7_700, "videos_14d_pct": 26,
        "hotness": 10.0, "hotness_delta": 0.3,
        "trend": [4.1, 4.3, 4.2, 4.5, 4.8, 5.1, 5.0, 5.3, 5.6, 6.0, 6.2, 6.5, 6.9, 7.0],
        "videos_trend": [300, 320, 310, 340, 360, 380, 400, 420, 440, 460, 500, 540, 600, 616],
        "similar": ["Loveisland", "Loveislanduk", "Loveislandedit", "Loveislandseason8"],
    },
    {
        "tag": "dreamcon", "category": "Games",
        "total_views": 1_040_000_000, "views_14d_pct": 4,
        "videos": 53_800, "videos_14d_pct": 15,
        "hotness": 10.0, "hotness_delta": 0.3,
        "trend": [8.2, 8.4, 8.3, 8.5, 8.6, 8.8, 8.7, 8.9, 9.0, 9.1, 9.3, 9.4, 9.6, 9.8],
        "videos_trend": [4000, 4100, 4050, 4200, 4300, 4400, 4500, 4600, 4700, 4800, 4900, 5000, 5100, 5200],
        "similar": ["Dreamconcosplay", "Dreamconvibes", "Dreamcon2026"],
    },
    {
        "tag": "peachandme", "category": "Other",
        "total_views": 32_300_000, "views_14d_pct": 41,
        "videos": 10_300, "videos_14d_pct": 47,
        "hotness": 10.0, "hotness_delta": 0.3,
        "trend": [1.2, 1.4, 1.5, 1.8, 2.0, 2.3, 2.6, 2.9, 3.1, 3.3, 3.5, 3.6, 3.8, 3.9],
        "videos_trend": [500, 550, 600, 650, 700, 750, 800, 820, 850, 880, 900, 920, 950, 980],
        "similar": ["Peachskin", "Peachvibes"],
    },
    {
        "tag": "norwayvsengland", "category": "Media",
        "total_views": 208_500_000, "views_14d_pct": 99,
        "videos": 4_900, "videos_14d_pct": 99,
        "hotness": 10.0, "hotness_delta": 0.3,
        "trend": [0.5, 0.6, 0.8, 1.0, 1.5, 2.2, 3.0, 4.0, 5.0, 5.8, 6.4, 6.8, 6.9, 7.0],
        "videos_trend": [50, 60, 80, 100, 150, 220, 300, 400, 500, 580, 640, 680, 690, 700],
        "similar": ["Norwayfootball", "Englandvsnorway"],
    },
    {
        "tag": "adrianakim", "category": "Beauty",
        "total_views": 349_100_000, "views_14d_pct": 3,
        "videos": 6_400, "videos_14d_pct": 10,
        "hotness": 10.0, "hotness_delta": 0.2,
        "trend": [3.0, 3.1, 3.2, 3.3, 3.3, 3.4, 3.4, 3.5, 3.5, 3.6, 3.6, 3.7, 3.7, 3.8],
        "videos_trend": [400, 410, 420, 430, 440, 450, 450, 460, 470, 480, 490, 500, 510, 520],
        "similar": ["Kbeauty", "Skincareroutine"],
    },
    {
        "tag": "elizabethraymond", "category": "Education",
        "total_views": 328_500_000, "views_14d_pct": 22,
        "videos": 32_800, "videos_14d_pct": 20,
        "hotness": 10.0, "hotness_delta": 0.1,
        "trend": [5.0, 5.1, 5.3, 5.5, 5.8, 6.0, 6.3, 6.5, 6.8, 7.0, 7.2, 7.4, 7.6, 7.8],
        "videos_trend": [2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700, 2800, 2900, 3000, 3100, 3200, 3300],
        "similar": ["Studytok", "Learnontiktok"],
    },
    {
        "tag": "hotdogleaguemontage", "category": "Shopping",
        "total_views": 365_000_000, "views_14d_pct": 20,
        "videos": 105_400, "videos_14d_pct": 30,
        "hotness": 9.2, "hotness_delta": 0.4,
        "trend": [4.0, 4.2, 4.3, 4.5, 4.6, 4.8, 5.0, 5.2, 5.4, 5.6, 5.7, 5.8, 5.9, 6.0],
        "videos_trend": [8000, 8200, 8400, 8600, 8800, 9000, 9200, 9400, 9600, 9800, 10000, 10200, 10400, 10500],
        "similar": ["Hotdogchallenge", "Foodtiktok"],
    },
]

_CATEGORY_OPTIONS = ["All", "Niche", "Medium", "Generic"]


def _fmt_num(n: float) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:.0f}"


# ── 목업 안내 배너 ────────────────────────────────────────────────────────────
st.info(
    "🚧 **UI 목업 화면입니다.** 아래 수치는 실제 데이터가 아닌 예시입니다. "
    "실제 연동은 Apify 해시태그 스크래핑 + 일별 스냅샷 저장 파이프라인이 필요합니다 (추후 구현 예정).",
    icon="🚧",
)

open_tag = st.session_state.get("hashtag_open")

# ═══════════════════════════════════════════════════════════════════════════
# 목록 뷰
# ═══════════════════════════════════════════════════════════════════════════

if not open_tag:
    st.title("#️⃣ Hashtags")
    st.caption(
        "TikTok에서 오늘 가장 트렌딩한 주제는? Hotness는 각 해시태그의 오늘 성과를 "
        "과거 자기 자신의 성과와 비교해 계산됩니다."
    )

    fc1, fc2, fc3 = st.columns([2, 1, 1])
    with fc1:
        category = st.radio(
            "카테고리", _CATEGORY_OPTIONS, horizontal=True,
            key="ht_category", label_visibility="collapsed",
        )
    with fc2:
        st.selectbox("국가", ["전체 국가"], key="ht_country", label_visibility="collapsed")
    with fc3:
        sort_by = st.selectbox(
            "정렬", ["🔥 Hottest", "Total views", "Videos", "Last 14 days"],
            key="ht_sort", label_visibility="collapsed",
        )

    rows = list(_MOCK_HASHTAGS)
    if category != "All":
        rows = [r for r in rows if r["category"].lower() in category.lower() or category == "Generic"]
        # 목업이라 카테고리 매핑이 완벽하지 않음 — 실제 연동 시 진짜 niche/medium/generic 분류로 교체
    if sort_by == "Total views":
        rows.sort(key=lambda r: r["total_views"], reverse=True)
    elif sort_by == "Videos":
        rows.sort(key=lambda r: r["videos"], reverse=True)
    elif sort_by == "Last 14 days":
        rows.sort(key=lambda r: r["views_14d_pct"], reverse=True)
    else:
        rows.sort(key=lambda r: r["hotness"], reverse=True)

    st.divider()

    hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([3, 2, 2, 2, 2, 2])
    hc1.markdown("**Hashtag**")
    hc2.markdown("**Total views**")
    hc3.markdown("**Last 14 days**")
    hc4.markdown("**Videos**")
    hc5.markdown("**Last 14 days**")
    hc6.markdown("**Today's Hotness**")

    for i, r in enumerate(rows, 1):
        c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 2, 2, 2, 2])
        if c1.button(f"#{r['tag']}", key=f"ht_open_{r['tag']}", use_container_width=True):
            st.session_state["hashtag_open"] = r["tag"]
            st.rerun()
        c1.caption(r["category"])
        c2.markdown(_fmt_num(r["total_views"]))
        c3.markdown(f":green[{r['views_14d_pct']}%]" if r["views_14d_pct"] >= 0 else f":red[{r['views_14d_pct']}%]")
        c4.markdown(_fmt_num(r["videos"]))
        c5.markdown(f":green[{r['videos_14d_pct']}%]")
        c6.markdown(f"🔥 {r['hotness']:.1f}  ·  `+{r['hotness_delta']}`")

    st.stop()

# ═══════════════════════════════════════════════════════════════════════════
# 상세 뷰
# ═══════════════════════════════════════════════════════════════════════════

tag_data = next((r for r in _MOCK_HASHTAGS if r["tag"] == open_tag), None)

if not tag_data:
    st.error("해시태그를 찾을 수 없습니다.")
    if st.button("← 목록으로"):
        st.session_state.pop("hashtag_open", None)
        st.rerun()
    st.stop()

if st.button("← Hashtags 목록으로"):
    st.session_state.pop("hashtag_open", None)
    st.rerun()

st.caption("TikTok Hashtags")
top_a, top_b = st.columns([5, 1])
with top_a:
    st.title(f"#{tag_data['tag']}")
with top_b:
    st.button("🔖 Track hashtag", key="ht_track", use_container_width=True, disabled=True)

tab_overview, tab_videos, tab_related, tab_trending, tab_countries = st.tabs(
    ["Overview", "Videos", "Related", "Trending", "Countries"]
)

with tab_overview:
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total Views", _fmt_num(tag_data["total_views"]))
    m2.metric("Videos", _fmt_num(tag_data["videos"]))
    avg_views = tag_data["total_views"] / tag_data["videos"] if tag_data["videos"] else 0
    m3.metric("Avg Views/Video", _fmt_num(avg_views))
    m4.metric("Today's Hotness", f"{tag_data['hotness']:.1f}/10", f"+{tag_data['hotness_delta']}")
    m5.metric("Trend", "↑" if tag_data["trend"][-1] >= tag_data["trend"][0] else "↓")
    m6.metric("Category", tag_data["category"])

    st.markdown("##### Hashtag growth")
    st.caption("최근 14일 추이 (예시 데이터)")

    days = [f"D-{13-i}" for i in range(14)]
    gc1, gc2 = st.columns(2)
    with gc1:
        st.caption("TikTok Views")
        st.line_chart(
            pd.DataFrame({"Views (M)": tag_data["trend"]}, index=days),
            use_container_width=True, height=260,
        )
    with gc2:
        st.caption("TikTok Videos")
        st.bar_chart(
            pd.DataFrame({"Videos": tag_data["videos_trend"]}, index=days),
            use_container_width=True, height=260,
        )

    st.divider()
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        st.markdown("##### Latest videos for the hashtag")
        st.warning(
            "Track hashtag for more data — 실제로 이 해시태그를 트래킹하면 영상/데이터 수집이 시작됩니다 "
            "(최대 48시간 소요). 아래는 예시 카드입니다.",
            icon="⚠️",
        )
        vcols = st.columns(4)
        for j in range(4):
            with vcols[j]:
                st.markdown(
                    "<div style='aspect-ratio:9/16;background:#1a1a1a;border-radius:10px;"
                    "display:flex;align-items:center;justify-content:center;color:#666;font-size:28px;'>"
                    "▶️</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"❤️ {4900 - j*300:,}  ·  💬 {90 - j*10}  ·  🔁 {j+1}.{j}%")
    with sc2:
        st.markdown("##### Similar hashtags")
        for s in tag_data["similar"]:
            st.markdown(f"**#{s}**")
            st.button("Track hashtag", key=f"track_similar_{s}", use_container_width=True, disabled=True)
            st.divider()

with tab_videos:
    st.info("🚧 Videos 탭 — 실제 연동 시 해당 해시태그의 전체 영상 목록이 여기 표시됩니다.")

with tab_related:
    st.info("🚧 Related 탭 — 관련 해시태그 추천이 여기 표시됩니다.")

with tab_trending:
    st.info("🚧 Trending 탭 — 시기별 트렌딩 추이가 여기 표시됩니다.")

with tab_countries:
    st.info("🚧 Countries 탭 — 국가별 성과 분포가 여기 표시됩니다.")
