"""
koc_contents 썸네일 스크랩 (TikTok oEmbed + Instagram imginn/picuki/embed 체인)

Usage:
    python scripts/scrape_koc_thumbnails.py                        # 전체 (썸네일 없는 것)
    python scripts/scrape_koc_thumbnails.py --campaign "미들US"    # 특정 캠페인 인플 한정
    python scripts/scrape_koc_thumbnails.py --platform tiktok
    python scripts/scrape_koc_thumbnails.py --platform instagram
    python scripts/scrape_koc_thumbnails.py --limit 50
    python scripts/scrape_koc_thumbnails.py --all                  # 기존 썸네일도 덮어쓰기
"""
import os
import re
import sys
import time
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: .env 파일에 SUPABASE_URL, SUPABASE_KEY 설정 필요")
    sys.exit(1)

from utils.storage_client import fetch_and_upload_thumbnail, extract_post_id

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"


def get_campaign_influencer_ids(campaign_name: str = "", campaign_id: str = "") -> list[str]:
    """캠페인 이름(부분 일치) 또는 ID로 influencer_id 목록 반환."""
    if campaign_id:
        camp = {"id": campaign_id, "name": campaign_id}
    else:
        r = requests.get(
            f"{REST}/campaigns",
            headers=HEADERS,
            params={"select": "id,name", "name": f"ilike.*{campaign_name}*", "limit": "20"},
            timeout=15,
        )
        r.raise_for_status()
        camps = r.json()
        if not camps:
            print(f"캠페인을 찾을 수 없습니다: {campaign_name}")
            sys.exit(1)
        if len(camps) > 1:
            print("여러 캠페인이 매칭됩니다. 더 구체적으로 입력하세요:")
            for c in camps:
                print(f"  - {c['name']}")
            sys.exit(1)
        camp = camps[0]
    print(f"캠페인: {camp['name']} (id={camp['id']})")

    # campaign_selections에서 influencer_id 목록 조회
    r2 = requests.get(
        f"{REST}/campaign_selections",
        headers=HEADERS,
        params={"select": "influencer_id", "campaign_id": f"eq.{camp['id']}", "limit": "2000"},
        timeout=15,
    )
    r2.raise_for_status()
    ids = [row["influencer_id"] for row in r2.json()]
    print(f"캠페인 인플루언서: {len(ids)}명\n")
    return ids


