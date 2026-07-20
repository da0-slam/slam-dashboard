"""브랜드 UGC 현황 — OWM 입점 브랜드의 TikTok·Instagram UGC 데이터 대시보드.

2026-07-16 개편: 브랜드 스코어(0~100)로 순위를 매기던 방식을 제거했다.
    표본 크기가 브랜드마다 크게 달라(수백~수천 건) 조회수·참여수 등 합계
    기반 지표가 실제 영향력이 아니라 "얼마나 많이 수집했는가"에 좌우되는
    문제가 있었고, 정규화 방식 자체도 상대적(코호트 구성이 바뀌면 점수도
    바뀜)이라 "1위/2위" 같은 확정적 순위로 제시하기에는 데이터 상태가
    부족하다고 판단함. 대신 브랜드별 실측 지표(총량 + 건당 평균)를 순위
    없이 나란히 보여주는 대시보드로 전환.

실데이터 파이프라인:
    1. 사용자가 Apify 콘솔에서 직접 수집한 TikTok/Instagram UGC 콘텐츠·댓글
       데이터를 Google Sheet(브랜드당 탭)로 export
    2. scripts/import_brand_ranking_sheet.py로 Supabase에 이관
       - "{브랜드}" 탭 → brand_ranking_content (TikTok 콘텐츠)
       - "{브랜드}-인스타"/"-instagram" 탭 → brand_ranking_content (Instagram)
       - "{브랜드}-코멘트"/"-댓글" 탭 → brand_ranking_comments
    3. 지역 분포는 댓글 기반(brand_ranking_comments)을 우선 사용, 없으면
       콘텐츠 위치태그로 폴백
    4. 핵심 키워드 = 콘텐츠 해시태그 빈도 top-N (fyp/viral 등 범용 태그는 제외)

    데이터가 없는 브랜드는 화면에 아예 표시되지 않습니다 (가짜 수치로
    대체하지 않음).
"""
import re
import streamlit as st
import pandas as pd
from collections import Counter

from utils.supabase_client import (
    get_brand_ranking_content, get_brand_ranking_comments, get_brand_ranking_names,
    get_brand_ranking_import_stats,
)

st.set_page_config(page_title="브랜드 UGC", page_icon="📊", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def _load_ranking_content(brand_name: str) -> list[dict]:
    return get_brand_ranking_content(brand_name)


@st.cache_data(ttl=300, show_spinner=False)
def _load_ranking_comments(brand_name: str) -> list[dict]:
    return get_brand_ranking_comments(brand_name)


@st.cache_data(ttl=300, show_spinner=False)
def _ranking_brand_names() -> list[str]:
    return get_brand_ranking_names()


@st.cache_data(ttl=300, show_spinner=False)
def _ranking_import_stats() -> dict[str, dict]:
    return get_brand_ranking_import_stats()


# 핵심 상품 2개 키워드 (scripts/compute_brand_ranking.py와 동일 — 캡션/해시태그 매칭용)
_PRODUCT_KEYWORDS = {
    "유이크(UIQ)": [
        ("바이옴 베리어 크림 미스트", ["biome barrier mist", "biome barrier"]),
        ("콜라겐 퍼밍 클렌징밤", ["collagen firming cleansing balm", "firming cleansing balm"]),
    ],
    "닥터리쥬올": [
        ("PDRN 리쥬버네이팅 크림", ["pdrn rejuvenating cream", "pdrn cream", "pdrn"]),
        ("레티노-멜라 세럼", ["retino-mela serum", "retino mela serum"]),
    ],
    "헤브블루": [
        ("살몬 케어링 센텔라 토너", ["salmon centella toner", "centella toner"]),
        ("살몬 케어링 센텔라 크림/앰플", ["salmon centella ampoule", "centella cream", "centella ampoule"]),
    ],
}


def _match_product(text: str, hashtags: list | None, keyword_list: list[tuple[str, list[str]]]) -> str | None:
    haystack = (text or "").lower() + " " + " ".join(hashtags or []).lower()
    for product_name, keywords in keyword_list:
        if any(kw in haystack for kw in keywords):
            return product_name
    return None


_GENERIC_HASHTAG_STOPWORDS = {
    "fyp", "fypage", "foryou", "foryoupage", "viral", "viralvideo", "viraltiktok",
    "tiktokmademebuyit", "creatorsearchinsights", "dealsforyoudays", "trending",
}


def _top_hashtags(rows: list[dict], n: int = 8) -> list[tuple[str, int]]:
    """콘텐츠 해시태그 빈도 top-N (fyp/viral 같은 범용 태그는 제외)."""
    counter = Counter()
    for r in rows:
        for h in (r.get("hashtags") or []):
            h_l = h.lower()
            if h_l not in _GENERIC_HASHTAG_STOPWORDS:
                counter[f"#{h_l}"] += 1
    return counter.most_common(n)


_TT_VIDEO_ID_RE = re.compile(r"/video/(\d+)")
_IG_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel)/([^/?]+)")


