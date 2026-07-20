"""
Apify Instagram Dataset → Supabase koc_contents 임포트
images/0 썸네일을 즉시 Supabase Storage에 영구 저장 후 thumbnail_url에 반영

사용법:
  python scripts/import_instagram_dataset.py <DATASET_ID>
  python scripts/import_instagram_dataset.py <DATASET_ID> --limit 50
  python scripts/import_instagram_dataset.py <DATASET_ID> --skip-thumb   # 썸네일 생략
"""

import os
import re
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from utils.storage_client import upload_thumbnail

APIFY_TOKEN  = os.environ.get("APIFY_TOKEN", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([APIFY_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: APIFY_TOKEN, SUPABASE_URL, SUPABASE_KEY 환경변수 설정 필요")
    sys.exit(1)

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates,return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"


# ── Apify Dataset 로드 ────────────────────────────────────────────────────────

def fetch_dataset(dataset_id: str) -> list[dict]:
    print(f"Apify Dataset {dataset_id} 로딩 중...")
    items, offset, limit = [], 0, 1000
    while True:
        resp = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
            params={"token": APIFY_TOKEN, "offset": offset, "limit": limit, "clean": "true"},
            timeout=30,
        )
        if not resp.ok:
            print(f"  ERROR: {resp.status_code} {resp.text[:100]}")
            break
        batch = resp.json()
        if not batch:
            break
        items.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    print(f"  총 {len(items)}개 항목")
    return items


# ── influencer_master 로드 ────────────────────────────────────────────────────

def get_influencer_map() -> dict:
    """influencer_id (lowercase) → 원본 influencer_id"""
    resp = requests.get(
        f"{REST}/influencer_master",
        headers=SB_HEADERS,
        params={"select": "influencer_id", "limit": 10000},
        timeout=15,
    )
    return {r["influencer_id"].lower(): r["influencer_id"] for r in (resp.json() if resp.ok else [])}


# ── 필드 추출 헬퍼 ────────────────────────────────────────────────────────────

def extract_username(item: dict) -> str | None:
    """ownerUsername → videoUrl 순서로 Instagram username 추출"""
    username = (item.get("ownerUsername") or "").strip().lstrip("@").lower()
    if username:
        return username
    for field in ("videoUrl", "url", "postUrl"):
        url = item.get(field) or ""
        m = re.search(r"instagram\.com/([^/?#]+)", url)
        if m:
            cand = m.group(1).lower()
            if cand not in ("p", "reel", "reels", "tv", "stories"):
                return cand
    return None


def extract_shortcode(item: dict) -> str | None:
    """포스트 shortcode 추출 (Storage 경로 키로 사용)"""
    sc = item.get("shortCode") or item.get("shortcode") or ""
    if sc:
        return sc
    for field in ("videoUrl", "url", "postUrl"):
        url = item.get(field) or ""
        m = re.search(r"/(?:p|reel|tv)/([^/?#]+)", url)
        if m:
            return m.group(1)
    return None


def extract_post_url(item: dict) -> str | None:
    """instagram.com 포스트 URL 추출"""
    for field in ("videoUrl", "url", "postUrl"):
        url = (item.get(field) or "").strip()
        if url and "instagram.com" in url and re.search(r"/(?:p|reel|tv)/", url):
            return url.split("?")[0].rstrip("/")
    return None


# ── 아이템 → koc_contents 행 변환 ────────────────────────────────────────────

def _int(v) -> int:
    try:
        return int(v or 0)
    except (ValueError, TypeError):
        return 0


def map_item(item: dict, influencer_id: str) -> dict | None:
    post_url = extract_post_url(item)
    if not post_url:
        return None

    # images/0 → 썸네일 소스 (images 배열의 첫 번째 원소)
    images = item.get("images") or []
    thumb_src = (images[0] if images else "") or item.get("displayUrl") or ""

    return {
        "influencer_id": influencer_id,
        "video_url":     post_url,
        "thumbnail_url": thumb_src,   # Storage 업로드 성공 시 교체됨
        "like_count":    _int(item.get("likesCount")    or item.get("likeCount")),
        "comment_count": _int(item.get("commentsCount") or item.get("commentCount")),
        "play_count":    _int(item.get("videoPlayCount") or item.get("videoViewCount") or item.get("playCount")),
        "share_count":   _int(item.get("videoShareCount") or item.get("shareCount")),
        "save_count":    _int(item.get("savesCount")    or item.get("saveCount")),
        "caption":       (item.get("text") or item.get("caption") or "")[:500],
        "posted_at":     item.get("timestamp") or item.get("takenAt") or item.get("createTimeISO") or None,
        # 내부용 — upsert 전에 제거
        "_thumb_src":    thumb_src,
    }


# ── Supabase upsert ───────────────────────────────────────────────────────────

def upsert_batch(rows: list[dict]) -> int:
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    if not clean:
        return 0
    resp = requests.post(
        f"{REST}/koc_contents",
        headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
        params={"on_conflict": "video_url"},
        json=clean,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"  [WARN] upsert 오류: {resp.status_code} {resp.text[:120]}")
        return 0
    return len(clean)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_id", help="Apify Dataset ID")
    parser.add_argument("--limit", type=int, default=0, help="처리 최대 수 (기본: 전체)")
    parser.add_argument("--skip-thumb", action="store_true",
                        help="썸네일 Storage 업로드 생략 (외부 CDN URL 그대로 저장)")
    args = parser.parse_args()

    items = fetch_dataset(args.dataset_id)
    if args.limit:
        items = items[:args.limit]

    inf_map = get_influencer_map()
    print(f"DB 인플루언서 {len(inf_map)}명 로드됨\n")

    rows      = []
    skipped   = 0
    new_infs  = {}
    ok_thumb  = 0
    fail_thumb = 0

    total = len(items)
    for i, item in enumerate(items, 1):
        username = extract_username(item)
        if not username:
            skipped += 1
            continue

        influencer_id = inf_map.get(username, username)
        row = map_item(item, influencer_id)
        if not row:
            skipped += 1
            continue

        shortcode = extract_shortcode(item) or f"ig_{i}"
        print(f"[{i}/{total}] @{influencer_id}/{shortcode}", end="  ", flush=True)

        # images/0 → Supabase Storage 영구 저장
        if not args.skip_thumb and row["_thumb_src"]:
            sb_url = upload_thumbnail(row["_thumb_src"], influencer_id, shortcode)
            if sb_url:
                row["thumbnail_url"] = sb_url
                ok_thumb += 1
                print("✅")
            else:
                fail_thumb += 1
                print("⚠️  Storage 실패 (CDN URL 유지)")
        else:
            print("–" if args.skip_thumb else "썸네일 없음")

        rows.append(row)

        if username not in inf_map:
            new_infs[username] = {
                "influencer_id": influencer_id,
                "account_url":   f"https://www.instagram.com/{username}/",
                "platform":      "instagram",
            }

        time.sleep(0.3)  # Storage 레이트리밋 방지

    print(f"\n매핑됨: {len(rows)}개  스킵: {skipped}개")
    print(f"썸네일: ✅ {ok_thumb}  ⚠️ {fail_thumb}")

    # 신규 인플루언서 먼저 등록
    if new_infs:
        print(f"\n[신규] influencer_master {len(new_infs)}명 등록 중...")
        inf_list = list(new_infs.values())
        for i in range(0, len(inf_list), 500):
            resp = requests.post(
                f"{REST}/influencer_master",
                headers={**SB_HEADERS, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                json=inf_list[i:i+500],
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                print(f"  [WARN] {resp.status_code} {resp.text[:120]}")

    # koc_contents upsert
    print(f"\n[Supabase] koc_contents 저장 중...")
    saved = 0
    for i in range(0, len(rows), 500):
        n = upsert_batch(rows[i:i+500])
        saved += n
        print(f"  {saved}/{len(rows)}...")

    print(f"\n[완료] koc_contents {saved}개 저장")
    print(f"       스킵 {skipped}개")
    print(f"       썸네일 영구저장 ✅ {ok_thumb}  ⚠️ {fail_thumb}")


if __name__ == "__main__":
    main()
