"""
썸네일이 없는 인플루언서 진단 + apify_status 리셋

역할:
  1. koc_contents.thumbnail_url이 NULL이거나 Apify URL인 인플루언서 수 확인
  2. 해당 인플루언서의 apify_status를 NULL로 리셋
     → 다음 파이프라인 실행 시 재채굴 + 썸네일 자동 Storage 업로드

사용법:
  python scripts/reset_missing_thumbnails.py          # 진단만 (dry-run)
  python scripts/reset_missing_thumbnails.py --apply  # 실제 리셋 실행
"""

import os
import sys
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수를 설정하세요.")
    sys.exit(1)

APPLY = "--apply" in sys.argv

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"


def fetch_all(table: str, params: dict) -> list[dict]:
    rows = []
    offset = 0
    limit = 1000
    while True:
        p = {**params, "offset": offset, "limit": limit}
        r = requests.get(f"{REST}/{table}", headers=HEADERS, params=p, timeout=30)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return rows


def main():
    print("=== 썸네일 누락 인플루언서 진단 ===\n")

    # 1) koc_contents 전체에서 thumbnail_url 상태 파악
    print("[1] koc_contents 썸네일 상태 조회 중...")
    rows = fetch_all("koc_contents", {"select": "influencer_id,thumbnail_url"})
    print(f"    전체 콘텐츠 행: {len(rows):,}개")

    # 인플루언서별로 썸네일 있는지 확인
    has_storage:  set[str] = set()  # Supabase Storage URL
    has_apify:    set[str] = set()  # 만료 위험 Apify URL
    has_null:     set[str] = set()  # null/빈 값

    for row in rows:
        iid = row.get("influencer_id", "").lower()
        url = row.get("thumbnail_url") or ""
        if not iid:
            continue
        if "supabase" in url:
            has_storage.add(iid)
        elif url:  # Apify URL 또는 기타
            has_apify.add(iid)
        else:
            has_null.add(iid)

    # Storage URL이 있으면 OK (Apify URL도 있어도 괜찮음)
    ok_set      = has_storage
    apify_only  = has_apify - has_storage
    null_only   = has_null - has_storage - has_apify
    needs_reset = apify_only | null_only

    print(f"\n[2] 인플루언서 썸네일 현황:")
    print(f"    OK (Supabase Storage URL 보유): {len(ok_set):,}명")
    print(f"    Apify URL만 있음 (만료 위험):   {len(apify_only):,}명")
    print(f"    썸네일 완전 없음 (NULL):         {len(null_only):,}명")
    print(f"    => 재채굴 필요:                  {len(needs_reset):,}명")

    if not needs_reset:
        print("\n모든 인플루언서가 Supabase Storage 썸네일을 보유 중입니다.")
        return

    # 2) influencer_master에서 현재 apify_status 확인
    print(f"\n[3] {len(needs_reset):,}명의 현재 apify_status 조회 중...")
    inf_rows = fetch_all("influencer_master", {
        "select": "influencer_id,apify_status",
        "platform": "eq.Tiktok",
    })
    status_map = {r["influencer_id"].lower(): r["apify_status"] for r in inf_rows}

    already_null = sum(1 for iid in needs_reset if status_map.get(iid) is None)
    to_reset     = [iid for iid in needs_reset if status_map.get(iid) is not None]

    status_counts: dict[str, int] = {}
    for iid in to_reset:
        s = status_map.get(iid, "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    print(f"    이미 NULL (자동 처리 예정): {already_null:,}명")
    print(f"    리셋 필요:                  {len(to_reset):,}명")
    for s, n in sorted(status_counts.items()):
        print(f"      - {s}: {n}명")

    if not to_reset:
        print("\n리셋할 대상이 없습니다. 파이프라인이 다음 실행 시 자동 처리합니다.")
        return

    if not APPLY:
        print(f"\n[DRY-RUN] --apply 옵션 없이 실행 중. 실제 변경 없음.")
        print(f"실제 리셋하려면: python scripts/reset_missing_thumbnails.py --apply")
        return

    # 3) apify_status NULL로 리셋 (배치 처리)
    print(f"\n[4] {len(to_reset):,}명 apify_status → NULL 리셋 중...")
    batch_size = 500
    total_ok = 0
    for i in range(0, len(to_reset), batch_size):
        chunk = to_reset[i:i + batch_size]
        id_list = ",".join(chunk)
        r = requests.patch(
            f"{REST}/influencer_master",
            headers=HEADERS,
            params={"influencer_id": f"in.({id_list})"},
            json={"apify_status": None, "apify_updated_at": None},
            timeout=30,
        )
        if r.status_code in (200, 204):
            total_ok += len(chunk)
            print(f"    리셋 완료: {total_ok}/{len(to_reset)}명...")
        else:
            print(f"    [WARN] 배치 오류: {r.status_code} {r.text[:80]}")

    print(f"\n[완료] {total_ok:,}명 리셋 완료")
    print(f"\n다음 단계:")
    print(f"  1. Railway 파이프라인이 자동 실행되기를 기다리거나")
    print(f"  2. Railway 대시보드에서 수동 실행 (Trigger Run)")
    print(f"  파이프라인이 실행되면 최대 {min(1200, len(to_reset))}명씩 재채굴됩니다.")


if __name__ == "__main__":
    main()
