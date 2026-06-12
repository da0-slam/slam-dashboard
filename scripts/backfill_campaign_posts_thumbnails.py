"""
Backfill thumbnails for `campaign_posts` table.

Usage:
  Set `SUPABASE_URL` and `SUPABASE_KEY` (service_role recommended), then:
    python scripts/backfill_campaign_posts_thumbnails.py --limit 50 --workers 8

This script fetches campaign_posts rows missing `thumbnail_url`, attempts to
extract a thumbnail (TikTok oEmbed / tikwm / OG tags), uploads to Supabase
Storage using existing helpers, and updates `campaign_posts.thumbnail_url`.
"""
import os
import sys
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.storage_client import fetch_and_upload_thumbnail, extract_post_id
from utils.supabase_client import update_campaign_post_thumbnail

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수를 설정하세요.")
    sys.exit(1)

LIMIT = None
WORKERS = 8
args = sys.argv[1:]
for i, arg in enumerate(args):
    if arg == "--limit" and i + 1 < len(args): LIMIT = int(args[i + 1])
    if arg == "--workers" and i + 1 < len(args): WORKERS = int(args[i + 1])

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"
PER_THREAD_DELAY = 0.3


def fetch_rows_needing_thumbnail(limit):
    rows = []
    offset = 0
    page_size = 1000
    while True:
        r = requests.get(
            f"{REST}/campaign_posts",
            headers=HEADERS,
            params={"select": "id,brand_id,influencer_id,post_url,platform,thumbnail_url",
                    "order": "id.asc", "offset": offset, "limit": page_size},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        for row in batch:
            if "supabase" not in (row.get("thumbnail_url") or ""):
                rows.append(row)
                if limit and len(rows) >= limit:
                    return rows
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def _retry_request(fn, retries=3):
    for attempt in range(retries):
        try:
            return fn()
        except requests.exceptions.ConnectionError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def process_row(row):
    pid = row.get("id")
    brand_id = row.get("brand_id")
    post_url = row.get("post_url") or ""
    platform = row.get("platform") or None
    username = row.get("influencer_id") or brand_id or "unknown"

    if not post_url:
        return "skip", pid, "post_url 없음"

    post_id = extract_post_id(post_url) or str(pid)

    try:
        stored = fetch_and_upload_thumbnail(post_url, username, post_id)
    except Exception as e:
        return "fail", pid, f"fetch/upload 예외: {e}"

    if not stored:
        time.sleep(PER_THREAD_DELAY)
        return "skip", pid, "썸네일을 찾을 수 없음"

    try:
        ok = update_campaign_post_thumbnail(pid, brand_id, stored)
    except Exception as e:
        return "fail", pid, f"DB 업데이트 예외: {e}"

    time.sleep(PER_THREAD_DELAY)
    return ("ok", pid, None) if ok else ("fail", pid, "DB 업데이트 실패")


def main():
    print(f"=== campaign_posts 썸네일 백필 (workers={WORKERS}) ===\n")
    print("[1] 썸네일 누락 campaign_posts 조회 중...")
    rows = fetch_rows_needing_thumbnail(LIMIT)
    total = len(rows)
    print(f"    대상: {total:,}개 행\n")
    if not rows:
        print("처리할 행이 없습니다.")
        return

    ok = skip = fail = 0
    lock = threading.Lock()
    done = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process_row, row): row for row in rows}
        for future in as_completed(futures):
            done += 1
            try:
                status, pid, msg = future.result()
            except Exception as e:
                status, pid, msg = "fail", futures[future]["id"], str(e)

            with lock:
                if status == "ok":
                    ok += 1
                elif status == "skip":
                    skip += 1
                else:
                    fail += 1

                if done % 50 == 0 or done <= 5:
                    elapsed = time.time() - t_start
                    rate = done / elapsed if elapsed > 0 else 0
                    eta_s = (total - done) / rate if rate > 0 else 0
                    eta_min = int(eta_s // 60)
                    print(f"  [{done}/{total}] 완료 {ok}개 | 스킵 {skip}개 | 실패 {fail}개"
                          f"  ({rate:.1f}건/s, 남은시간 ~{eta_min}분)")

                if msg and status != "ok":
                    print(f"  [{done}/{total}] @id={pid} — {msg}")

    elapsed_min = int((time.time() - t_start) // 60)
    print(f"\n=== 완료 ({elapsed_min}분 소요) ===")
    print(f"  성공:  {ok:,}개")
    print(f"  스킵:  {skip:,}개")
    print(f"  실패:  {fail:,}개")


if __name__ == "__main__":
    main()
