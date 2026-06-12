"""
Copy thumbnail URLs from `koc_contents` to `campaign_posts` when campaign posts
are missing `thumbnail_url` but a matching koc_contents row has one.

Usage:
  Set `SUPABASE_URL` and `SUPABASE_KEY` (service_role recommended), then:
    python scripts/copy_thumbnails_from_koc.py --limit 100

This performs lightweight reads and PATCH updates — safe and fast compared
to re-scraping thumbnails.
"""
import os
import sys
import time
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY environment variables must be set.")
    sys.exit(1)

REST = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

LIMIT = None
args = sys.argv[1:]
for i, a in enumerate(args):
    if a == "--limit" and i + 1 < len(args):
        try:
            LIMIT = int(args[i + 1])
        except Exception:
            LIMIT = None


def fetch_campaign_rows(limit=None):
    rows = []
    offset = 0
    page_size = 1000
    while True:
        r = requests.get(
            f"{REST}/campaign_posts",
            headers=HEADERS,
            params={"select": "id,brand_id,influencer_id,post_url,thumbnail_url", "offset": offset, "limit": page_size},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        for row in batch:
            thumb = row.get("thumbnail_url") or ""
            if not thumb or "supabase" not in thumb:
                rows.append(row)
                if limit and len(rows) >= limit:
                    return rows
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def find_koc_thumbnail(influencer_id: str, post_url: str) -> str | None:
    if not influencer_id or not post_url:
        return None
    # 1) Exact match on video_url
    try:
        r = requests.get(
            f"{REST}/koc_contents",
            headers=HEADERS,
            params={"select": "thumbnail_url", "influencer_id": f"eq.{influencer_id}", "video_url": f"eq.{post_url}", "limit": 1},
            timeout=20,
        )
        if r.ok:
            data = r.json()
            if data and data[0].get("thumbnail_url"):
                return data[0]["thumbnail_url"]
    except Exception:
        pass

    # 2) Fallback: try to match by containing post_id in video_url
    try:
        # extract last path segment
        path = post_url.split("?")[0].rstrip("/")
        post_id = path.split("/")[-1]
        if post_id:
            r = requests.get(
                f"{REST}/koc_contents",
                headers=HEADERS,
                params={"select": "thumbnail_url", "influencer_id": f"eq.{influencer_id}", "video_url": f"like.%{post_id}%", "limit": 1},
                timeout=20,
            )
            if r.ok:
                data = r.json()
                if data and data[0].get("thumbnail_url"):
                    return data[0]["thumbnail_url"]
    except Exception:
        pass

    return None


def update_campaign_thumbnail(post_id: str, thumbnail_url: str) -> bool:
    try:
        r = requests.patch(
            f"{REST}/campaign_posts",
            headers=HEADERS,
            params={"id": f"eq.{post_id}"},
            json={"thumbnail_url": thumbnail_url},
            timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def main():
    print("=== Copy thumbnails from koc_contents → campaign_posts ===")
    rows = fetch_campaign_rows(LIMIT)
    total = len(rows)
    print(f"Found {total} campaign_posts missing thumbnails")
    if not rows:
        return

    ok = skip = fail = 0
    for i, r in enumerate(rows, 1):
        pid = r.get("id")
        inf = r.get("influencer_id")
        post_url = r.get("post_url") or ""
        thumb = find_koc_thumbnail(inf, post_url)
        if not thumb:
            skip += 1
            print(f"[{i}/{total}] id={pid} - no matching koc thumbnail")
            continue
        if update_campaign_thumbnail(pid, thumb):
            ok += 1
            print(f"[{i}/{total}] id={pid} - copied thumbnail")
        else:
            fail += 1
            print(f"[{i}/{total}] id={pid} - update failed")
        time.sleep(0.05)

    print("=== Done ===")
    print(f"success: {ok}, skip: {skip}, fail: {fail}")


if __name__ == "__main__":
    main()
