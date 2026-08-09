"""LeanLoop focused regression suite (run: python3 test_leanloop.py). Mocks Notion/Garmin. No deps."""
import os
from datetime import datetime, timedelta
os.environ.update(dict(MCP_SECRET="t", GARMINTOKENS_B64="d", NOTION_TOKEN="d",
    NOTION_FOODLOG_DS="fl", NOTION_TRAININGLOG_DS="tl", NOTION_BODYMETRICS_DS="bm",
    NOTION_EXERCISELIB_DS="ex", D1_DATE="2026-03-15", TDEE_BASELINE="2620",
    PROGRESS_PAGE_ID="p", TZ_NAME="Asia/Bangkok", CONFIG_PAGE_ID="c",
    PLAYBOOK_URL="file://"+os.path.abspath("playbook.md")))
import main
P=[0]; F=[]
def ok(n,c):
    P[0]+= 1 if c else 0
    (F.append(n) if not c else None)
    print(("  ok  " if c else " FAIL ")+n)

ok("day() bangkok", len(main.day(""))==10 and main.day("2026-01-01")=="2026-01-01")

def mock_food(children):
    d,w=[],[]
    def _n(m,p,pl,v):
        if m=="DELETE": d.append(p.split("/")[-1]); return {}
        if "query" in p: return {"results":[{"id":"pg","properties":{"kcal":{"number":1}}}]}
        if p.startswith("/blocks/tbl/children") and m=="GET":
            return {"results":[{"type":"table_row","table_row":{"cells":[[{"plain_text":h}] for h in ["เวลา","รายการ","kcal","p","c","f"]]}}]}
        if p.startswith("/blocks/") and m=="GET": return {"results":children}
        if p=="/pages": return {"id":"pg"}
        return {"results":[]}
    main._notion=_n; main._notion_write=lambda m,p,pl:(w.append(pl),{"id":"x"})[1]
    main._find_row=lambda x:{"id":"pg","properties":{"kcal":{"number":1}}}
    return d,w
ch=[{"id":"tbl","type":"table"},{"id":"note","type":"callout"}]
d,w=mock_food(ch); main.foodlog_upsert(kcal=500)
ok("meals=None no block touch", d==[])
d,w=mock_food(ch); main.foodlog_upsert(meals=[])
ok("meals=[] clears table only", d==["tbl"])
d,w=mock_food(ch); main.foodlog_upsert(meals=[["12:00","rice",500,20,60,10]])
ok("meals=[...] deletes only table + writes", d==["tbl"] and any("table" in str(x) for x in w))
ok("non-table blocks preserved", "note" not in d)

base={"results":[{"properties":{"session":{"title":[{"plain_text":"Run"}]},"distance_km":{"number":5.0},"duration":{"rich_text":[{"plain_text":"30:00"}]},"garmin_activity_id":{"rich_text":[{"plain_text":"111"}]}}}]}
made=[]
def _n2(m,p,pl,v):
    if "query" in p: return base
    if p=="/pages": made.append(1); return {"id":"x"}
    return {"results":[]}
main._notion=_n2
ok("diff activityId+close duration NOT dup", main._log_training("2026-08-10",[{"activityId":222,"activityName":"Weights","activityType":{"typeKey":"strength_training"},"duration":1840,"distance":0,"calories":300}])["created"]==1)
made.clear()
ok("same activityId IS dup", main._log_training("2026-08-10",[{"activityId":111,"activityName":"R2","activityType":{"typeKey":"running"},"duration":1800,"distance":5000,"calories":400}])["created"]==0)
ok("fallback other", main._tl_type({"activityType":{"typeKey":"yoga"}})=="other")
ok("strength->weights", main._tl_type({"activityType":{"typeKey":"strength_training"}})=="weights")

ok("contains_error nested", main._contains_error({"a":{"error":"x"}}) is True)
ok("contains_error clean", main._contains_error({"a":1,"b":[{"c":2}]}) is False)