def _embed_url(post_url: str, platform: str) -> str | None:
    if platform == "instagram":
        m = _IG_SHORTCODE_RE.search(post_url)
        return f"https://www.instagram.com/p/{m.group(1)}/embed" if m else None
    m = _TT_VIDEO_ID_RE.search(post_url)
    return f"https://www.tiktok.com/embed/v2/{m.group(1)}" if m else None


def _top_videos(rows: list[dict], n: int = 4) -> list[dict]:
    """조회수+참여수가 높은 순으로 대표 콘텐츠 top-N (TikTok/Instagram 임베드 URL 포함)."""
    candidates = []
    for r in rows:
        post_url = r.get("post_url") or ""
        platform = r.get("platform") or "tiktok"
        embed_url = _embed_url(post_url, platform)
        if not embed_url:
            continue
        views = r.get("views") or 0
        engagement = (r.get("likes") or 0) + (r.get("comments") or 0) + (r.get("shares") or 0)
        candidates.append({
            "embed_url": embed_url,
            "post_url": post_url,
            "platform": platform,
            "title": r.get("title") or "",
            "channel_username": r.get("channel_username") or "",
            "views": views,
            "likes": r.get("likes") or 0,
            "comments": r.get("comments") or 0,
            "shares": r.get("shares") or 0,
            "_rank_score": views + engagement,
        })
    candidates.sort(key=lambda c: c["_rank_score"], reverse=True)
    return candidates[:n]


def _compute_brand_from_content(brand_name: str, rows: list[dict], comment_rows: list[dict]) -> dict:
    total_views = sum(r.get("views") or 0 for r in rows)
    total_engagement = sum((r.get("likes") or 0) + (r.get("comments") or 0) + (r.get("shares") or 0) for r in rows)
    creators = len({r["channel_username"] for r in rows if r.get("channel_username")})

    keyword_list = _PRODUCT_KEYWORDS.get(brand_name, [])
    product_stats = {name: {"count": 0, "engagement": 0} for name, _ in keyword_list}
    for r in rows:
        matched = _match_product(r.get("title"), r.get("hashtags"), keyword_list)
        if matched:
            product_stats[matched]["count"] += 1
            product_stats[matched]["engagement"] += (r.get("likes") or 0) + (r.get("comments") or 0) + (r.get("shares") or 0)

    # 지역/언어: 댓글 기반(표본이 훨씬 크고 커버리지가 좋음)을 우선 사용,
    # 댓글 데이터가 없으면 콘텐츠 위치태그로 폴백
    if comment_rows:
        region_counter = Counter(c["user_region"] for c in comment_rows if c.get("user_region"))
        lang_counter = Counter(c["user_language"] for c in comment_rows if c.get("user_language"))
        region_source = "댓글 작성자"
    else:
        region_counter = Counter(r["region_code"] for r in rows if r.get("region_code"))
        lang_counter = Counter()
        region_source = "콘텐츠 위치태그"

    region_total = sum(region_counter.values()) or 1
    regions = {k: round(v / region_total * 100, 1) for k, v in region_counter.most_common(6)}
    lang_total = sum(lang_counter.values()) or 1
    languages = {k: round(v / lang_total * 100, 1) for k, v in lang_counter.most_common(6)}

    mentions = len(rows)
    imported_dates = [r["imported_at"] for r in rows if r.get("imported_at")]

    return {
        "mentions": mentions,
        "total_views": total_views,
        "total_engagement": total_engagement,
        "avg_views": (total_views / mentions) if mentions else 0,
        "avg_engagement": (total_engagement / mentions) if mentions else 0,
        "engagement_rate": (total_engagement / total_views * 100) if total_views else 0,
        "creators": creators,
        "product_stats": product_stats,
        "regions": regions,
        "region_sample_size": sum(region_counter.values()),
        "region_source": region_source,
        "languages": languages,
        "top_keywords": _top_hashtags(rows),
        "top_videos": _top_videos(rows),
        "last_collected": max(imported_dates) if imported_dates else None,
    }

