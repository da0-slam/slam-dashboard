"""브랜드 랭킹 실데이터 파이프라인 — 핵심 상품 2개 기준 Apify 키워드 검색.

사용법:
    python scripts/compute_brand_ranking.py                 # 전체 브랜드 실행
    python scripts/compute_brand_ranking.py --test           # 상품 1개만 소량(5건) 테스트
    python scripts/compute_brand_ranking.py --max-results 30 # 상품당 결과 수 조정

방식 (2026-07-14 확정 설계):
    1. 브랜드별 핵심 상품 2개의 "영어" 검색어로 TikTok/Instagram을 검색
       (글로벌 타겟이라 한국어가 아닌 영어 키워드로 검색)
    2. 상품별 "개수"(검색된 영상/게시물 수)와 "인게이지먼트"(좋아요+댓글+공유 합) 집계
    3. 상품 점수 = 개수·인게이지먼트를 정규화해 산출
    4. 브랜드 점수 = 핵심 상품 2개 점수의 평균
    5. 결과를 data/brand_ranking_snapshot.json에 저장 (pages/1_brand_ranking.py가 읽음)

주의:
    - 샤오홍슈는 이번 파이프라인에서 제외 (검색 모드가 쿠키 없이는 불안정하고
      계정 정지 리스크가 있어 사용자가 TikTok+Instagram만 진행하기로 결정함).
    - Instagram은 TikTok과 달리 자유 텍스트 키워드 검색을 지원하지 않아
      해시태그 검색(hashtags 입력)으로 대체함 — 상품명을 해시태그 형태로 변환.
    - 브랜드 공식 영문명 확인 완료: 리쥬올 → Dr.Reju-All, 헤브블루 → HeveBlue.
"""
import argparse
import json
import os
import re
import sys
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

# ── 브랜드 × 핵심 상품 2개 (영어 검색어, 글로벌 타겟 기준) ────────────────────
# query: TikTok 자유 텍스트 검색용 (브랜드+상품명 — 특정도를 위해 브랜드명 포함).
# hashtag: Instagram 해시태그 검색용 (상품명만 — 실제로 테스트해서 브랜드+상품
#          조합 해시태그는 거의 안 쓰이는 걸 확인함, 상품명 단독이 결과가 더 잘 나옴).
BRANDS = [
    {
        "name": "23yearsold",
        "products": [
            {"name": "더마 씬 컨실러", "query": "Derma Thin Concealer 23yearsold", "hashtag": "DermaThinConcealer"},
            {"name": "하트리프 씬 쿠션", "query": "Heartleaf Thin Cushion 23yearsold", "hashtag": "HeartleafThinCushion"},
        ],
    },
    {
        "name": "유이크(UIQ)",
        "products": [
            {"name": "바이옴 베리어 크림 미스트", "query": "UIQ Biome Barrier Mist", "hashtag": "BiomeBarrierMist"},
            {"name": "콜라겐 퍼밍 클렌징밤", "query": "UIQ Collagen Firming Cleansing Balm", "hashtag": "CollagenFirmingCleansingBalm"},
        ],
    },
    {
        "name": "리쥬올",
        "products": [
            {"name": "PDRN 리쥬버네이팅 크림", "query": "Dr.Reju-All PDRN Rejuvenating Cream", "hashtag": "PDRNRejuvenatingCream"},
            {"name": "레티노-멜라 세럼", "query": "Dr.Reju-All Retino-Mela Serum", "hashtag": "RetinoMelaSerum"},
        ],
    },
    {
        "name": "헤브블루",
        "products": [
            {"name": "살몬 케어링 센텔라 토너", "query": "HeveBlue Salmon Centella Toner", "hashtag": "SalmonCentellaToner"},
            {"name": "살몬 케어링 센텔라 크림/앰플", "query": "HeveBlue Salmon Centella Ampoule", "hashtag": "SalmonCentellaAmpoule"},
        ],
    },
]

_TIKTOK_ACTOR = "clockworks~tiktok-scraper"
_INSTAGRAM_ACTOR = "apify~instagram-scraper"


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


def _to_hashtag(query: str) -> str:
    """검색어를 Instagram 해시태그 형태로 변환 (공백/특수문자 제거)."""
    return re.sub(r"[^a-zA-Z0-9]", "", query)


