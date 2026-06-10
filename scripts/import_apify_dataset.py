"""
Apify Dataset → Supabase koc_contents 수동 임포트

사용법:
  python scripts/import_apify_dataset.py <DATASET_ID>

Dataset ID 확인:
  Apify 실행 페이지 → Storage 탭 → Dataset ID

예시:
  python scripts/import_apify_dataset.py 1SDxR9eZoctvqDC79
"""

import os
import re
import sys

import requests

# ─── 환경 변수 ────────────────────────────────────────────────────────────────

APIFY_TOKEN  = os.environ.get("APIFY_TOKEN", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([APIFY_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: 환경 변수를 설정하세요.")
    print("  APIFY_TOKEN, SUPABASE_URL, SUPABASE_KEY")
    sys.exit(1)

if len(sys.argv) < 2:
    print("사용법: python scripts/import_apify_dataset.py <DATASET_ID>")
    print("Dataset ID는 Apify 실행 → Storage 탭에서 확인")
    sys.exit(1)

DATASET_ID = sys.argv[1].strip()

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates,return=minimal",
}

# ─── Apify Dataset 가져오기 ───────────────────────────────────────────────────

def fetch_dataset(dataset_id: str) -> list[dict]:
    print(f"Apify Dataset {dataset_id} 로딩 중...")
    items = []
    offset = 0
    limit  = 1000
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
        print(f"  {len(items)}개 로드됨...")
        if len(batch) < limit:
            break
        offset += limit
    print(f"  총 {len(items)}개 항목")
    return items

# ─── 인플루언서 목록 (influencer_id 매핑용) ──────────────────────────────────

def get_influencer_map() -> dict:
    """account_url → influencer_id 매핑."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/influencer_master",
        headers=SB_HEADERS,
        params={"select": "influencer_id,account_url", "limit": 10000},
        timeout=15,
    )
    result = {}
    for r in (resp.json() if resp.ok else []):
        url = r.get("account_url", "")
        iid = r.get("influencer_id", "")
        if url and iid:
            result[url.rstrip("/")] = iid
        # username으로도 매핑
        result[iid.lower()] = iid
    return result


def resolve_influencer_id(item: dict, inf_map: dict) -> str | None:
    """Apify 아이템에서 influencer_id 추출."""
    # 1) authorMeta.uniqueId (TikTok username)
    author_meta = item.get("authorMeta") or {}
    unique_id   = (author_meta.get("uniqueId") or author_meta.get("name") or "").lower().strip()
    if unique_id:
        if unique_id in inf_map:
            return inf_map[unique_id]
        # DB에 없어도 username 그대로 사용
        return unique_id

    # 2) webVideoUrl에서 username 추출
    video_url = item.get("webVideoUrl") or ""
    m = re.search(r"tiktok\.com/@([^/]+)", video_url)
    if m:
        return m.group(1).lower()

    return None

# ─── 필드 매핑 ────────────────────────────────────────────────────────────────

def map_item(item: dict, influencer_id: str) -> dict | None:
    video_url = (item.get("webVideoUrl") or item.get("videoUrl") or "").strip()
    if not video_url:
        return None

    # video_id 추출 (중복 방지용)
    vid_match = re.search(r"/video/(\d+)", video_url)
    video_id  = vid_match.group(1) if vid_match else None

    # 썸네일 — covers 우선, 없으면 authorMeta.avatar
    video_meta = item.get("videoMeta") or {}
    covers     = item.get("covers") or {}
    thumbnail  = (
        covers.get("default")
        or video_meta.get("coverUrl")
        or (item.get("authorMeta") or {}).get("avatar")
        or ""
    )

    return {
        "influencer_id": influencer_id,
        "video_url":     video_url,
        "thumbnail_url": thumbnail,
        "play_count":    int(item.get("playCount")    or item.get("statsV2", {}).get("playCount")    or 0),
        "like_count":    int(item.get("diggCount")    or item.get("statsV2", {}).get("diggCount")    or 0),
        "share_count":   int(item.get("shareCount")   or item.get("statsV2", {}).get("shareCount")   or 0),
        "comment_count": int(item.get("commentCount") or item.get("statsV2", {}).get("commentCount") or 0),
        "save_count":    int(item.get("collectCount") or item.get("statsV2", {}).get("collectCount") or 0),
        "caption":       (item.get("text") or "")[:500],
        "posted_at":     item.get("createTimeISO") or None,
    }

# ─── Supabase upsert ─────────────────────────────────────────────────────────

def upsert_batch(rows: list[dict]) -> int:
    if not rows:
        return 0
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/koc_contents",
        headers=SB_HEADERS,
        json=rows,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"  [WARN] upsert 오류: {resp.status_code} {resp.text[:120]}")
        return 0
    return len(rows)

# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Apify Dataset → Supabase 임포트 ===\n")

    items   = fetch_dataset(DATASET_ID)
    inf_map = get_influencer_map()
    print(f"DB 인플루언서 {len(inf_map)//2}명 로드됨\n")

    rows     = []
    skipped  = 0
    new_infs = {}  # influencer_id → {account_url, platform}

    for item in items:
        iid = resolve_influencer_id(item, inf_map)
        if not iid:
            skipped += 1
            continue

        row = map_item(item, iid)
        if not row:
            skipped += 1
            continue

        rows.append(row)

        if iid.lower() not in inf_map:
            author_meta = item.get("authorMeta") or {}
            video_url   = item.get("webVideoUrl") or ""
            m = re.search(r"tiktok\.com/@([^/]+)", video_url)
            username    = m.group(1) if m else iid
            new_infs[iid] = {
                "influencer_id": iid,
                "account_url":   f"https://www.tiktok.com/@{username}",
                "platform":      "tiktok",
                "apify_status":  "done",
            }

    print(f"매핑됨: {len(rows)}개  |  스킵: {skipped}개")

    # 신규 인플루언서 먼저 등록
    if new_infs:
        preview = ', '.join(sorted(new_infs)[:5]) + ('...' if len(new_infs) > 5 else '')
        print(f"[신규] influencer_master에 {len(new_infs)}명 등록: {preview}")
        inf_rows = list(new_infs.values())
        for i in range(0, len(inf_rows), 500):
            resp = requests.post(
                f"{SUPABASE_URL}/rest/v1/influencer_master",
                headers={**SB_HEADERS, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                json=inf_rows[i:i+500],
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                print(f"  [WARN] 인플루언서 등록 오류: {resp.status_code} {resp.text[:120]}")

    # 콘텐츠 저장
    saved = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i:i+500]
        n = upsert_batch(chunk)
        saved += n
        print(f"  저장 {saved}/{len(rows)}...")

    print(f"\n[완료] {saved}개 koc_contents 저장")
    if skipped:
        print(f"[스킵] {skipped}개 (video_url 없거나 인플루언서 미확인)")


if __name__ == "__main__":
    main()