# 앱 전체에서 재사용 중인 팔레트(_comment_avatar_color, 6_content_performance.py)와 동일 —
# 브랜드별 색을 화면 전체에서 고정 배정 (순위가 바뀌어도 색은 브랜드에 고정)
_PALETTE = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444"]

# ── 추적 중인 브랜드 목록 (실데이터가 없으면 화면에 표시되지 않음) ──
_TRACKED_BRANDS = ["유이크(UIQ)", "닥터리쥬올", "헤브블루", "닥터리앤장"]

# 시트 탭 이름과 화면 표시명이 다를 경우를 위한 별칭 매핑 (현재는 이름 통일로 비어있음)
_BRAND_NAME_ALIASES: dict[str, str] = {}

_real_brand_names = set(_ranking_brand_names())

_real_computed: dict[str, dict] = {}
for _name in _TRACKED_BRANDS:
    _lookup_name = _BRAND_NAME_ALIASES.get(_name, _name)
    if _lookup_name not in _real_brand_names:
        continue
    rows = _load_ranking_content(_lookup_name)
    if not rows:
        continue
    comment_rows = _load_ranking_comments(_lookup_name)
    _real_computed[_name] = _compute_brand_from_content(_name, rows, comment_rows)



# ── 실데이터가 있는 브랜드만 최종 목록에 포함 (없는 브랜드는 가짜 수치 없이 그냥 제외) ──
_BRANDS = []
for _i, _name in enumerate(n for n in _TRACKED_BRANDS if n in _real_computed):
    computed = _real_computed[_name]
    products = [
        {"name": p_name, "count": stats["count"], "engagement": stats["engagement"]}
        for p_name, stats in computed["product_stats"].items()
    ]
    _BRANDS.append({
        "name": _name,
        "color": _PALETTE[_i % len(_PALETTE)],
        "products": products,
        "mentions": computed["mentions"],
        "total_engagement": computed["total_engagement"],
        "total_views": computed["total_views"],
        "avg_views": computed["avg_views"],
        "avg_engagement": computed["avg_engagement"],
        "engagement_rate": computed["engagement_rate"],
        "creators": computed["creators"],
        "regions": computed["regions"],
        "region_sample_size": computed["region_sample_size"],
        "region_source": computed["region_source"],
        "languages": computed["languages"],
        "top_keywords": computed["top_keywords"],
        "top_videos": computed["top_videos"],
        "last_collected": computed["last_collected"],
    })

# 지역 색상 — 실데이터의 ISO 국가 코드(US/PH/...)에 카테고리 팔레트를 순서대로 배정
_REGION_PALETTE = [
    "#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444",
    "#8b5cf6", "#14b8a6", "#f97316", "#06b6d4", "#84cc16", "#e11d48",
]
_all_region_keys = sorted({k for b in _BRANDS for k in b.get("regions", {}).keys()})
_REGION_COLORS = {k: _REGION_PALETTE[i % len(_REGION_PALETTE)] for i, k in enumerate(_all_region_keys)}

# 언어도 지역과 같은 방식으로 실제 등장하는 언어 코드에 팔레트를 순서대로 배정
# (지역과 겹치지 않게 팔레트 뒤에서부터 배정해 인접 색이 덜 겹치도록 함)
_all_lang_keys = sorted({k for b in _BRANDS for k in b.get("languages", {}).keys()})
_LANG_COLORS = {
    k: _REGION_PALETTE[(len(_REGION_PALETTE) - 1 - i) % len(_REGION_PALETTE)]
    for i, k in enumerate(_all_lang_keys)
}


