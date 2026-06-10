"""
TikTok oEmbed API로 썸네일 무료 백필 (병렬 처리)

사용법:
  python scripts/backfill_thumbnails.py               # 전체 실행 (workers=8)
  python scripts/backfill_thumbnails.py --limit 100   # 100개만 테스트
  python scripts/backfill_thumbnails.py --workers 12  # 병렬 수 조정
"""

import os
import re
import sys
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.storage_client import upload_thumbnail

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수를 설정하세요.")
    sys.exit(1)

# CLI 파라미터 파싱
LIMIT   = None
WORKERS = 8
args = sys.argv[1:]
for i, arg in enumerate(args):
    if arg == "--limit"   and i + 1 < len(args): LIMIT   = int(args[i + 1])
    if arg == "--workers" and i + 1 < len(args): WORKERS = int(args[i + 1])

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
REST      = f"{SUPABASE_URL}/rest/v1"
OEMBED_URL = "https://www.tiktok.com/oembed"
PER_THREAD_DELAY = 0.3   # 워커당 딜레이 (TikTok rate limit 방지)


def fetch_rows_needing_thumbnail(limit):
    rows, offset, page_size = [], 0, 1000
    while True:
        r = requests.get(
            f"{REST}/koc_contents",
            headers=HEADERS,
            params={"select": "influencer_id,video_url,thumbnail_url",
                    "order": "influencer_id.asc",
                    "offset": offset, "limit": page_size},
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


def get_thumbnail_from_oembed(video_url: str):
    try:
        r = requests.get(OEMBED_URL, params={"url": video_url}, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.json().get("thumbnail_url")
    except Exception:
        pass
    return None


def get_thumbnail_from_tikwm(video_url: str):
    """tikwm.com API — 지역 제한 영상도 우회 가능한 폴백."""
    try:
        r = requests.post(
            "https://tikwm.com/api/",
            data={"url": video_url, "hd": 0},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("cover")
    except Exception:
        pass
    return None


def _retry_request(fn, retries=4):
    for attempt in range(retries):
        try:
            return fn()
        except requests.exceptions.ConnectionError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def update_thumbnail(influencer_id: str, video_url: str, thumbnail_url: str) -> bool:
    try:
        r = _retry_request(lambda: requests.patch(
            f"{REST}/koc_contents",
            headers=HEADERS,
            params={"influencer_id": f"eq.{influencer_id}", "video_url": f"eq.{video_url}"},
            json={"thumbnail_url": thumbnail_url},
            timeout=15,
        ))
        return r.status_code in (200, 204)
    except Exception:
        return False


def process_row(row):
    """단일 row 처리 — 스레드풀에서 실행."""
    iid       = row["influencer_id"]
    video_url = row["video_url"]

    vid_m = re.search(r"/video/(\d+)", video_url)
    if not vid_m:
        return "skip", iid, None

    video_id  = vid_m.group(1)
    thumb_url = get_thumbnail_from_oembed(video_url)
    if not thumb_url:
        thumb_url = get_thumbnail_from_tikwm(video_url)
    if not thumb_url:
        time.sleep(PER_THREAD_DELAY)
        return "skip", iid, "썸네일 없음 (삭제/비공개)"

    storage_url = upload_thumbnail(thumb_url, iid, video_id)
    if not storage_url:
        time.sleep(PER_THREAD_DELAY)
        return "skip", iid, "storage 업로드 실패"

    if update_thumbnail(iid, video_url, storage_url):
        time.sleep(PER_THREAD_DELAY)
        return "ok", iid, None
    else:
        return "fail", iid, "DB 업데이트 실패"


def main():
    print(f"=== TikTok oEmbed 썸네일 백필 (workers={WORKERS}) ===\n")

    print("[1] 썸네일 누락 행 조회 중...")
    rows = fetch_rows_needing_thumbnail(LIMIT)
    total = len(rows)
    print(f"    대상: {total:,}개 행\n")

    if not rows:
        print("처리할 행이 없습니다.")
        return

    ok = skip = fail = 0
    lock   = threading.Lock()
    done   = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process_row, row): row for row in rows}

        for future in as_completed(futures):
            done += 1
            try:
                status, iid, msg = future.result()
            except Exception as e:
                status, iid, msg = "fail", futures[future]["influencer_id"], str(e)

            with lock:
                if status == "ok":   ok   += 1
                elif status == "skip": skip += 1
                else:                fail += 1

                if done % 50 == 0 or done <= 5:
                    elapsed = time.time() - t_start
                    rate    = done / elapsed if elapsed > 0 else 0
                    eta_s   = (total - done) / rate if rate > 0 else 0
                    eta_min = int(eta_s // 60)
                    print(f"  [{done}/{total}] 완료 {ok}개 | 스킵 {skip}개 | 실패 {fail}개"
                          f"  ({rate:.1f}건/s, 남은시간 ~{eta_min}분)")

                if msg and status != "ok":
                    print(f"  [{done}/{total}] @{iid} — {msg}")

    elapsed_min = int((time.time() - t_start) // 60)
    print(f"\n=== 완료 ({elapsed_min}분 소요) ===")
    print(f"  성공:  {ok:,}개")
    print(f"  스킵:  {skip:,}개 (삭제/비공개/video_id 없음)")
    print(f"  실패:  {fail:,}개 (DB 오류)")


if __name__ == "__main__":
    main()