pages=[{"results":[{"id":1}],"has_more":True,"next_cursor":"c"},{"results":[{"id":2}],"has_more":False}]
i=[0]
main._notion=lambda m,p,pl,v: pages[i.__setitem__(0,i[0]+1) or i[0]-1]
ok("pagination follows has_more", [x["id"] for x in main._notion_query_all("ds")]==[1,2])

main._notion=lambda m,p,pl,v:{"results":[]} if "query" in p else {"id":"w"}
main._notion_write=lambda m,p,pl:{"id":"x"}
ok("weightlog lazy saves", main.weightlog_upsert(session="Pull",lifts=[["Deadlift"]])["status"]=="saved")
ok("weightlog empty=cleared", main.weightlog_upsert(session="Pull",lifts=[])["status"]=="lifts-cleared")
r=main.weightlog_upsert(page_id="exact",session="Push",lifts=[["Bench",60,4,8]])
ok("weightlog page_id + volume", r["page_id"]=="exact" and r["total_volume"]==1920)

def _tl(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"w1","properties":{"session":{"title":[{"plain_text":"Push"}]},"type":{"select":{"name":"weights"}},"date":{"date":{"start":"2026-08-10"}}}}],"has_more":False}
    if p.startswith("/blocks/w1") and m=="GET": return {"results":[{"id":"t","type":"table"}]}
    if p.startswith("/blocks/t") and m=="GET": return {"results":[
        {"type":"table_row","table_row":{"cells":[[{"plain_text":"ท่า"}],[{"plain_text":"นน(kg)"}],[{"plain_text":"เซ็ต×ครั้ง"}],[{"plain_text":"volume"}],[{"plain_text":"e1RM"}]]}},
        {"type":"table_row","table_row":{"cells":[[{"plain_text":"Bench"}],[{"plain_text":"60"}],[{"plain_text":"4×8"}],[{"plain_text":"1920"}],[{"plain_text":"76"}]]}}]}
    return {"results":[]}
main._notion=_tl
ok("traininglog_read lift table", main.traininglog_read("2026-08-10",type="weights")[0]["lifts"]==[["Bench",60.0,4.0,8.0]])

class G:
    def get_sleep_data(s,d): return {"dailySleepDTO":{"sleepScores":{"overall":{"value":68}},"sleepTimeSeconds":20031},"avgOvernightHrv":51,"restingHeartRate":48,"bodyBatteryChange":56}
    def get_training_readiness(s,d): return [{"score":72}]
main.client=lambda:G()
ok("recovery props non-None", main._recovery_props("2026-08-10")["sleep_score"]=={"number":68})
class Gf:
    def get_sleep_data(s,d): raise RuntimeError("down")
    def get_training_readiness(s,d): raise RuntimeError("down")
main.client=lambda:Gf()
ok("recovery tolerant", main._recovery_props("2026-08-10")=={})