def search_tiktok(query: str, max_results: int) -> tuple[dict | None, str]:
    run_input = {
        "searchQueries": [query],
        "resultsPerPage": max_results,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }
    items, reason = _run_apify_actor(_TIKTOK_ACTOR, run_input)
    if items is None:
        return None, reason
    items = [it for it in items if not it.get("errorCode")]
    if not items:
        return {"count": 0, "engagement": 0, "views": 0}, "ok (결과 0건)"
    engagement = sum(
        int(it.get("diggCount") or 0) + int(it.get("commentCount") or 0) + int(it.get("shareCount") or 0)
        for it in items
    )
    views = sum(int(it.get("playCount") or 0) for it in items)
    return {"count": len(items), "engagement": engagement, "views": views}, "ok"


def search_instagram(hashtag: str, max_results: int) -> tuple[dict | None, str]:
    hashtag = _to_hashtag(hashtag)
    run_input = {
        "directUrls": [f"https://www.instagram.com/explore/tags/{hashtag}/"],
        "resultsType": "posts",
        "resultsLimit": max_results,
    }
    items, reason = _run_apify_actor(_INSTAGRAM_ACTOR, run_input)
    if items is None:
        return None, reason
    items = [it for it in items if not it.get("error")]
    if not items:
        return {"count": 0, "engagement": 0, "views": 0}, f"ok (결과 0건, 해시태그: #{hashtag})"
    engagement = sum(
        int(it.get("likesCount") or 0) + int(it.get("commentsCount") or 0)
        for it in items
    )
    views = sum(int(it.get("videoViewCount") or it.get("videoPlayCount") or 0) for it in items)
    return {"count": len(items), "engagement": engagement, "views": views}, "ok"


def compute_product_score(count: int, engagement: int, max_count: int, max_engagement: int) -> float:
    """개수·인게이지먼트를 0~100으로 정규화 (개수 40% + 인게이지먼트 60%)."""
    count_norm = (count / max_count * 100) if max_count else 0
    eng_norm = (engagement / max_engagement * 100) if max_engagement else 0
    return round(count_norm * 0.4 + eng_norm * 0.6, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="상품 1개만 소량(5건) 테스트")
    parser.add_argument("--max-results", type=int, default=30, help="상품당 검색 결과 수 (기본 30)")
    args = parser.parse_args()

    if args.test:
        print("=== 테스트 모드: 23yearsold의 첫 번째 상품만, 결과 5건 ===\n")
        p = BRANDS[0]["products"][0]
        print(f"[TikTok] 검색어: {p['query']}")
        tt_result, tt_reason = search_tiktok(p["query"], 5)
        print(f"  결과: {tt_result}  ({tt_reason})\n")
        print(f"[Instagram] 해시태그: #{p['hashtag']}")
        ig_result, ig_reason = search_instagram(p["hashtag"], 5)
        print(f"  결과: {ig_result}  ({ig_reason})")
        return

    max_results = args.max_results
    print(f"=== 브랜드 랭킹 실데이터 파이프라인 (상품당 결과 {max_results}건) ===\n")

    raw_results = []  # [{brand, product_name, query, tiktok:{count,engagement}, instagram:{...}}]
    for brand in BRANDS:
        for p in brand["products"]:
            print(f"[{brand['name']}] {p['name']}  (TikTok: {p['query']} / IG: #{p['hashtag']})")
            tt, tt_reason = search_tiktok(p["query"], max_results)
            print(f"  TikTok: {tt}  ({tt_reason})")
            ig, ig_reason = search_instagram(p["hashtag"], max_results)
            print(f"  Instagram: {ig}  ({ig_reason})")
            count = (tt or {}).get("count", 0) + (ig or {}).get("count", 0)
            engagement = (tt or {}).get("engagement", 0) + (ig or {}).get("engagement", 0)
            views = (tt or {}).get("views", 0) + (ig or {}).get("views", 0)
            raw_results.append({
                "brand": brand["name"], "product_name": p["name"], "query": p["query"],
                "count": count, "engagement": engagement, "views": views,
                "tiktok": tt, "instagram": ig,
            })
            print()

    max_count = max((r["count"] for r in raw_results), default=0)
    max_engagement = max((r["engagement"] for r in raw_results), default=0)

    for r in raw_results:
        r["score"] = compute_product_score(r["count"], r["engagement"], max_count, max_engagement)

    # 브랜드 점수 = 소속 상품 2개 점수 평균
    brand_scores = {}
    for brand in BRANDS:
        prods = [r for r in raw_results if r["brand"] == brand["name"]]
        brand_scores[brand["name"]] = round(sum(p["score"] for p in prods) / len(prods), 1) if prods else 0.0

    print("=== 결과 요약 ===")
    for name, score in sorted(brand_scores.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name}: {score}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"products": raw_results, "brand_scores": brand_scores}, f, ensure_ascii=False, indent=2)
    print(f"\n저장됨: {OUT_PATH}")


if __name__ == "__main__":
    main()
