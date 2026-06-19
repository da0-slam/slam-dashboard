"""
koc_contents 썸네일 스크랩 (TikTok oEmbed + Instagram imginn/picuki/embed 체인)

Usage:
    python scripts/scrape_koc_thumbnails.py              # supabase 썸네일 없는 전체
    python scripts/scrape_koc_thumbnails.py --platform tiktok
    python scripts/scrape_koc_thumbnails.py --platform instagram
    python scripts/scrape_koc_thumbnails.py --limit 50
    python scripts/scrape_koc_thumbnails.py --all        # 기존 썸네일도 덮어쓰기
"""
import os
import re
import sys
import time
import argparse

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


def _fetch_rows(extra_params: dict, limit: int, platform: str | None) -> list[dict]:
    params = {
        "select": "influencer_id,video_url,thumbnail_url,posted_at",
        "order":  "posted_at.desc.nullslast",
        "limit":  limit,
        **extra_params,
    }
    if platform:
        params["video_url"] = f"like.*{platform}*"
    r = requests.get(f"{REST}/koc_contents", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_rows(platform: str | None, force: bool, limit: int) -> list[dict]:
    if force:
        return _fetch_rows({}, limit, platform)

    # NULL 썸네일 + supabase 아닌 외부 URL 각각 조회 후 합산
    null_rows = _fetch_rows({"thumbnail_url": "is.null"}, limit, platform)
    ext_rows  = _fetch_rows({"thumbnail_url": "not.like.*supabase*"}, limit, platform)
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
    parser.add_argument("--platform", choices=["tiktok", "instagram"], help="플랫폼 필터")
    parser.add_argument("--limit", type=int, default=200, help="처리 최대 수 (기본 200)")
    parser.add_argument("--all", dest="force", action="store_true", help="기존 썸네일도 재스크랩")
    parser.add_argument("--dry-run", action="store_true", help="실제 스크랩 없이 대상 목록만 출력")
    args = parser.parse_args()

    rows = get_rows(args.platform, args.force, args.limit)
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

    ok = fail = skip = 0

    for i, row in enumerate(rows, 1):
        iid   = row["influencer_id"]
        vurl  = row["video_url"]
        is_ig = "instagram.com" in vurl

        post_id = extract_post_id(vurl)
        if not post_id:
            print(f"[{i}/{total}] @{iid}: post_id 추출 불가 → 스킵")
            skip += 1
            continue

        plat_tag = "IG" if is_ig else "TT"
        print(f"[{i}/{total}] [{plat_tag}] @{iid} / {post_id}", end="  ", flush=True)

        try:
            saved = fetch_and_upload_thumbnail(vurl, iid, post_id)
        except Exception as e:
            print(f"오류: {e}")
            fail += 1
            time.sleep(2 if is_ig else 0.5)
            continue

        if saved:
            if update_row(vurl, saved):
                print("OK")
                ok += 1
            else:
                print("WARN DB 업데이트 실패")
                fail += 1
        else:
            print("FAIL")
            fail += 1

        time.sleep(3 if is_ig else 0.5)

    print(f"\n{'-'*40}")
    print(f"완료: OK {ok}  FAIL {fail}  스킵 {skip}  / 전체 {total}")


if __name__ == "__main__":
    main()
