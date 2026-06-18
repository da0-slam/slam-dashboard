"""
특정 캠페인 selections에 등록된 인플루언서 중 cover_url이 없는 것만 스크랩.

Usage:
    python scripts/scrape_campaign_covers.py --campaign "US 미들 임시"
"""
import os, sys, time, argparse
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv; load_dotenv()
from supabase import create_client
from utils.storage_client import fetch_and_upload_thumbnail, extract_post_id

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

parser = argparse.ArgumentParser()
parser.add_argument("--campaign", required=True)
args = parser.parse_args()

# 캠페인 찾기
campaigns = sb.table("campaigns").select("id,name").ilike("name", f"%{args.campaign}%").execute().data
if not campaigns:
    print(f"캠페인 없음: {args.campaign}"); sys.exit(1)
if len(campaigns) > 1:
    print("여러 캠페인 매칭:")
    for c in campaigns: print(f"  {c['name']}")
    sys.exit(1)

campaign = campaigns[0]
print(f"캠페인: {campaign['name']}")

# 이 캠페인의 influencer_id 목록
sels = sb.table("campaign_selections").select("influencer_id,platform_url").eq("campaign_id", campaign["id"]).execute().data
inf_ids = [s["influencer_id"] for s in sels]
print(f"등록 인플루언서: {len(inf_ids)}명")

# cover_url NULL인 것만
covers = sb.table("influencer_master").select("influencer_id,cover_url,account_url").in_("influencer_id", inf_ids).execute().data
targets = [x for x in covers if not x.get("cover_url")]
print(f"cover_url NULL: {len(targets)}명\n")

# koc_contents Supabase 썸네일 맵 (빠른 fallback)
koc_map: dict[str, str] = {}
for iid in [t["influencer_id"] for t in targets]:
    rows = sb.table("koc_contents").select("video_url,thumbnail_url").eq("influencer_id", iid).execute().data
    for row in rows:
        if row.get("thumbnail_url") and "supabase" in row["thumbnail_url"]:
            koc_map[iid] = row["thumbnail_url"]
            break

ok = fail = skip = 0
for i, inf in enumerate(targets, 1):
    iid  = inf["influencer_id"]
    aurl = inf.get("account_url") or ""

    # 1순위: 이미 koc_contents에 Supabase 썸네일 있으면 바로 사용
    if iid in koc_map:
        r = sb.table("influencer_master").update({"cover_url": koc_map[iid]}).eq("influencer_id", iid).execute()
        print(f"[{i}/{len(targets)}] ✓ {iid} (koc 재사용)")
        ok += 1
        continue

    # 2순위: koc_contents에서 아무 video_url이라도 찾아서 스크랩
    koc_rows = sb.table("koc_contents").select("video_url").eq("influencer_id", iid).limit(3).execute().data
    scraped = None
    for row in koc_rows:
        vurl = row.get("video_url", "")
        post_id = extract_post_id(vurl)
        if not post_id:
            continue
        try:
            saved = fetch_and_upload_thumbnail(vurl, iid, post_id)
            if saved:
                scraped = saved
                break
        except Exception as e:
            print(f"  오류: {e}")
        is_ig = "instagram.com" in vurl
        time.sleep(3 if is_ig else 0.5)

    if scraped:
        sb.table("influencer_master").update({"cover_url": scraped}).eq("influencer_id", iid).execute()
        print(f"[{i}/{len(targets)}] ✓ {iid} (스크랩)")
        ok += 1
        continue

    print(f"[{i}/{len(targets)}] ✗ {iid} FAIL (koc_contents 없음)")
    fail += 1

print(f"\n완료: 성공 {ok}명 / 실패 {fail}명 / 스킵 {skip}명")
