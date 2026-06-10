"""
TikTok oEmbed API로 썸네일 무료 백필

역할:
  1. koc_contents에서 thumbnail_url이 NULL이거나 Supabase URL이 아닌 행 조회
  2. TikTok oEmbed API (무료, 인증 불필요)로 썸네일 URL 획득
  3. Supabase Storage에 업로드 → 영구 URL로 교체
  4. koc_contents.thumbnail_url 업데이트

사용법:
  python scripts/backfill_thumbnails.py              # 전체 실행
  python scripts/backfill_thumbnails.py --limit 100  # 100개만 테스트
"""

import os
import re
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.storage_client import upload_thumbnail

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수를 설정하세요.")
    sys.exit(1)

# --limit N 파싱
LIMIT = None
for i, arg in enumerate(sys.argv[1:]):
    if arg == "--limit" and i + 1 < len(sys.argv) - 1:
        LIMIT = int(sys.argv[i + 2])

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"

OEMBED_URL = "https://www.tiktok.com/oembed"
REQUEST_DELAY = 0.4   # TikTok rate limit 방지 (초)


def fetch_rows_needing_thumbnail(limit: int | None) -> list[dict]:
    """thumbnail_url이 없거나 Supabase URL이 아닌 koc_contents 행."""
    rows = []
    offset = 0
    page_size = 1000
    while True:
        r = requests.get(
            f"{REST}/koc_contents",
            headers=HEADERS,
            params={
                "select":  "influencer_id,video_url,thumbnail_url",
                "order":   "influencer_id.asc",
                "offset":  offset,
                "limit":   page_size,
            },
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        for row in batch:
            url = row.get("thumbnail_url") or ""
            if "supabase" not in url:
                rows.append(row)
                if limit and len(rows) >= limit:
                    return rows
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def get_thumbnail_from_oembed(video_url: str) -> str | None:
    """TikTok oEmbed API로 썸네일 URL 조회."""
    try:
        r = requests.get(
            OEMBED_URL,
            params={"url": video_url},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            return r.json().get("thumbnail_url")
    except Exception:
        pass
    return None


def _retry_request(fn, retries=4):
    """네트워크 오류 시 지수 백오프로 재시도."""
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
            params={
                "influencer_id": f"eq.{influencer_id}",
                "video_url":     f"eq.{video_url}",
            },
            json={"thumbnail_url": thumbnail_url},
            timeout=15,
        ))
        return r.status_code in (200, 204)
    except Exception:
        return False


def main():
    print("=== TikTok oEmbed 썸네일 백필 ===\n")

    print("[1] 썸네일 누락 행 조회 중...")
    rows = fetch_rows_needing_thumbnail(LIMIT)
    print(f"    대상: {len(rows):,}개 행\n")

    if not rows:
        print("처리할 행이 없습니다.")
        return

    ok = skip = fail = 0

    for i, row in enumerate(rows, 1):
        iid       = row["influencer_id"]
        video_url = row["video_url"]

        # video_id 추출
        vid_m = re.search(r"/video/(\d+)", video_url)
        if not vid_m:
            skip += 1
            continue
        video_id = vid_m.group(1)

        try:
            # oEmbed로 썸네일 URL 조회
            thumb_url = get_thumbnail_from_oembed(video_url)
            if not thumb_url:
                skip += 1
                if i % 50 == 0 or i <= 5:
                    print(f"  [{i}/{len(rows)}] @{iid} — oEmbed 실패 (비공개/삭제된 영상)")
                time.sleep(REQUEST_DELAY)
                continue

            # Supabase Storage에 업로드
            storage_url = upload_thumbnail(thumb_url, iid, video_id)
            if not storage_url:
                skip += 1
                time.sleep(REQUEST_DELAY)
                continue

            # DB 업데이트
            if update_thumbnail(iid, video_url, storage_url):
                ok += 1
                if i % 50 == 0 or i <= 3:
                    print(f"  [{i}/{len(rows)}] 완료 {ok}개 | 스킵 {skip}개 | 실패 {fail}개")
            else:
                fail += 1
                print(f"  [{i}/{len(rows)}] @{iid} — DB 업데이트 실패")

        except Exception as e:
            fail += 1
            print(f"  [{i}/{len(rows)}] @{iid} — 오류: {e}")

        time.sleep(REQUEST_DELAY)

    print(f"\n=== 완료 ===")
    print(f"  성공:  {ok:,}개")
    print(f"  스킵:  {skip:,}개 (삭제/비공개/video_id 없음)")
    print(f"  실패:  {fail:,}개 (DB 오류)")


if __name__ == "__main__":
    main()
