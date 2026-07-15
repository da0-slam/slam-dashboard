"""브랜드 랭킹 — OWM 입점 브랜드 글로벌 영향력 스코어링.

실데이터 파이프라인 (2026-07-15 확정):
    라이브 Apify 검색(scripts/compute_brand_ranking.py)은 (1) 브랜드 공식
    계정을 스크랩하면 브랜드 자체 게시물만 나와 "제3자 UGC 영향력" 취지에
    안 맞고, (2) 해시태그가 브랜드명과 겹치는 일반 단어일 때(예: "23yearsold")
    무관한 콘텐츠가 섞이는 문제가 있어 보류. 대신:

    1. 사용자가 Apify 콘솔에서 직접 수집한 TikTok UGC 콘텐츠/댓글 데이터를
       Google Sheet(브랜드당 탭)로 export
    2. scripts/import_brand_ranking_sheet.py로 Supabase에 이관
       - "{브랜드}" 탭 → brand_ranking_content (콘텐츠: 조회수/좋아요/댓글/
         공유/해시태그/위치태그 등)
       - "{브랜드}-코멘트" 탭 → brand_ranking_comments (apidojo/tiktok-
         comments-scraper 형식: 댓글별 user_region/user_language — 콘텐츠
         위치태그보다 표본이 훨씬 크고 커버리지가 좋음, 예: 헤브블루 855개
         댓글 전부 지역 데이터 있음)
    3. 브랜드 랭킹 스코어 = 브랜드 전체 지표(조회수 40% + 참여수 25% + 참여율 15%
       + 언급수 10% + 고유 크리에이터수 10%)를 실데이터 브랜드 코호트 내에서
       정규화해 산출. ※ 애초 설계는 "핵심 상품 2개 점수의 평균"이었으나, 실데이터로
       확인해보니 상품명이 캡션에 잘 안 적히는 브랜드(예: 헤브블루 223건 중 9~11건만
       매칭)가 부당하게 저평가되는 문제가 있어 2026-07-15에 브랜드 전체 지표 기반으로
       전환함. 상품별 매칭 결과는 "핵심 상품 성과" 섹션에 참고용으로만 남김.
    4. 지역 분포는 댓글 기반(brand_ranking_comments)을 우선 사용, 없으면
       콘텐츠 위치태그로 폴백
    5. 핵심 키워드 = 콘텐츠 해시태그 빈도 top-N (fyp/viral 등 범용 태그는 제외)

    저장된 데이터가 있는 브랜드만 실값으로 표시되고, 나머지는 예시 데이터.
    감성·크리에이터 규모/플랫폼 비중/성별은 아직 별도 파이프라인이 없어
    예시 데이터임.
"""
import streamlit as st
import pandas as pd
from collections import Counter

from utils.supabase_client import (
    get_brand_ranking_content, get_brand_ranking_comments, get_brand_ranking_names,
)

