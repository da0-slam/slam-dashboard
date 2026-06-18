"""
influencer_master.cover_url을 koc_contents의 최신 Supabase 썸네일로 채우기.

Usage:
    python scripts/fill_cover_urls.py
"""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# 1. koc_contents에서 Supabase URL 있는 행 전수 조회
print("koc_contents 조회 중...")
koc_rows = []
offset = 0
while True:
    r = sb.table("koc_contents") \
        .select("influencer_id, thumbnail_url") \
        .like("thumbnail_url", "%supabase%") \
        .range(offset, offset + 999) \
        .execute()
    batch = r.data or []
    koc_rows.extend(batch)
    if len(batch) < 1000:
        break
    offset += 1000

print(f"  Supabase URL 행: {len(koc_rows)}개")

# influencer_id별 첫 번째 Supabase URL 선택
cover_map: dict[str, str] = {}
for row in koc_rows:
    iid = row["influencer_id"]
    if iid not in cover_map:
        cover_map[iid] = row["thumbnail_url"]

print(f"  대상 인플루언서: {len(cover_map)}명")

# 2. influencer_master에서 cover_url 없는 행 조회
print("\ninfluencer_master 조회 중...")
inf_rows = []
offset = 0
while True:
    r = sb.table("influencer_master") \
        .select("influencer_id") \
        .is_("cover_url", "null") \
        .range(offset, offset + 999) \
        .execute()
    batch = r.data or []
    inf_rows.extend(batch)
    if len(batch) < 1000:
        break
    offset += 1000

null_ids = [r["influencer_id"] for r in inf_rows]
print(f"  cover_url 없는 인플루언서: {len(null_ids)}명")

# 3. 업데이트
targets = [(iid, cover_map[iid]) for iid in null_ids if iid in cover_map]
no_thumb = [iid for iid in null_ids if iid not in cover_map]

print(f"\n업데이트 대상: {len(targets)}명 (koc_contents 썸네일 없음: {len(no_thumb)}명)\n")

ok = fail = 0
for i, (iid, thumb_url) in enumerate(targets, 1):
    r = sb.table("influencer_master") \
        .update({"cover_url": thumb_url}) \
        .eq("influencer_id", iid) \
        .execute()
    if r.data is not None:
        print(f"[{i}/{len(targets)}] ✓ {iid}")
        ok += 1
    else:
        print(f"[{i}/{len(targets)}] ✗ {iid} FAIL")
        fail += 1

print(f"\n완료: 성공 {ok}명 / 실패 {fail}명 / 썸네일 없어 스킵 {len(no_thumb)}명")
if no_thumb:
    print(f"\nkoc_contents 썸네일 없는 인플루언서 ({len(no_thumb)}명):")
    for iid in no_thumb[:20]:
        print(f"  - {iid}")
    if len(no_thumb) > 20:
        print(f"  ... 외 {len(no_thumb)-20}명")