t0=datetime(2026,8,10,7,0,0)
rows=[{"timestamp":t0+timedelta(seconds=s)} for s in [0,1,2,302,303,304,305,306,307,308]]
ok("moving-time split != naive under pause", main._moving_time_split(rows)!=len(rows)//2)

# ---- 2nd-audit fixes ----
main._call_cache.clear()
def _fr(aid):
    tt=datetime(2026,8,10,7,0,0); vv=100 if aid=="A" else 200
    return [{"timestamp":tt+timedelta(seconds=s),"heart_rate":vv} for s in range(300)]
main._fit_records=_fr; main._garmin="x"; main.client=lambda:object()
_rA=main.get_activity_stream("A"); _rB=main.get_activity_stream("B")
ok("cache: stream A != B (no key collision)", _rA["points"][0]["heart_rate"]!=_rB["points"][0]["heart_rate"])
ok("cache: same args = hit", main.get_activity_stream("A")["points"][0]["heart_rate"]==100)
ok("slim keeps downsampled stream (<=40 pts)", len(_rA["points"])<=40 and isinstance(main.slim(_rA)["points"],list))
main._notion=lambda m,p,pl,v:{"results":[]} if "query" in p else {"id":"w"}
main._notion_write=lambda m,p,pl:{"id":"x"}
_seen=[]; main._replace_table=lambda bid,tb,header=None:_seen.append(("clear" if tb is None else "write",header))
ok("weightlog None = table untouched", main.weightlog_upsert(session="P",lifts=None)["status"].startswith("session-row"))
_seen.clear()
ok("weightlog [] = cleared with lift header", main.weightlog_upsert(session="P",lifts=[])["status"]=="lifts-cleared" and _seen==[("clear",main._LIFT_HEADER)])
ok("body_battery_change (not body_battery) in REC_KEYS", "body_battery_change" in main._REC_KEYS and "body_battery" not in main._REC_KEYS)


# ---- round-3: read-side table ownership + backward-safe ----
def _RR(cells): return {"type":"table_row","table_row":{"cells":[[{"plain_text":str(c)}] for c in cells]}}
def _rd_mock(m,p,pl,v):
    if p.startswith("/blocks/pg/children"): return {"results":[{"id":"tu","type":"table"},{"id":"tm","type":"table"}]}
    if "/tu/" in p: return {"results":[_RR(["date","mood"]),_RR(["1/1","ok"])]}
    if "/tm/" in p: return {"results":[_RR(["เวลา","รายการ","kcal","p","c","f"]),_RR(["12:00","rice",500,20,60,10])]}
    return {"results":[]}
main._notion=_rd_mock
ok("_parse_meals picks meal table by header (skips user table)", main._parse_meals("pg")==[["12:00","rice",500.0,20.0,60.0,10.0]])
main._notion=lambda m,p,pl,v: {"results":[{"id":"tu","type":"table"}]} if p.startswith("/blocks/pg/children") else ({"results":[_RR(["date","mood"])]} if "/tu/" in p else {"results":[]})
ok("_parse_meals returns [] when only a user table exists", main._parse_meals("pg")==[])
# backward-safe: _log_training retries create without garmin_activity_id
_c=[]
def _bt(m,p,pl,v):
    if "query" in p: return {"results":[]}
    if p=="/pages":
        if "garmin_activity_id" in pl.get("properties",{}): raise RuntimeError("400 unknown property")
        _c.append(1); return {"id":"x"}
    return {"results":[]}
main._notion=_bt
ok("training create falls back without garmin_activity_id (old schema)", main._log_training("2026-08-10",[{"activityId":9,"activityName":"R","activityType":{"typeKey":"running"},"duration":1800,"distance":5000,"calories":400}])["created"]==1)
# backward-safe: close-day writes core even if recovery columns missing
_w=[]
def _bw(m,p,pl):
    pr=pl.get("properties",{})
    if any(k in pr for k in ("sleep_score","readiness","hrv")): raise RuntimeError("400 unknown property")
    _w.append([k for k in ("tdee_est","sync") if k in pr]); return {"id":"x"}
main._notion=lambda m,p,pl,v:{"results":[{"id":"pg","properties":{"kcal":{"number":2000}}}]} if "query" in p else {"results":[]}
main._notion_write=_bw
main._find_row=lambda d:{"id":"pg","properties":{"kcal":{"number":2000}}}
main._log_training=lambda d,a:{"created":0,"failed":0}
class _C:
    def get_activities_by_date(s,a,b): return []
    def get_stats(s,d): return {"totalKilocalories":2800}
    def get_sleep_data(s,d): return {"dailySleepDTO":{"sleepScores":{"overall":{"value":70}},"sleepTimeSeconds":25000},"avgOvernightHrv":50,"restingHeartRate":48,"bodyBatteryChange":60}
    def get_training_readiness(s,d): return [{"score":75}]
main.client=lambda:_C()
_r=main._close_one("2026-08-09")
ok("close-day writes core TDEE/sync even if recovery cols missing", _r["status"]=="updated" and _w==[["tdee_est","sync"]])


print("\n=== %d passed, %d failed ===" % (P[0], len(F)))
if F: print("FAILURES:", F); raise SystemExit(1)