st.set_page_config(page_title="브랜드 랭킹", page_icon="🏆", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def _load_ranking_content(brand_name: str) -> list[dict]:
    return get_brand_ranking_content(brand_name)


@st.cache_data(ttl=300, show_spinner=False)
def _load_ranking_comments(brand_name: str) -> list[dict]:
    return get_brand_ranking_comments(brand_name)


@st.cache_data(ttl=300, show_spinner=False)
def _ranking_brand_names() -> list[str]:
    return get_brand_ranking_names()


# 핵심 상품 2개 키워드 (scripts/compute_brand_ranking.py와 동일 — 캡션/해시태그 매칭용)
_PRODUCT_KEYWORDS = {
    "23yearsold": [
        ("더마 씬 컨실러", ["derma thin concealer", "concealer"]),
        ("하트리프 씬 쿠션", ["heartleaf thin cushion", "heartleaf cushion"]),
    ],
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

    return {
        "mentions": len(rows),
        "total_views": total_views,
        "total_engagement": total_engagement,
        "engagement_rate": (total_engagement / total_views * 100) if total_views else 0,
        "creators": creators,
        "product_stats": product_stats,
        "regions": regions,
        "region_sample_size": sum(region_counter.values()),
        "region_source": region_source,
        "languages": languages,
        "top_keywords": _top_hashtags(rows),
    }

# 앱 전체에서 재사용 중인 팔레트(_comment_avatar_color, 6_content_performance.py)와 동일 —
# 브랜드별 색을 화면 전체에서 고정 배정 (순위가 바뀌어도 색은 브랜드에 고정)
_PALETTE = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444"]

# ── MOCK 데이터 (추후 campaign_posts/koc_contents 집계로 교체) ──────────────
_MOCK_BRANDS = [
    {
        "name": "23yearsold", "score": 92.4, "prev_rank": 1,
        "total_views": 18_400_000, "total_engagement": 612_000,
        "mentions": 342, "creators": 58,
        "products": [
            {"name": "그린 컨실러", "count": 198, "engagement": 355_000, "score": 95.8},
            {"name": "선크림 스틱", "count": 144, "engagement": 257_000, "score": 89.0},
        ],
        "sentiment": {"positive": 71, "neutral": 22, "negative": 7},
        "trend": [8, 9, 9, 10, 11, 12, 13, 14, 15, 16, 17, 17, 18, 18.4],
        "ugc_pct": 34,
        "emotions": {"신뢰": 62, "설렘": 18, "놀라움": 12, "불만": 8},
        "regions": {"미국": 38, "한국": 22, "동남아": 18, "중국": 14, "기타": 8},
        "top_keywords": [("보습력", 128), ("흡수력", 97), ("끈적임 없음", 71), ("향", 45), ("가격", 33)],
        "top_comment": {"text": "이거 진짜 흡수 미쳤음... 끈적임 하나도 없어서 매일 씀", "author": "@skincare_luv", "likes": 1_204},
        "creator_tiers": {"나노(1만↓)": 42, "마이크로(1만~10만)": 34, "미드(10만~50만)": 17, "매크로(50만↑)": 7},
        "platform_mix": {"TikTok": 48, "Instagram": 40, "샤오홍슈": 12},
        "gender": {"여성": 82, "남성": 18},
    },
    {
        "name": "유이크(UIQ)", "score": 85.6, "prev_rank": 3,
        "total_views": 14_200_000, "total_engagement": 471_000,
        "mentions": 276, "creators": 45,
        "products": [
            {"name": "리페어 세럼", "count": 146, "engagement": 250_000, "score": 88.2},
            {"name": "배리어 크림", "count": 130, "engagement": 221_000, "score": 83.0},
        ],
        "sentiment": {"positive": 64, "neutral": 27, "negative": 9},
        "trend": [7, 7.4, 7.8, 8.2, 8.7, 9.3, 9.9, 10.4, 11.2, 11.8, 12.5, 13.1, 13.7, 14.2],
        "ugc_pct": 27,
        "emotions": {"신뢰": 54, "설렘": 22, "놀라움": 14, "불만": 10},
        "regions": {"한국": 40, "중국": 22, "미국": 20, "동남아": 12, "기타": 6},
        "top_keywords": [("탄력", 104), ("가성비", 88), ("성분", 62), ("트러블", 40), ("포장", 22)],
        "top_comment": {"text": "가격 대비 성분표가 너무 알짜라 재구매 각", "author": "@uiq_daily", "likes": 892},
        "creator_tiers": {"나노(1만↓)": 38, "마이크로(1만~10만)": 36, "미드(10만~50만)": 19, "매크로(50만↑)": 7},
        "platform_mix": {"TikTok": 35, "Instagram": 33, "샤오홍슈": 32},
        "gender": {"여성": 76, "남성": 24},
    },
    {
        "name": "닥터리쥬올", "score": 76.3, "prev_rank": 2,
        "total_views": 10_500_000, "total_engagement": 318_000,
        "mentions": 214, "creators": 36,
        "products": [
            {"name": "리프팅 앰플", "count": 111, "engagement": 166_000, "score": 79.6},
            {"name": "아이크림", "count": 103, "engagement": 152_000, "score": 73.0},
        ],
        "sentiment": {"positive": 59, "neutral": 30, "negative": 11},
        "trend": [5, 5.3, 5.6, 6, 6.4, 6.9, 7.3, 7.8, 8.3, 8.9, 9.4, 9.9, 10.2, 10.5],
        "ugc_pct": 21,
        "emotions": {"신뢰": 47, "설렘": 24, "놀라움": 16, "불만": 13},
        "regions": {"한국": 48, "중국": 25, "동남아": 15, "미국": 8, "기타": 4},
        "top_keywords": [("리프팅", 96), ("각질", 58), ("효과", 51), ("자극", 29), ("향", 18)],
        "top_comment": {"text": "일주일 써보니 각질이 확실히 줄었어요, 자극도 없고", "author": "@rejuall_kr", "likes": 615},
        "creator_tiers": {"나노(1만↓)": 46, "마이크로(1만~10만)": 33, "미드(10만~50만)": 15, "매크로(50만↑)": 6},
        "platform_mix": {"TikTok": 20, "Instagram": 38, "샤오홍슈": 42},
        "gender": {"여성": 79, "남성": 21},
    },
    {
        "name": "헤브블루", "score": 65.8, "prev_rank": 4,
        "total_views": 6_800_000, "total_engagement": 192_000,
        "mentions": 143, "creators": 24,
        "products": [
            {"name": "클렌징밤", "count": 76, "engagement": 102_000, "score": 69.4},
            {"name": "토너패드", "count": 67, "engagement": 90_000, "score": 62.2},
        ],
        "sentiment": {"positive": 52, "neutral": 33, "negative": 15},
        "trend": [3, 3.2, 3.4, 3.7, 4.0, 4.3, 4.6, 5.0, 5.3, 5.7, 6.0, 6.3, 6.6, 6.8],
        "ugc_pct": 14,
        "emotions": {"신뢰": 38, "설렘": 19, "놀라움": 21, "불만": 22},
        "regions": {"한국": 55, "동남아": 20, "중국": 15, "미국": 6, "기타": 4},
        "top_keywords": [("향", 61), ("촉감", 47), ("가격", 40), ("트러블", 34), ("배송", 15)],
        "top_comment": {"text": "향은 진짜 좋은데 가격이 좀 부담스럽긴 해요", "author": "@blue_review", "likes": 348},
        "creator_tiers": {"나노(1만↓)": 51, "마이크로(1만~10만)": 31, "미드(10만~50만)": 13, "매크로(50만↑)": 5},
        "platform_mix": {"TikTok": 15, "Instagram": 45, "샤오홍슈": 40},
        "gender": {"여성": 71, "남성": 29},
    },
]
for i, b in enumerate(_MOCK_BRANDS):
    b["color"] = _PALETTE[i % len(_PALETTE)]

# ── 실데이터 병합 (Supabase brand_ranking_content에 데이터가 있으면 실값으로 교체) ──
# 시트 탭 이름과 화면 표시명이 다를 경우를 위한 별칭 매핑 (현재는 이름 통일로 비어있음)
_BRAND_NAME_ALIASES: dict[str, str] = {}

_real_brand_names = set(_ranking_brand_names())
HAS_REAL_DATA = bool(_real_brand_names)

_real_computed: dict[str, dict] = {}
for b in _MOCK_BRANDS:
    _lookup_name = _BRAND_NAME_ALIASES.get(b["name"], b["name"])
    if _lookup_name not in _real_brand_names:
        continue
    rows = _load_ranking_content(_lookup_name)
    if not rows:
        continue
    comment_rows = _load_ranking_comments(_lookup_name)
    computed = _compute_brand_from_content(b["name"], rows, comment_rows)
    _real_computed[b["name"]] = computed

# 상품별 성과표(참고용)에 쓰는 점수 — 개수/인게이지먼트를 상품 코호트 내에서 정규화.
# ⚠️ 랭킹 스코어에는 더 이상 쓰지 않음: 상품명 키워드 매칭은 브랜드마다 커버리지
# 편차가 커서(예: 헤브블루는 223건 중 9~11건만 매칭, 닥터리쥬올은 479건 중 360건)
# 이걸로 전체 점수를 매기면 실제 성과와 무관하게 왜곡됨 (2026-07-15 실데이터로 확인).
_all_product_counts = [s["count"] for c in _real_computed.values() for s in c["product_stats"].values()]
_all_product_engagements = [s["engagement"] for c in _real_computed.values() for s in c["product_stats"].values()]
_max_p_count = max(_all_product_counts, default=0)
_max_p_engagement = max(_all_product_engagements, default=0)


def _product_score(count: int, engagement: int) -> float:
    count_norm = (count / _max_p_count * 100) if _max_p_count else 0
    eng_norm = (engagement / _max_p_engagement * 100) if _max_p_engagement else 0
    return round(count_norm * 0.4 + eng_norm * 0.6, 1)


# 브랜드 랭킹 스코어 — 브랜드 전체 지표(조회수/참여수/참여율/언급수/크리에이터 수)를
# 실데이터 브랜드 코호트 내에서 정규화해 산출. 상품 키워드 매칭에 좌우되지 않음.
_max_views = max((c["total_views"] for c in _real_computed.values()), default=0)
_max_engagement = max((c["total_engagement"] for c in _real_computed.values()), default=0)
_max_rate = max((c["engagement_rate"] for c in _real_computed.values()), default=0)
_max_mentions = max((c["mentions"] for c in _real_computed.values()), default=0)
_max_creators = max((c["creators"] for c in _real_computed.values()), default=0)


# 스코어 산정 기준 — 화면의 "📐 스코어 산정 기준" 설명 박스와 반드시 같이 수정할 것
_SCORE_WEIGHTS = [
    ("조회수 (Reach)", 0.40, "총 조회수 — 콘텐츠가 얼마나 많은 사람에게 도달했는지"),
    ("참여수 (Engagement)", 0.25, "좋아요+댓글+공유 합 — 실제 반응의 절대량"),
    ("참여율 (Engagement Rate)", 0.15, "참여수 ÷ 조회수 — 도달 대비 반응 품질"),
    ("언급 콘텐츠 수 (Volume)", 0.10, "브랜드가 언급된 콘텐츠 건수 — 확산 폭"),
    ("고유 크리에이터 수 (Creator Diversity)", 0.10, "브랜드를 언급한 서로 다른 계정 수 — 특정 계정 의존도가 낮을수록 유리"),
]


def _brand_score(c: dict) -> float:
    v = (c["total_views"] / _max_views * 100) if _max_views else 0
    e = (c["total_engagement"] / _max_engagement * 100) if _max_engagement else 0
    r = (c["engagement_rate"] / _max_rate * 100) if _max_rate else 0
    m = (c["mentions"] / _max_mentions * 100) if _max_mentions else 0
    cr = (c["creators"] / _max_creators * 100) if _max_creators else 0
    weights = {name: w for name, w, _ in _SCORE_WEIGHTS}
    return round(
        v * weights["조회수 (Reach)"]
        + e * weights["참여수 (Engagement)"]
        + r * weights["참여율 (Engagement Rate)"]
        + m * weights["언급 콘텐츠 수 (Volume)"]
        + cr * weights["고유 크리에이터 수 (Creator Diversity)"],
        1,
    )


for b in _MOCK_BRANDS:
    computed = _real_computed.get(b["name"])
    if not computed:
        continue
    products = [
        {"name": name, "count": stats["count"], "engagement": stats["engagement"],
         "score": _product_score(stats["count"], stats["engagement"])}
        for name, stats in computed["product_stats"].items()
    ]
    b["products"] = products
    b["score"] = _brand_score(computed)
    b["mentions"] = computed["mentions"]
    b["total_engagement"] = computed["total_engagement"]
    b["total_views"] = computed["total_views"]
    b["creators"] = computed["creators"]
    if computed["regions"]:
        b["regions"] = computed["regions"]
        b["region_sample_size"] = computed["region_sample_size"]
        b["region_source"] = computed["region_source"]
    if computed["languages"]:
        b["languages"] = computed["languages"]
    if computed["top_keywords"]:
        b["top_keywords"] = computed["top_keywords"]

# 지역 색상 — 목업(한국/미국/...)과 실데이터(US/PH/... ISO 코드)가 섞여 있으므로,
# 병합이 끝난 뒤 실제로 등장하는 모든 지역 키에 카테고리 팔레트를 순서대로 배정
# (고정 딕셔너리로 두면 ISO 코드가 전부 매칭 안 돼 회색 하나로 뭉쳐 보이는 문제가 있었음).
_REGION_PALETTE = [
    "#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#ef4444",
    "#8b5cf6", "#14b8a6", "#f97316", "#06b6d4", "#84cc16", "#e11d48",
]
_all_region_keys = sorted({k for b in _MOCK_BRANDS for k in b.get("regions", {}).keys()})
_REGION_COLORS = {k: _REGION_PALETTE[i % len(_REGION_PALETTE)] for i, k in enumerate(_all_region_keys)}

# 언어도 지역과 같은 방식으로 실제 등장하는 언어 코드에 팔레트를 순서대로 배정
# (지역과 겹치지 않게 팔레트 뒤에서부터 배정해 인접 색이 덜 겹치도록 함)
_all_lang_keys = sorted({k for b in _MOCK_BRANDS for k in b.get("languages", {}).keys()})
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


def _rank_change_html(prev_rank: int, cur_rank: int) -> str:
    delta = prev_rank - cur_rank
    if delta > 0:
        return f"<span style='color:#10b981;font-weight:600;'>▲{delta}</span>"
    if delta < 0:
        return f"<span style='color:#ef4444;font-weight:600;'>▼{abs(delta)}</span>"
    return "<span style='color:#9ca3af;'>─</span>"


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


if HAS_REAL_DATA:
    _missing = [
        b["name"] for b in _MOCK_BRANDS
        if _BRAND_NAME_ALIASES.get(b["name"], b["name"]) not in _real_brand_names
    ]
    st.caption(
        "✅ 스코어·핵심 상품 성과·조회수·참여수·언급수·지역·오디언스 국가·핵심 키워드는 Supabase에 저장된 "
        f"실제 TikTok UGC/댓글 데이터입니다 ({', '.join(sorted(_real_brand_names))}). "
        + (f"🚧 {', '.join(_missing)}는 아직 데이터가 없어 예시 값입니다. " if _missing else "")
        + "🚧 감성·크리에이터 규모/플랫폼 비중/성별은 아직 예시 데이터입니다."
    )
else:
    st.caption("🚧 임시 화면입니다.")

open_brand = st.session_state.get("rank_open_brand")

# ═══════════════════════════════════════════════════════════════════════════
# 랭킹 목록 뷰
# ═══════════════════════════════════════════════════════════════════════════

if not open_brand:
    st.title("🏆 브랜드 랭킹")
    st.caption("OWM(오프라인 매장) 입점 브랜드의 글로벌 영향력을 스코어링해 비교합니다.")

    with st.expander("📐 스코어 산정 기준", expanded=False):
        st.markdown(
            "브랜드 스코어(0~100)는 아래 5개 지표를 **현재 추적 중인 브랜드들 사이에서 상대적으로 정규화**"
            "(최고값=100 기준)한 뒤 가중합해 산출합니다. 브랜드가 추가/제외되면 다른 브랜드의 점수도 "
            "함께 바뀔 수 있습니다 (절대 점수가 아니라 상대 비교 지표)."
        )
        for name, weight, desc in _SCORE_WEIGHTS:
            st.markdown(f"- **{name} {weight*100:.0f}%** — {desc}")
        st.caption(
            "데이터 출처: TikTok 공식 해시태그/UGC 콘텐츠 + 댓글(Apify 수집, Supabase 저장). "
            "핵심 상품 2개 단위 매칭은 참고용으로만 별도 표시하며 이 스코어 산정에는 포함되지 않습니다."
        )

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
    st.caption("변동은 전 기간(직전 집계 주기) 순위 대비입니다.")
    hc = st.columns([1, 1, 3, 2, 2, 2, 2, 3, 1])
    for col, label in zip(hc, ["순위", "변동", "브랜드", "스코어", "조회수", "참여수", "언급 영상", "감성", ""]):
        col.markdown(f"**{label}**")

    for rank, b in enumerate(ranked, 1):
        c = st.columns([1, 1, 3, 2, 2, 2, 2, 3, 1])
        c[0].markdown(f"**{rank}**")
        c[1].markdown(_rank_change_html(b["prev_rank"], rank), unsafe_allow_html=True)
        c[2].markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        c[3].markdown(f"**{b['score']:.1f}**")
        c[4].markdown(_fmt_num(b["total_views"]))
        c[5].markdown(_fmt_num(b["total_engagement"]))
        c[6].markdown(f"{b['mentions']:,}건")
        with c[7]:
            st.markdown(_sentiment_bar(b["sentiment"]), unsafe_allow_html=True)
        if c[8].button("열기", key=f"rank_open_{b['name']}", use_container_width=True):
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

    st.divider()

    # ── 국가별 오디언스 분포 ─────────────────────────────────────────────
    st.markdown("##### 🌍 국가별 오디언스 분포")
    st.caption(
        "이 브랜드 콘텐츠에 실제로 댓글을 남긴 오디언스가 어느 국가에 있는지 보여줍니다 "
        "(위치 태그가 있는 경우 콘텐츠 자체 위치로 보완). "
        "광고 없이 이미 여러 국가에서 유기적으로 반응이 일어나고 있다는 근거로 볼 수 있습니다."
    )
    for b in ranked:
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
    for b in ranked:
        lc, rc = st.columns([1, 5])
        lc.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        with rc:
            st.markdown(_keyword_tags(b["top_keywords"]), unsafe_allow_html=True)

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

# 비교 중인 브랜드들 사이에서의 순위(변동 계산 기준)
_ranked_all = sorted(_MOCK_BRANDS, key=lambda x: x["score"], reverse=True)
_rank_of = {b["name"]: i + 1 for i, b in enumerate(_ranked_all)}

st.title("🏆 브랜드 비교")

with st.expander("📐 스코어 산정 기준", expanded=False):
    for name, weight, desc in _SCORE_WEIGHTS:
        st.markdown(f"- **{name} {weight*100:.0f}%** — {desc}")
    st.caption("현재 추적 중인 브랜드들 사이의 상대 비교 지표이며, 상품 매칭 결과는 반영되지 않습니다.")

# ── 핵심 상품 성과 (참고용 — 랭킹 스코어에는 반영되지 않음) ─────────────────
st.markdown("##### 🔎 핵심 상품 성과")
st.caption(
    "핵심 상품 2개의 이름이 캡션·해시태그에 언급된 콘텐츠만 집계한 참고용 지표입니다. "
    "⚠️ 브랜드 랭킹 스코어에는 반영되지 않습니다 — 실제 콘텐츠에서 상품명을 캡션에 "
    "잘 안 적는 브랜드는 매칭 건수가 적게 잡혀 저평가될 수 있어(예: 헤브블루는 223건 중 "
    "9~11건만 매칭) 상품 단위 비교보다는 브랜드 전체 지표를 신뢰하는 게 안전합니다."
)
pc = st.columns(len(compare))
for col, b in zip(pc, compare):
    with col:
        st.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        prod_df = pd.DataFrame([
            {"상품명": p["name"], "개수": p["count"], "인게이지먼트": _fmt_num(p["engagement"]), "매칭 점수": p["score"]}
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
        st.metric("글로벌 영향력 스코어", f"{b['score']:.1f}")
        st.markdown(
            f"전체 {_rank_of[b['name']]}위  ·  전 기간 대비 {_rank_change_html(b['prev_rank'], _rank_of[b['name']])}",
            unsafe_allow_html=True,
        )
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

st.divider()

st.markdown("##### 🌍 국가별 오디언스 분포 비교")
st.caption("브랜드별로 댓글을 남긴 오디언스가 어느 국가에 분포하는지 비교합니다.")
# 비교 대상 브랜드들이 실제로 갖고 있는 지역 코드 전체를 합집합으로 (고정 목록이면
# 실데이터 브랜드의 ISO 국가코드가 다 0으로 잡히는 문제가 있어 동적으로 구성)
region_labels = sorted({r for b in compare for r in b["regions"].keys()})
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

# ── 댓글 분석 ─────────────────────────────────────────────────────────────
st.markdown("##### 💬 댓글 분석")
st.caption("브랜드 언급 콘텐츠의 댓글에서 추출한 주요 키워드와 최다 좋아요 댓글")
cc = st.columns(len(compare))
for col, b in zip(cc, compare):
    with col:
        st.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        st.markdown(f"<div style='margin:6px 0'>{_keyword_tags(b['top_keywords'])}</div>", unsafe_allow_html=True)
        tc = b["top_comment"]
        st.markdown(f"> {tc['text']}")
        st.caption(f"{tc['author']}  ·  ❤️ {tc['likes']:,}")

st.divider()

# ── 오디언스 분석 ─────────────────────────────────────────────────────────
st.markdown("##### 👥 오디언스 분석")
st.caption("언급 콘텐츠를 만든 크리에이터/시청자 구성")

ac1, ac2, ac3 = st.columns(3)
with ac1:
    st.markdown("**크리에이터 규모 분포**")
    tier_labels = list(compare[0]["creator_tiers"].keys()) if compare else []
    tier_df = pd.DataFrame(
        {b["name"]: [b["creator_tiers"].get(t, 0) for t in tier_labels] for b in compare},
        index=tier_labels,
    )
    try:
        st.bar_chart(tier_df, use_container_width=True, height=260,
                     color=[b["color"] for b in compare])
    except TypeError:
        st.bar_chart(tier_df, use_container_width=True, height=260)

with ac2:
    st.markdown("**플랫폼 비중**")
    plat_labels = list(compare[0]["platform_mix"].keys()) if compare else []
    plat_df = pd.DataFrame(
        {b["name"]: [b["platform_mix"].get(p, 0) for p in plat_labels] for b in compare},
        index=plat_labels,
    )
    try:
        st.bar_chart(plat_df, use_container_width=True, height=260,
                     color=[b["color"] for b in compare])
    except TypeError:
        st.bar_chart(plat_df, use_container_width=True, height=260)

with ac3:
    st.markdown("**시청자 성별 비중**")
    for b in compare:
        st.markdown(f"{_dot(b['color'])}**{b['name']}**", unsafe_allow_html=True)
        st.progress(
            b["gender"].get("여성", 0) / 100,
            text=f"여성 {b['gender'].get('여성', 0)}%  ·  남성 {b['gender'].get('남성', 0)}%",
        )

st.divider()

with st.expander("🤖 AI 요약 (최다 좋아요 댓글 기반)", expanded=True):
    st.caption("아래는 예시 텍스트입니다. 실제 연동 시 좋아요 상위 댓글을 모델에 전달해 요약을 생성합니다.")
    st.markdown(
        "> 소비자들은 전반적으로 **보습력과 흡수 속도**를 가장 많이 언급했습니다. "
        "특히 **23yearsold**와 **유이크(UIQ)**는 '끈적임 없음'에 대한 긍정 언급이 두드러졌고, "
        "**헤브블루**는 향에 대한 호불호가 갈리는 댓글이 상대적으로 많았습니다."
    )
