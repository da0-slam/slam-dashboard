"""
One-time migration: Apify KV Store → Supabase Storage

역할:
  1. Apify KV Store의 cover-*.jpg 이미지를 Supabase Storage에 업로드
  2. influencer_master.cover_url 업데이트 (인플루언서당 대표 이미지 1장)
  3. koc_contents.thumbnail_url 업데이트 (video_url에서 video_id 추출 후 매핑)

사용법:
  APIFY_TOKEN=xxx APIFY_COVER_STORE_IDS=wzKx30cg9JWdGBcv2 \\
  SUPABASE_URL=xxx SUPABASE_KEY=xxx \\
  python scripts/migrate_kv_to_storage.py

  여러 KV Store:
  APIFY_COVER_STORE_IDS=storeId1,storeId2,storeId3

파이프라인 연동 (apify_pipeline.py에 추가할 코드):
  # save_contents() 내부 thumb_url 저장 전에:
  from utils.storage_client import upload_thumbnail, ensure_buckets
  ensure_buckets()
  supabase_url = upload_thumbnail(apify_thumb_url, influencer_id, video_id, APIFY_TOKEN)
  thumb_url = supabase_url or apify_thumb_url
"""

import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import requests

# ─── 환경 변수 ────────────────────────────────────────────────────────────────

APIFY_TOKEN        = os.environ.get("APIFY_TOKEN", "").strip()
APIFY_STORE_IDS    = [s.strip() for s in os.environ.get("APIFY_COVER_STORE_IDS", "").split(",") if s.strip()]
SUPABASE_URL       = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY       = os.environ.get("SUPABASE_KEY", "").strip()

