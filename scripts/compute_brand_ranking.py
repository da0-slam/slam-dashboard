"""브랜드 랭킹 실데이터 파이프라인 v2 — 공식 계정/해시태그 기반 대량 수집 + 댓글 지역/언어.

사용법:
    python scripts/compute_brand_ranking.py                   # 전체 브랜드 실행 (브랜드당 최대 max-items)
    python scripts/compute_brand_ranking.py --test             # 소량(5건) 스키마 검증용 테스트
    python scripts/compute_brand_ranking.py --max-items 2000   # 브랜드당 수집 목표 (기본 2000)
    python scripts/compute_brand_ranking.py --comment-sample 60 # 댓글 스크랩할 상위 영상 수 (기본 60)

방식 (2026-07-14 v2 — 공식 계정/해시태그 확보 후 확장):
    1. 브랜드별 공식 TikTok/Instagram 계정 + 공식 해시태그로 콘텐츠를 대량 수집
       (해시태그 검색 + 프로필 스크랩을 합쳐 최대 max-items건, 브랜드당 목표 2000건)
    2. 핵심 상품 2개는 영어 검색어로 캡션 텍스트를 매칭해 "이 콘텐츠가 어느 상품
       얘기인지" 태깅 (상품별 개수·인게이지먼트 = 매칭된 콘텐츠 집계)
    3. 상품 점수 = 개수·인게이지먼트를 정규화해 산출 (개수 40% + 인게이지먼트 60% — 임의 기본값)
    4. 브랜드 점수 = 핵심 상품 2개 점수의 평균
    5. 수집된 TikTok 영상 중 참여도 상위 N개의 댓글을 apidojo/tiktok-comments-scraper로
       수집해 댓글 작성자의 지역(user.region)·언어(user.language) 분포 집계
    6. 결과를 data/brand_ranking_snapshot.json에 저장 (pages/1_brand_ranking.py가 읽음)

주의:
    - 샤오홍슈는 제외 (검색 모드 쿠키/계정 리스크 — 기존 결정 유지).
    - Instagram은 해시태그/프로필 방문(directUrls) 방식만 지원 — 자유 텍스트 키워드
      검색은 이 액터가 지원하지 않음 (v1에서 확인됨).
    - 상품-콘텐츠 매칭은 캡션 텍스트에 상품 키워드가 포함되는지로 판단하는 휴리스틱이라
      정확도가 완벽하지 않음 (특히 브랜드 공식 계정 게시물은 상품명을 캡션에 안 적을 수도 있음).
    - 브랜드 공식 계정 (2026-07-14 확인):
        23yearsold    — TikTok: @23yearsold #23yearsold / Instagram: @23yo_global
        유이크(UIQ)    — TikTok+Instagram: @uiq_global #uiq
        리쥬올        — @rejuall_uk_official, @rejuall_official (플랫폼 미명시 — 둘 다 시도)
        헤브블루       — TikTok(추정): @Heveblue.us #HEVEBLUE / Instagram: @heveblue_cosmetic
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
if not APIFY_TOKEN:
    print("ERROR: APIFY_TOKEN 환경변수가 필요합니다 (.env에 추가하세요).")
    sys.exit(1)

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "brand_ranking_snapshot.json"

_TIKTOK_ACTOR = "clockworks~tiktok-scraper"
_INSTAGRAM_ACTOR = "apify~instagram-scraper"
_TT_COMMENTS_ACTOR = "apidojo~tiktok-comments-scraper"

# ── 브랜드 × 공식 계정/해시태그 + 핵심 상품 2개 ───────────────────────────────
BRANDS = [
    {
        "name": "23yearsold",
        "tiktok_hashtags": ["23yearsold"],
        "tiktok_profiles": ["23yearsold"],
        "instagram_profiles": ["23yo_global"],
        "products": [
            {"name": "더마 씬 컨실러", "keywords": ["derma thin concealer", "concealer"]},
            {"name": "하트리프 씬 쿠션", "keywords": ["heartleaf thin cushion", "heartleaf cushion"]},
        ],
    },
    {
        "name": "유이크(UIQ)",
        "tiktok_hashtags": ["uiq"],
        "tiktok_profiles": ["uiq_global"],
        "instagram_profiles": ["uiq_global"],
        "products": [
            {"name": "바이옴 베리어 크림 미스트", "keywords": ["biome barrier mist", "biome barrier"]},
            {"name": "콜라겐 퍼밍 클렌징밤", "keywords": ["collagen firming cleansing balm", "firming cleansing balm"]},
        ],
    },
    {
        "name": "리쥬올",
        "tiktok_hashtags": ["rejuall"],
        "tiktok_profiles": ["rejuall_official", "rejuall_uk_official"],
        "instagram_profiles": ["rejuall_official", "rejuall_uk_official"],
        "products": [
            {"name": "PDRN 리쥬버네이팅 크림", "keywords": ["pdrn rejuvenating cream", "pdrn cream"]},
            {"name": "레티노-멜라 세럼", "keywords": ["retino-mela serum", "retino mela serum"]},
        ],
    },
    {
        "name": "헤브블루",
        "tiktok_hashtags": ["heveblue"],
        "tiktok_profiles": ["Heveblue.us"],
        "instagram_profiles": ["heveblue_cosmetic"],
        "products": [
            {"name": "살몬 케어링 센텔라 토너", "keywords": ["salmon centella toner", "salmon centella"]},
            {"name": "살몬 케어링 센텔라 크림/앰플", "keywords": ["salmon centella ampoule", "salmon centella cream"]},
        ],
    },
]


def _run_apify_actor(actor: str, run_input: dict, timeout_s: int = 280) -> tuple[list | None, str]:
    try:
        resp = requests.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": APIFY_TOKEN, "timeout": timeout_s},
            json=run_input,
            timeout=timeout_s + 20,
        )
    except requests.RequestException as e:
        return None, f"요청 실패: {e}"
    if not resp.ok:
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        return resp.json(), "ok"
    except ValueError:
        return None, f"JSON 파싱 실패: {resp.text[:200]}"


# ── TikTok: 해시태그 / 프로필 대량 수집 ──────────────────────────────────────

def fetch_tiktok_hashtags(hashtags: list[str], max_items: int) -> tuple[list[dict], str]:
    run_input = {
        "hashtags": hashtags, "resultsPerPage": max_items,
        "shouldDownloadVideos": False, "shouldDownloadCovers": False,
    }
    items, reason = _run_apify_actor(_TIKTOK_ACTOR, run_input)
    if items is None:
        return [], reason
    return [it for it in items if not it.get("errorCode")], "ok"


def fetch_tiktok_profiles(usernames: list[str], max_items: int) -> tuple[list[dict], str]:
    run_input = {
        "profiles": usernames, "resultsPerPage": max_items,
        "shouldDownloadVideos": False, "shouldDownloadCovers": False,
    }
    items, reason = _run_apify_actor(_TIKTOK_ACTOR, run_input)
    if items is None:
        return [], reason
    return [it for it in items if not it.get("errorCode")], "ok"


# ── Instagram: 프로필 대량 수집 (자유 텍스트 검색 미지원, directUrls만 가능) ──

def fetch_instagram_profiles(usernames: list[str], max_items: int) -> tuple[list[dict], str]:
    urls = [f"https://www.instagram.com/{u}/" for u in usernames]
    run_input = {"directUrls": urls, "resultsType": "posts", "resultsLimit": max_items}
    items, reason = _run_apify_actor(_INSTAGRAM_ACTOR, run_input)
    if items is None:
        return [], reason
    return [it for it in items if not it.get("error")], "ok"


# ── TikTok 댓글: 지역/언어 ────────────────────────────────────────────────────

def fetch_tiktok_comments(video_urls: list[str], max_items: int) -> tuple[list[dict], str]:
    if not video_urls:
        return [], "ok (영상 없음)"
    run_input = {"startUrls": video_urls, "includeReplies": False, "maxItems": max_items}
    items, reason = _run_apify_actor(_TT_COMMENTS_ACTOR, run_input)
    if items is None:
        return [], reason
    return items, "ok"


# ── 집계 헬퍼 ─────────────────────────────────────────────────────────────────

def _tt_engagement(it: dict) -> int:
    stats = it.get("statsV2") or {}
    return (
        int(it.get("diggCount") or stats.get("diggCount") or 0)
        + int(it.get("commentCount") or stats.get("commentCount") or 0)
        + int(it.get("shareCount") or stats.get("shareCount") or 0)
    )


def _tt_views(it: dict) -> int:
    stats = it.get("statsV2") or {}
    return int(it.get("playCount") or stats.get("playCount") or 0)


def _ig_engagement(it: dict) -> int:
    return int(it.get("likesCount") or 0) + int(it.get("commentsCount") or 0)


def _ig_views(it: dict) -> int:
    return int(it.get("videoViewCount") or it.get("videoPlayCount") or 0)


def _dedupe_tiktok(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        vid = it.get("id") or it.get("webVideoUrl")
        if vid and vid not in seen:
            seen.add(vid)
            out.append(it)
    return out


def _dedupe_instagram(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        pid = it.get("id") or it.get("url")
        if pid and pid not in seen:
            seen.add(pid)
            out.append(it)
    return out


def _match_product(text: str, products: list[dict]) -> str | None:
    text_l = (text or "").lower()
    for p in products:
        if any(kw in text_l for kw in p["keywords"]):
            return p["name"]
    return None


def compute_product_score(count: int, engagement: int, max_count: int, max_engagement: int) -> float:
    """개수·인게이지먼트를 0~100으로 정규화 (개수 40% + 인게이지먼트 60% — 임의 기본값, 조정 가능)."""
    count_norm = (count / max_count * 100) if max_count else 0
    eng_norm = (engagement / max_engagement * 100) if max_engagement else 0
    return round(count_norm * 0.4 + eng_norm * 0.6, 1)


def process_brand(brand: dict, max_items: int, comment_sample: int) -> dict:
    name = brand["name"]
    print(f"=== [{name}] 콘텐츠 수집 ===")

    tt_items: list[dict] = []
    if brand.get("tiktok_hashtags"):
        got, reason = fetch_tiktok_hashtags(brand["tiktok_hashtags"], max_items)
        print(f"  TikTok 해시태그 {brand['tiktok_hashtags']}: {len(got)}건 ({reason})")
        tt_items += got
    if brand.get("tiktok_profiles"):
        got, reason = fetch_tiktok_profiles(brand["tiktok_profiles"], max_items)
        print(f"  TikTok 프로필 {brand['tiktok_profiles']}: {len(got)}건 ({reason})")
        tt_items += got
    tt_items = _dedupe_tiktok(tt_items)
    print(f"  TikTok 합계(중복 제거): {len(tt_items)}건")

    ig_items: list[dict] = []
    if brand.get("instagram_profiles"):
        got, reason = fetch_instagram_profiles(brand["instagram_profiles"], max_items)
        print(f"  Instagram 프로필 {brand['instagram_profiles']}: {len(got)}건 ({reason})")
        ig_items += got
    ig_items = _dedupe_instagram(ig_items)
    print(f"  Instagram 합계(중복 제거): {len(ig_items)}건")

    total_count = len(tt_items) + len(ig_items)
    total_views = sum(_tt_views(it) for it in tt_items) + sum(_ig_views(it) for it in ig_items)
    total_engagement = sum(_tt_engagement(it) for it in tt_items) + sum(_ig_engagement(it) for it in ig_items)
    unique_creators = len({it.get("authorMeta", {}).get("uniqueId") for it in tt_items if it.get("authorMeta")}) \
        + len({it.get("ownerUsername") for it in ig_items if it.get("ownerUsername")})

    # ── 핵심 상품 2개 매칭 (캡션 텍스트 키워드 기반) ─────────────────────────
    product_stats = {p["name"]: {"count": 0, "engagement": 0} for p in brand["products"]}
    for it in tt_items:
        matched = _match_product(it.get("text") or "", brand["products"])
        if matched:
            product_stats[matched]["count"] += 1
            product_stats[matched]["engagement"] += _tt_engagement(it)
    for it in ig_items:
        matched = _match_product((it.get("caption") or it.get("text") or ""), brand["products"])
        if matched:
            product_stats[matched]["count"] += 1
            product_stats[matched]["engagement"] += _ig_engagement(it)

    for p in brand["products"]:
        matched_n = product_stats[p["name"]]["count"]
        print(f"  상품 매칭 '{p['name']}': {matched_n}건")

    # ── 댓글 지역/언어 (참여도 상위 N개 TikTok 영상) ─────────────────────────
    top_videos = sorted(tt_items, key=_tt_engagement, reverse=True)[:comment_sample]
    video_urls = [v.get("webVideoUrl") for v in top_videos if v.get("webVideoUrl")]
    comments, c_reason = fetch_tiktok_comments(video_urls, max_items=comment_sample * 20)
    print(f"  댓글 수집: {len(comments)}건 (영상 {len(video_urls)}개 대상, {c_reason})")

    region_counter, lang_counter = Counter(), Counter()
    for c in comments:
        user = c.get("user") or {}
        if user.get("region"):
            region_counter[user["region"]] += 1
        lang = c.get("commentLanguage") or user.get("language")
        if lang:
            lang_counter[lang] += 1

    region_total = sum(region_counter.values()) or 1
    lang_total = sum(lang_counter.values()) or 1
    regions = {k: round(v / region_total * 100, 1) for k, v in region_counter.most_common(6)}
    languages = {k: round(v / lang_total * 100, 1) for k, v in lang_counter.most_common(6)}
    print(f"  지역 분포: {regions}")
    print(f"  언어 분포: {languages}")
    print()

    return {
        "brand": name,
        "total_count": total_count,
        "total_views": total_views,
        "total_engagement": total_engagement,
        "unique_creators": unique_creators,
        "products": [
            {"name": p["name"], "count": product_stats[p["name"]]["count"],
             "engagement": product_stats[p["name"]]["engagement"]}
            for p in brand["products"]
        ],
        "comment_sample_size": len(comments),
        "regions": regions,
        "languages": languages,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="소량(5건) 스키마 검증용 테스트")
    parser.add_argument("--max-items", type=int, default=2000, help="브랜드당 수집 목표 (기본 2000)")
    parser.add_argument("--comment-sample", type=int, default=60, help="댓글 스크랩할 상위 영상 수 (기본 60)")
    args = parser.parse_args()

    if args.test:
        print("=== 테스트 모드: 23yearsold, 결과 5건 ===\n")
        b = BRANDS[0]
        got, reason = fetch_tiktok_hashtags(b["tiktok_hashtags"], 5)
        print(f"[TikTok 해시태그] {len(got)}건 ({reason})")
        got2, reason2 = fetch_instagram_profiles(b["instagram_profiles"], 5)
        print(f"[Instagram 프로필] {len(got2)}건 ({reason2})")
        return

    print(f"=== 브랜드 랭킹 실데이터 파이프라인 v2 (브랜드당 목표 {args.max_items}건) ===\n")

    results = [process_brand(b, args.max_items, args.comment_sample) for b in BRANDS]

    max_count = max((r["total_count"] for r in results), default=0)
    max_engagement = max((r["total_engagement"] for r in results), default=0)

    # 상품 점수는 상품 매칭 결과들 중 최댓값 기준으로 정규화
    all_product_counts = [p["count"] for r in results for p in r["products"]]
    all_product_engagements = [p["engagement"] for r in results for p in r["products"]]
    max_p_count = max(all_product_counts, default=0)
    max_p_engagement = max(all_product_engagements, default=0)

    brand_scores = {}
    for r in results:
        for p in r["products"]:
            p["score"] = compute_product_score(p["count"], p["engagement"], max_p_count, max_p_engagement)
        brand_scores[r["brand"]] = round(sum(p["score"] for p in r["products"]) / len(r["products"]), 1) \
            if r["products"] else 0.0

    print("=== 결과 요약 ===")
    for name, score in sorted(brand_scores.items(), key=lambda x: x[1], reverse=True):
        r = next(x for x in results if x["brand"] == name)
        print(f"  {name}: 점수 {score}  ·  콘텐츠 {r['total_count']}건  ·  조회수 {r['total_views']:,}  ·  참여수 {r['total_engagement']:,}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"brands": results, "brand_scores": brand_scores}, f, ensure_ascii=False, indent=2)
    print(f"\n저장됨: {OUT_PATH}")


if __name__ == "__main__":
    main()