def _region_bar(regions: dict, height: int = 14) -> str:
    total = sum(regions.values()) or 1
    bars = "".join(
        f"<div title='{name} {v}%' style='width:{v/total*100:.1f}%;"
        f"background:{_REGION_COLORS.get(name, '#9ca3af')};height:{height}px;'></div>"
        for name, v in regions.items() if v > 0
    )
    return f"<div style='display:flex;width:100%;border-radius:4px;overflow:hidden;'>{bars}</div>"


def _lang_bar(languages: dict, height: int = 14) -> str:
    total = sum(languages.values()) or 1
    bars = "".join(
        f"<div title='{name} {v}%' style='width:{v/total*100:.1f}%;"
        f"background:{_LANG_COLORS.get(name, '#9ca3af')};height:{height}px;'></div>"
        for name, v in languages.items() if v > 0
    )
    return f"<div style='display:flex;width:100%;border-radius:4px;overflow:hidden;'>{bars}</div>"


def _colored_labels(dist: dict, color_map: dict) -> str:
    """막대 세그먼트 색상과 매칭되는 색점 + 라벨 목록 (막대 밑에 바로 이어붙여 표시)."""
    items = "".join(
        f"<span style='margin-right:14px;font-size:12px;color:#374151;white-space:nowrap;'>"
        f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
        f"background:{color_map.get(name, '#9ca3af')};margin-right:4px;'></span>{name} {v}%</span>"
        for name, v in dist.items()
    )
    return f"<div style='margin-top:4px;line-height:1.8;'>{items}</div>"


def _keyword_tags(keywords: list[tuple[str, int]]) -> str:
    return "".join(
        f"<span style='background:#f3f4f6;border-radius:6px;padding:3px 10px;margin:2px;"
        f"font-size:12px;font-weight:600;color:#374151;display:inline-block;'>"
        f"{kw} <span style='color:#6b7280;font-weight:400'>{cnt}</span></span>"
        for kw, cnt in keywords
    )


_import_stats = _ranking_import_stats()


def _render_coverage_table(brand_names: list[str]) -> None:
    """원본 수집 건수 대비 필터링 후 유효 건수(커버리지)를 표로 노출."""
    stat_rows = [
        {
            "브랜드": name,
            "원본 수집": s["raw_count"],
            "유효(화면 반영)": s["kept_count"],
            "커버리지": f"{s['kept_count'] / s['raw_count'] * 100:.0f}%" if s["raw_count"] else "-",
        }
        for name in brand_names
        if (s := _import_stats.get(name))
    ]
    if not stat_rows:
        return
    st.caption(
        "📊 데이터 커버리지 — 해시태그/브랜드명 충돌로 무관한 콘텐츠가 섞이는 걸 막기 위해 "
        "캡션·해시태그에 브랜드 키워드가 정확히 있는 콘텐츠만 남긴 결과입니다. 커버리지가 낮을수록 "
        "원본 수집 검색어가 넓어 무관 콘텐츠가 많이 섞여 있었다는 뜻입니다."
    )
    st.dataframe(pd.DataFrame(stat_rows), use_container_width=True, hide_index=True)


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


_missing = [name for name in _TRACKED_BRANDS if name not in _real_computed]
st.caption(
    "✅ 핵심 상품 성과·조회수·참여수·언급수·지역·오디언스 국가·핵심 키워드는 Supabase에 저장된 "
    f"실제 TikTok·Instagram UGC/댓글 데이터입니다 ({', '.join(b['name'] for b in _BRANDS)}). "
    + (f"🚧 {', '.join(_missing)}는 아직 데이터가 없어 화면에 표시되지 않습니다. " if _missing else "")
)

if not _BRANDS:
    st.info("아직 표시할 실데이터가 없습니다.")
    st.stop()

open_brand = st.session_state.get("rank_open_brand")

# ═══════════════════════════════════════════════════════════════════════════
# 목록 뷰
# ═══════════════════════════════════════════════════════════════════════════