if not all([APIFY_TOKEN, APIFY_STORE_IDS, SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: 환경 변수를 모두 설정하세요.")
    print("  APIFY_TOKEN, APIFY_COVER_STORE_IDS, SUPABASE_URL, SUPABASE_KEY")
    sys.exit(1)

APIFY_BASE       = "https://api.apify.com/v2"
BUCKET           = "tiktok-thumbnails"   # 기존 Supabase Storage 버킷
COVER_KEY_RE     = re.compile(r"^cover-(.+)-(\d{14})-(\d+)\.jpg$", re.IGNORECASE)

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
APIFY_HEADERS = {"Authorization": f"Bearer {APIFY_TOKEN}"}


# ─── Supabase Storage ─────────────────────────────────────────────────────────

def _storage_url() -> str:
    return f"{SUPABASE_URL}/storage/v1"


def ensure_bucket(bucket: str) -> None:
    resp = requests.post(
        f"{_storage_url()}/bucket",
        headers={**SB_HEADERS, "Content-Type": "application/json"},
        json={"id": bucket, "name": bucket, "public": True},
        timeout=10,
    )
    if resp.status_code in (200, 201):
        print(f"  [bucket] 생성됨: {bucket}")
    else:
        print(f"  [bucket] {bucket} 사용 (이미 존재)")


def upload_to_storage(img_bytes: bytes, content_type: str, bucket: str, path: str) -> str | None:
    resp = requests.post(
        f"{_storage_url()}/object/{bucket}/{path}",
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  content_type,
            "x-upsert":      "true",
        },
        data=img_bytes,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"    [FAIL] upload {path}: {resp.status_code} {resp.text[:80]}")
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


# ─── Supabase DB ──────────────────────────────────────────────────────────────

def _rest(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1{path}"


def update_influencer_cover(influencer_id: str, cover_url: str) -> bool:
    resp = requests.patch(
        _rest("/influencer_master"),
        headers=SB_HEADERS,
        params={"influencer_id": f"eq.{influencer_id}"},
        json={"cover_url": cover_url},
        timeout=10,
    )
    return resp.status_code in (200, 204)


def update_koc_thumbnail(influencer_id: str, old_url_fragment: str, new_url: str) -> bool:
    """video_url에 video_id가 포함된 행의 thumbnail_url을 교체."""
    resp = requests.patch(
        _rest("/koc_contents"),
        headers=SB_HEADERS,
        params={
            "influencer_id": f"eq.{influencer_id}",
            "video_url":     f"like.%{old_url_fragment}%",
        },
        json={"thumbnail_url": new_url},
        timeout=10,
    )
    return resp.status_code in (200, 204)


def get_koc_rows(influencer_id: str) -> list[dict]:
    resp = requests.get(
        _rest("/koc_contents"),
        headers={**SB_HEADERS, "Content-Type": "application/json"},
        params={
            "influencer_id": f"eq.{influencer_id}",
            "select":        "influencer_id,video_url,thumbnail_url",
        },
        timeout=10,
    )
    return resp.json() if resp.ok else []


# ─── Apify KV Store ───────────────────────────────────────────────────────────

def list_kv_keys(store_id: str) -> list[dict]:
    """모든 KV Store 키를 페이지네이션으로 수집."""
    keys = []
    params: dict = {"limit": 1000}
    while True:
        resp = requests.get(
            f"{APIFY_BASE}/key-value-stores/{store_id}/keys",
            headers=APIFY_HEADERS,
            params=params,
            timeout=15,
        )
        if not resp.ok:
            print(f"  [WARN] KV Store {store_id} 키 조회 실패: {resp.status_code}")
            break
        data = resp.json().get("data", {})
        keys.extend(data.get("items", []))
        nk = data.get("nextExclusiveStartKey")
        if not nk:
            break
        params["exclusiveStartKey"] = nk
    return keys


def download_kv_image(store_id: str, key: str) -> tuple[bytes, str] | None:
    """Apify KV에서 이미지 다운로드. (bytes, content_type) 반환."""
    url = f"{APIFY_BASE}/key-value-stores/{store_id}/records/{key}"
    resp = requests.get(url, headers=APIFY_HEADERS, timeout=20)
    if resp.status_code != 200:
        return None
    ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return resp.content, ct


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print("=== Apify KV → Supabase Storage 마이그레이션 ===\n")

    # 버킷 준비 (이미 존재하면 그냥 사용)
    ensure_bucket(BUCKET)

    # 모든 KV Store에서 키 수집, 인플루언서별로 그룹핑
    # {username: [(timestamp_str, video_id_str, store_id, key), ...]}
    influencer_videos: dict[str, list] = {}

    for store_id in APIFY_STORE_IDS:
        print(f"\n[KV Store] {store_id} 키 조회 중...")
        keys = list_kv_keys(store_id)
        matched = 0
        for item in keys:
            key = item.get("key", "")
            m = COVER_KEY_RE.match(key)
            if not m:
                continue
            username, ts, video_id = m.group(1).lower(), m.group(2), m.group(3)
            influencer_videos.setdefault(username, []).append((ts, video_id, store_id, key))
            matched += 1
        print(f"  cover 이미지 {matched}개 발견 ({len(influencer_videos)}명)")

    if not influencer_videos:
        print("\n처리할 이미지가 없습니다. APIFY_COVER_STORE_IDS를 확인하세요.")
        return

    # 인플루언서별 처리
    total = len(influencer_videos)
    cover_ok = 0
    thumb_ok = 0

    for i, (username, videos) in enumerate(sorted(influencer_videos.items()), 1):
        print(f"\n[{i}/{total}] @{username} — {len(videos)}개 영상")

        # 가장 최신 영상을 대표 커버로 사용
        videos_sorted = sorted(videos, key=lambda x: x[0], reverse=True)
        ts, video_id, store_id, cover_key = videos_sorted[0]

        # 대표 커버 이미지 다운로드 → Supabase Storage
        result = download_kv_image(store_id, cover_key)
        if result is None:
            print(f"  [SKIP] 다운로드 실패: {cover_key}")
            continue

        img_bytes, content_type = result
        cover_path = f"covers/{username}.jpg"
        cover_url = upload_to_storage(img_bytes, content_type, BUCKET, cover_path)
        if not cover_url:
            continue

        # influencer_master.cover_url 업데이트
        if update_influencer_cover(username, cover_url):
            print(f"  ✓ cover_url 저장: {cover_url}")
            cover_ok += 1
        else:
            print(f"  [WARN] cover_url DB 업데이트 실패 (인플루언서가 DB에 없을 수 있음)")

        # koc_contents.thumbnail_url 업데이트 (모든 영상)
        koc_rows = get_koc_rows(username)
        koc_video_ids = {}
        for row in koc_rows:
            vurl = row.get("video_url", "")
            m = re.search(r"/video/(\d+)", vurl)
            if m:
                koc_video_ids[m.group(1)] = row

        for ts2, vid2, sid2, key2 in videos_sorted:
            if vid2 not in koc_video_ids:
                continue  # DB에 해당 영상 없음
            koc_row = koc_video_ids[vid2]

            # 이미 Supabase URL이면 스킵
            existing = koc_row.get("thumbnail_url", "")
            if existing and "supabase" in existing:
                continue

            # 해당 영상 썸네일도 업로드
            if vid2 == video_id:
                # 이미 다운로드한 커버와 같은 영상
                thumb_url = upload_to_storage(img_bytes, content_type, BUCKET, f"thumbnails/{username}/{vid2}.jpg")
            else:
                result2 = download_kv_image(sid2, key2)
                if result2 is None:
                    continue
                img2, ct2 = result2
                thumb_url = upload_to_storage(img2, ct2, BUCKET, f"thumbnails/{username}/{vid2}.jpg")

            if thumb_url and update_koc_thumbnail(username, vid2, thumb_url):
                print(f"  ✓ thumbnail 갱신: video {vid2}")
                thumb_ok += 1

            time.sleep(0.05)  # Rate limit 방지

    print(f"\n=== 완료 ===")
    print(f"  cover_url 업데이트: {cover_ok}명")
    print(f"  thumbnail_url 업데이트: {thumb_ok}개")
    print(f"\n다음 단계: Supabase 대시보드에서 migrations/003_influencer_cover_url.sql 실행 후 이 스크립트를 재실행하세요.")


if __name__ == "__main__":
    main()
