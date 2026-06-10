"""
US_DB의 Instagram 데이터를 influencer_master에 동기화

실행:
  python scripts/sync_instagram_from_usdb.py [--dry-run] [--batch N]

옵션:
  --dry-run    실제 DB 업데이트 없이 매칭 결과만 출력
  --batch N    1회 upsert 배치 크기 (기본 500)
"""

import os, re, sys, argparse, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "supa-apify-pipeline", ".env"))
except ImportError:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수를 설정하세요.")
    sys.exit(1)

HDR = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"


# ─── 팔로워 파싱 ──────────────────────────────────────────────────────────────

_MULTIPLIERS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

def parse_followers(raw: str) -> int | None:
    if not raw:
        return None
    raw = raw.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+(?:[.,]\d+)?)([kKmMbB])?$", raw)
    if not m:
        return None
    num_str = m.group(1).replace(",", ".")
    try:
        num = float(num_str)
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    return int(num * _MULTIPLIERS.get(suffix, 1))


# ─── 페이지네이션 fetch ───────────────────────────────────────────────────────

def fetch_all(table: str, params: dict, page_size: int = 1000) -> list[dict]:
    rows = []
    for offset in range(0, 200_000, page_size):
        r = requests.get(
            f"{REST}/{table}",
            headers={k: v for k, v in HDR.items() if k != "Prefer"},
            params={**params, "limit": str(page_size), "offset": str(offset)},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
    return rows


# ─── 세션 (재시도 포함) ──────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

_local = threading.local()

def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = _make_session()
    return _local.s


# ─── 개별 PATCH 업데이트 ──────────────────────────────────────────────────────

def _patch_one(row: dict) -> bool:
    iid = row["influencer_id"]
    payload = {k: v for k, v in row.items() if k != "influencer_id"}
    try:
        r = _session().patch(
            f"{REST}/influencer_master",
            headers=HDR,
            params={"influencer_id": f"eq.{iid}"},
            json=payload,
            timeout=20,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def parallel_update(rows: list[dict], workers: int = 20) -> tuple[int, int]:
    """(성공 행 수, 실패 행 수) 반환"""
    ok = fail = 0
    lock = threading.Lock()
    done = [0]

    def _track(future):
        nonlocal ok, fail
        with lock:
            done[0] += 1
            if future.result():
                ok += 1
            else:
                fail += 1
            if done[0] % 500 == 0 or done[0] == len(rows):
                pct = done[0] / len(rows) * 100
                print(f"\r  {done[0]:,} / {len(rows):,} 처리 중… ({pct:.0f}%)", end="", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_patch_one, row) for row in rows]
        for f in as_completed(futs):
            _track(f)
    print()
    return ok, fail


# ─── 메인 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="매칭 결과만 출력, DB 미변경")
    parser.add_argument("--workers", type=int, default=20, help="병렬 워커 수 (기본 20)")
    args = parser.parse_args()

    # 1. influencer_master 전체 로드 (influencer_id가 PK)
    print("▶ influencer_master 로드 중…")
    t0 = time.time()
    im_rows = fetch_all("influencer_master", {"select": "influencer_id"})
    # lowercase → 원본 케이스 맵 (upsert 시 PK 케이스 일치 보장)
    im_map = {r["influencer_id"].lower(): r["influencer_id"] for r in im_rows if r.get("influencer_id")}
    print(f"  {len(im_map):,}명 로드 완료 ({time.time()-t0:.1f}s)")

    # 2. US_DB Instagram 전체 로드
    print("▶ US_DB Instagram 로드 중…")
    t0 = time.time()
    ig_rows = fetch_all("US_DB", {
        "select":   "influencer_ID,account_URL,followers",
        "platform": "eq.Instagram",
    })
    print(f"  {len(ig_rows):,}행 로드 완료 ({time.time()-t0:.1f}s)")

    # 3. 매칭 및 upsert 페이로드 빌드
    matched = []
    no_match = []
    no_url   = []

    for row in ig_rows:
        uid_raw = (row.get("influencer_ID") or "").strip()
        uid = uid_raw.lower()

        im_uid = im_map.get(uid)
        if not im_uid:
            no_match.append(uid_raw)
            continue

        url = (row.get("account_URL") or "").strip()
        if not url:
            url = f"https://www.instagram.com/{uid_raw}/"
            no_url.append(uid_raw)

        followers = parse_followers(row.get("followers") or "")
        payload = {"influencer_id": im_uid, "instagram_url": url}
        if followers is not None:
            payload["instagram_followers"] = followers
        matched.append(payload)

    print(f"\n=== 매칭 결과 ===")
    print(f"  매칭 성공:  {len(matched):,}명")
    print(f"  매칭 실패:  {len(no_match):,}명")
    print(f"  URL 없음:   {len(no_url):,}명 (username으로 대체)")

    if no_match:
        print(f"\n  [매칭 실패 샘플] {no_match[:5]}")

    if args.dry_run:
        print("\n※ --dry-run 모드: DB 업데이트 생략")
        if matched:
            print(f"  샘플 upsert 페이로드:")
            for p in matched[:3]:
                print(f"    {p}")
        return

    if not matched:
        print("업데이트할 데이터가 없습니다.")
        return

    # 4. 병렬 PATCH
    print(f"\n▶ influencer_master 업데이트 중… ({args.workers} 워커)")
    t0 = time.time()
    ok, fail = parallel_update(matched, args.workers)
    elapsed = time.time() - t0

    print(f"\n=== 완료 ===")
    print(f"  성공: {ok:,}명")
    print(f"  실패: {fail:,}명")
    print(f"  소요: {elapsed:.1f}s ({ok/elapsed:.0f}행/s)")


if __name__ == "__main__":
    main()