def _fetch_rows(extra_params: dict, limit: int, platform: str | None,
                influencer_ids: list[str] | None = None) -> list[dict]:
    params = {
        "select": "influencer_id,video_url,thumbnail_url,posted_at",
        "order":  "posted_at.desc.nullslast",
        "limit":  limit,
        **extra_params,
    }
    if platform:
        params["video_url"] = f"like.*{platform}*"
    if influencer_ids:
        params["influencer_id"] = f"in.({','.join(influencer_ids)})"
    r = requests.get(f"{REST}/koc_contents", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_rows(platform: str | None, force: bool, limit: int,
             influencer_ids: list[str] | None = None) -> list[dict]:
    if force:
        return _fetch_rows({}, limit, platform, influencer_ids)

    # NULL 썸네일 + supabase 아닌 외부 URL 각각 조회 후 합산
    null_rows = _fetch_rows({"thumbnail_url": "is.null"}, limit, platform, influencer_ids)
    ext_rows  = _fetch_rows({"thumbnail_url": "not.like.*supabase*"}, limit, platform, influencer_ids)
    # not.like는 NULL을 제외하므로 중복 없음
    seen, combined = set(), []
    for row in null_rows + ext_rows:
        key = row["video_url"]
        if key not in seen:
            seen.add(key)
            combined.append(row)
    return combined[:limit]


def update_row(video_url: str, thumb_url: str) -> bool:
    r = requests.patch(
        f"{REST}/koc_contents",
        headers=HEADERS,
        params={"video_url": f"eq.{video_url}"},
        json={"thumbnail_url": thumb_url},
        timeout=15,
    )
    return r.status_code in (200, 204)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", help="캠페인 이름 (부분 일치) — 해당 캠페인 인플루언서만 처리")
    parser.add_argument("--campaign-id", dest="campaign_id", help="캠페인 UUID (정확한 ID)")
    parser.add_argument("--platform", choices=["tiktok", "instagram"], help="플랫폼 필터")
    parser.add_argument("--limit", type=int, default=2000, help="처리 최대 수 (기본 2000)")
    parser.add_argument("--all", dest="force", action="store_true", help="기존 썸네일도 재스크랩")
    parser.add_argument("--dry-run", action="store_true", help="실제 스크랩 없이 대상 목록만 출력")
    parser.add_argument("--workers", type=int, default=8, help="TikTok 병렬 워커 수 (기본 8, Instagram은 고정 2)")
    parser.add_argument("--influencer", help="특정 influencer_id만 처리 (쉼표 구분 가능)")
    args = parser.parse_args()

    influencer_ids = None
    if args.influencer:
        influencer_ids = [i.strip() for i in args.influencer.split(",") if i.strip()]
    elif args.campaign_id or args.campaign:
        influencer_ids = get_campaign_influencer_ids(
            campaign_name=args.campaign or "",
            campaign_id=args.campaign_id or "",
        )
        if not influencer_ids:
            print("캠페인에 등록된 인플루언서가 없습니다.")
            return

    rows = get_rows(args.platform, args.force, args.limit, influencer_ids)
    total = len(rows)
    print(f"썸네일 없는 항목: {total}개\n")

    if not rows:
        print("처리할 항목 없음.")
        return

    if args.dry_run:
        for r in rows:
            plat = "IG" if "instagram" in r["video_url"] else "TT"
            print(f"  [{plat}] @{r['influencer_id']}  {r['video_url']}")
        return

    # TikTok / Instagram 분리
    tt_rows = [r for r in rows if "instagram.com" not in r["video_url"]]
    ig_rows = [r for r in rows if "instagram.com"     in r["video_url"]]
    print(f"  TikTok {len(tt_rows)}개 (워커 {args.workers}개)  |  Instagram {len(ig_rows)}개 (워커 2개)\n")

    counters = {"ok": 0, "fail": 0, "skip": 0}
    lock     = threading.Lock()
    done_idx = [0]

    def _process(row):
        iid   = row["influencer_id"]
        vurl  = row["video_url"]
        is_ig = "instagram.com" in vurl

        post_id = extract_post_id(vurl)
        if not post_id:
            with lock:
                counters["skip"] += 1
                done_idx[0] += 1
            print(f"@{iid}: post_id 추출 불가 → 스킵")
            return

        plat_tag = "IG" if is_ig else "TT"
        with lock:
            done_idx[0] += 1
            idx = done_idx[0]
        print(f"[{idx}/{total}] [{plat_tag}] @{iid} / {post_id}", end="  ", flush=True)

        try:
            saved = fetch_and_upload_thumbnail(vurl, iid, post_id)
        except Exception as e:
            print(f"오류: {e}")
            with lock:
                counters["fail"] += 1
            time.sleep(1.5 if is_ig else 0.3)
            return

        if saved:
            if update_row(vurl, saved):
                print("OK")
                with lock:
                    counters["ok"] += 1
            else:
                print("WARN DB 업데이트 실패")
                with lock:
                    counters["fail"] += 1
        else:
            print("FAIL")
            with lock:
                counters["fail"] += 1

        # Instagram은 rate limit 주의, TikTok은 빠르게
        time.sleep(1.5 if is_ig else 0.3)

    # TikTok: 병렬 처리
    if tt_rows:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_process, r): r for r in tt_rows}
            for f in as_completed(futs):
                if f.exception():
                    with lock:
                        counters["fail"] += 1

    # Instagram: 실패 최소화를 위해 2개 워커로 제한
    if ig_rows:
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = {ex.submit(_process, r): r for r in ig_rows}
            for f in as_completed(futs):
                if f.exception():
                    with lock:
                        counters["fail"] += 1

    print(f"\n{'-'*40}")
    print(f"완료: OK {counters['ok']}  FAIL {counters['fail']}  스킵 {counters['skip']}  / 전체 {total}")


if __name__ == "__main__":
    main()