if not open_brand:
    st.title("📊 브랜드 UGC 현황")
    st.caption(
        "OWM(오프라인 매장) 입점 브랜드의 TikTok·Instagram UGC 데이터를 브랜드별로 보여줍니다. "
        "**순위가 아니라 참고 자료입니다** — 브랜드마다 수집 규모·시점이 달라 총량 지표만으로 "
        "브랜드 간 우열을 매길 수 없습니다."
    )

    with st.expander("📊 데이터 수집 방법", expanded=False):
        st.markdown(
            "담당자가 Apify를 통해 TikTok·Instagram에서 브랜드 키워드가 캡션·해시태그에 정확히 "
            "포함된 콘텐츠를 수집합니다. **자동/실시간 갱신이 아니라 특정 시점의 스냅샷**이며, "
            "브랜드마다 수집 시점과 규모가 다릅니다 — 아래 커버리지 표 참고."
        )
        st.caption(
            "데이터 출처: TikTok·Instagram UGC 콘텐츠 + 댓글(Apify 수집, Supabase 저장). "
            "핵심 상품 2개 단위 매칭은 참고용으로만 별도 표시됩니다."
        )
        _render_coverage_table([b["name"] for b in _BRANDS])

    _sort_options = {
        "총 조회수": lambda b: b["total_views"],
        "건당 평균 조회수": lambda b: b["avg_views"],
        "참여율": lambda b: b["engagement_rate"],
        "언급 건수": lambda b: b["mentions"],
        "최근 수집일": lambda b: b["last_collected"] or "",
    }
    sc1, sc2 = st.columns([2, 1])
    with sc1:
        search = st.text_input(
            "🔍 브랜드 검색", placeholder="브랜드명으로 검색", key="ugc_search",
            label_visibility="collapsed",
        )
    with sc2:
        sort_label = st.selectbox(
            "정렬 기준", list(_sort_options.keys()), key="ugc_sort", label_visibility="collapsed",
        )
    ordered = sorted(_BRANDS, key=_sort_options[sort_label], reverse=True)
    if search.strip():
        ordered = [b for b in ordered if search.strip().lower() in b["name"].lower()]

    # ── 브랜드별 참여수 비중 ─────────────────────────────────────────────
    st.markdown("##### 📣 브랜드별 참여수 비중")
    total_eng = sum(b["total_engagement"] for b in ordered) or 1
    sov_bar = "".join(
        f"<div style='width:{b['total_engagement']/total_eng*100:.1f}%;background:{b['color']};"
        f"height:28px;display:flex;align-items:center;justify-content:center;"
        f"color:#fff;font-size:11px;font-weight:600;overflow:hidden;white-space:nowrap;'>"
        f"{b['total_engagement']/total_eng*100:.0f}%</div>"
        for b in ordered
    )
    st.markdown(
        f"<div style='display:flex;width:100%;border-radius:6px;overflow:hidden;margin-bottom:6px;'>{sov_bar}</div>",
        unsafe_allow_html=True,
    )
    legend = "".join(
        f"<span style='margin-right:16px;font-size:12px;color:#374151;'>{_dot(b['color'])}{b['name']}</span>"
        for b in ordered
    )
    st.markdown(f"<div>{legend}</div>", unsafe_allow_html=True)

    st.divider()

    # ── 브랜드 목록 (검색·정렬 반영, 순위 번호 없음) ─────────────────────────
    if not ordered:
        st.caption(f"'{search}'와 일치하는 브랜드가 없습니다.")
    else:
        hc = st.columns([3, 2, 2, 2, 2, 2, 1])
        for col, label in zip(hc, ["브랜드", "총 조회수", "건당 평균", "참여율", "언급 건수", "최근 수집", ""]):
            col.markdown(f"**{label}**")
        for b in ordered:
            with st.container(border=True):
                c = st.columns([3, 2, 2, 2, 2, 2, 1])
                c[0].markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
                c[1].markdown(_fmt_num(b["total_views"]))
                c[2].markdown(_fmt_num(b["avg_views"]))
                c[3].markdown(f"{b['engagement_rate']:.1f}%")
                c[4].markdown(f"{b['mentions']:,}건")
                c[5].markdown(b["last_collected"][:10] if b.get("last_collected") else "-")
                if c[6].button("보기", key=f"rank_open_{b['name']}", use_container_width=True):
                    st.session_state["rank_open_brand"] = b["name"]
                    st.rerun()

    st.divider()

    # ── 국가별 오디언스 분포 ─────────────────────────────────────────────
    st.markdown("##### 🌍 국가별 오디언스 분포")
    st.caption(
        "이 브랜드 콘텐츠에 실제로 댓글을 남긴 오디언스가 어느 국가에 있는지 보여줍니다 "
        "(위치 태그가 있는 경우 콘텐츠 자체 위치로 보완). "
        "광고 없이 이미 여러 국가에서 유기적으로 반응이 일어나고 있다는 근거로 볼 수 있습니다."
    )
    for b in ordered:
        lc, rc = st.columns([1, 5])
        lc.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        with rc:
            if b["regions"]:
                st.markdown(_region_bar(b["regions"]), unsafe_allow_html=True)
                st.markdown(_colored_labels(b["regions"], _REGION_COLORS), unsafe_allow_html=True)
                sample = b.get("region_sample_size")
                source = b.get("region_source")
                if sample:
                    st.caption(f"{source or '표본'} {sample}건 기준")
            else:
                st.caption("데이터 없음")
            if b.get("languages"):
                st.markdown("🗣 **댓글 언어**", unsafe_allow_html=False)
                st.markdown(_lang_bar(b["languages"]), unsafe_allow_html=True)
                st.markdown(_colored_labels(b["languages"], _LANG_COLORS), unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:10px'></div>", unsafe_allow_html=True)

    st.divider()

    # ── 브랜드별 핵심 키워드 ─────────────────────────────────────────────
    st.markdown("##### 🔑 브랜드별 핵심 키워드")
    st.caption("언급 콘텐츠의 댓글에서 가장 많이 등장한 키워드 (괄호 안은 언급 횟수)")
    for b in ordered:
        lc, rc = st.columns([1, 5])
        lc.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        with rc:
            st.markdown(_keyword_tags(b["top_keywords"]), unsafe_allow_html=True)

    st.stop()

# ═══════════════════════════════════════════════════════════════════════════
# 브랜드 상세 뷰
# ═══════════════════════════════════════════════════════════════════════════

if st.button("← 목록으로"):
    st.session_state.pop("rank_open_brand", None)
    st.rerun()

all_names = [b["name"] for b in _BRANDS]
with st.expander("➕ 다른 브랜드와 비교하기 (선택사항)", expanded=False):
    added = st.multiselect(
        "비교에 추가할 브랜드", [n for n in all_names if n != open_brand], key="rank_compare_sel",
    )
selected = [open_brand] + added
compare = [b for b in _BRANDS if b["name"] in selected] or _BRANDS[:1]

st.title(f"📊 {open_brand}" if len(compare) == 1 else "📊 브랜드 비교")

with st.expander("📊 데이터 수집 방법", expanded=False):
    st.markdown(
        "담당자가 Apify를 통해 TikTok·Instagram에서 브랜드 키워드가 캡션·해시태그에 정확히 "
        "포함된 콘텐츠를 수집합니다. 자동/실시간 갱신이 아니라 특정 시점의 스냅샷입니다."
    )
    st.caption("아래 지표는 브랜드 간 순위가 아니라 각 브랜드의 실측 데이터입니다.")
    _render_coverage_table([b["name"] for b in compare])

# ── 핵심 상품 성과 (참고용) ────────────────────────────────────────────────
st.markdown("##### 🔎 핵심 상품 성과")
st.caption(
    "핵심 상품 2개의 이름이 캡션·해시태그에 언급된 콘텐츠만 집계한 참고용 지표입니다. "
    "⚠️ 실제 콘텐츠에서 상품명을 캡션에 잘 안 적는 상품은 매칭 건수가 적게 잡힐 뿐 실제로 "
    "덜 팔리거나 인기가 낮다는 뜻이 아니므로, 상품 간 개수·인게이지먼트를 직접 비교하지 마세요."
)
pc = st.columns(len(compare))
for col, b in zip(pc, compare):
    with col:
        st.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        prod_df = pd.DataFrame([
            {"상품명": p["name"], "개수": p["count"], "인게이지먼트": _fmt_num(p["engagement"])}
            for p in b["products"]
        ])
        st.dataframe(prod_df, use_container_width=True, hide_index=True)

st.divider()

cols = st.columns(len(compare))
for col, b in zip(cols, compare):
    with col:
        st.markdown(
            f"<h3 style='margin:0 0 8px'>{_dot(b['color'])}{b['name']}</h3>",
            unsafe_allow_html=True,
        )
        if b.get("last_collected"):
            st.caption(f"최근 수집: {b['last_collected'][:10]}")
        st.metric("총 조회수", _fmt_num(b["total_views"]))
        st.metric("건당 평균 조회수", _fmt_num(b["avg_views"]))
        st.metric("참여율", f"{b['engagement_rate']:.1f}%")
        st.metric("언급 영상", f"{b['mentions']:,}건")
        st.metric("고유 크리에이터", f"{b['creators']:,}명")
        st.markdown("**오디언스 지역**")
        if b["regions"]:
            st.markdown(_region_bar(b["regions"], height=18), unsafe_allow_html=True)
            st.markdown(_colored_labels(b["regions"], _REGION_COLORS), unsafe_allow_html=True)
        else:
            st.caption("데이터 없음")
        if b.get("languages"):
            st.markdown("**댓글 언어**")
            st.markdown(_lang_bar(b["languages"], height=18), unsafe_allow_html=True)
            st.markdown(_colored_labels(b["languages"], _LANG_COLORS), unsafe_allow_html=True)

# ── 대표 콘텐츠 (조회수+참여수 상위 영상 임베드) ────────────────────────────
for b in compare:
    videos = b.get("top_videos") or []
    if not videos:
        continue
    st.markdown(f"##### 🎬 {b['name']} 대표 콘텐츠")
    st.caption("조회수·참여수 합산 기준 상위 영상입니다.")
    vcols = st.columns(len(videos))
    for col, v in zip(vcols, videos):
        with col:
            height = 620 if v["platform"] == "instagram" else 560
            st.markdown(
                f'<iframe src="{v["embed_url"]}" '
                f'style="width:100%;height:{height}px;border:none;" allowfullscreen></iframe>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"@{v['channel_username']}  ·  👁 {_fmt_num(v['views'])}  ❤️ {_fmt_num(v['likes'])}  "
                f"💬 {_fmt_num(v['comments'])}  🔁 {_fmt_num(v['shares'])}"
            )

st.divider()

st.markdown("##### 🌍 국가별 오디언스 분포 비교")
st.caption("브랜드별로 댓글을 남긴 오디언스가 어느 국가에 분포하는지 비교합니다.")
# 비교 대상 브랜드들이 실제로 갖고 있는 지역 코드 전체를 합집합으로, 비중 합이
# 높은 국가부터 정렬 (고정/알파벳 순이면 어느 국가가 실제로 비중이 큰지 한눈에 안 보임)
_region_keys = {r for b in compare for r in b["regions"].keys()}
region_labels = sorted(
    _region_keys, key=lambda r: sum(b["regions"].get(r, 0) for b in compare), reverse=True,
)
region_df = pd.DataFrame(
    {b["name"]: [b["regions"].get(r, 0) for r in region_labels] for b in compare},
    index=region_labels,
)
try:
    st.bar_chart(region_df, use_container_width=True, height=280,
                 color=[b["color"] for b in compare])
except TypeError:
    st.bar_chart(region_df, use_container_width=True, height=280)

st.divider()

# ── 댓글 분석 ─────────────────────────────────────────────────────────────
st.markdown("##### 💬 댓글 분석")
st.caption("브랜드 언급 콘텐츠의 댓글에서 추출한 주요 키워드")
cc = st.columns(len(compare))
for col, b in zip(cc, compare):
    with col:
        st.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        st.markdown(f"<div style='margin:6px 0'>{_keyword_tags(b['top_keywords'])}</div>", unsafe_allow_html=True)
