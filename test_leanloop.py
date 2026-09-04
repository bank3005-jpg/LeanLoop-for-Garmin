"""LeanLoop focused regression suite (run: python3 test_leanloop.py). Mocks Notion/Garmin. No deps."""
import os
from datetime import datetime, timedelta
os.environ.update(dict(MCP_SECRET="t", GARMINTOKENS_B64="d", NOTION_TOKEN="d",
    NOTION_FOODLOG_DS="fl", NOTION_TRAININGLOG_DS="tl", NOTION_BODYMETRICS_DS="bm",
    NOTION_EXERCISELIB_DS="ex", D1_DATE="2025-01-01", TDEE_BASELINE="2000",
    PROGRESS_PAGE_ID="p", TZ_NAME="Asia/Bangkok", CONFIG_PAGE_ID="c",
    PLAYBOOK_URL="file://"+os.path.abspath("playbook.md")))
import main
_orig_log_training=main._log_training; _orig_replace_table=main._replace_table; _orig_call=main.call
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
_gt=main.get_today()
ok("get_today: date + D-label + weekday + time", isinstance(_gt,dict) and "date" in _gt and _gt["day_label"].startswith("D") and "weekday" in _gt and "time" in _gt)

def _tl(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"w1","properties":{"session":{"title":[{"plain_text":"Push"}]},"type":{"select":{"name":"weights"}},"date":{"date":{"start":"2026-08-10"}}}}],"has_more":False}
    if p.startswith("/blocks/w1") and m=="GET": return {"results":[{"id":"t","type":"table"}]}
    if p.startswith("/blocks/t") and m=="GET": return {"results":[
        {"type":"table_row","table_row":{"cells":[[{"plain_text":"ท่า"}],[{"plain_text":"นน(kg)"}],[{"plain_text":"เซ็ต×ครั้ง"}],[{"plain_text":"volume"}],[{"plain_text":"e1RM"}]]}},
        {"type":"table_row","table_row":{"cells":[[{"plain_text":"Bench"}],[{"plain_text":"60"}],[{"plain_text":"4×8"}],[{"plain_text":"1920"}],[{"plain_text":"76"}]]}}]}
    return {"results":[]}
main._notion=_tl
ok("traininglog_read lift table", main.traininglog_read("2026-08-10",type="weights")[0]["lifts"]==[["Bench",60.0,4.0,8.0,None]])

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
ok("weightlog [] = cleared with lift header", main.weightlog_upsert(session="P",lifts=[])["status"]=="lifts-cleared" and _seen==[("clear",main._LIFT_HEADERS)])
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

def _lift_rd(m,p,pl,v):
    if p.startswith("/blocks/pg2/children"): return {"results":[{"id":"tu","type":"table"},{"id":"tl","type":"table"}]}
    if "/tu/" in p: return {"results":[_RR(["date","note"]),_RR(["1/1","x"])]}
    if "/tl/" in p: return {"results":[_RR(["ท่า","นน(kg)","เซ็ต×ครั้ง","volume","e1RM"]),_RR(["Bench","60","4×8","1920","76"])]}
    return {"results":[]}
main._notion=_lift_rd
ok("_parse_lift_table picks lift table by header (skips user table)", main._parse_lift_table("pg2")==[["Bench",60.0,4.0,8.0,None]])

# ---- B: RIR (5th element) round-trip ----
def _lift_rir(m,p,pl,v):
    if p.startswith("/blocks/pgr/children"): return {"results":[{"id":"tl","type":"table"}]}
    if "/tl/" in p: return {"results":[_RR(main._LIFT_HEADER),_RR(["Bench","60","4×8","2","1920","76"])]}
    return {"results":[]}
main._notion=_lift_rir; main._call_cache.clear()
ok("B _parse_lift_table reads RIR from 6-col table", main._parse_lift_table("pgr")==[["Bench",60.0,4.0,8.0,2.0]])
main._notion=lambda mth,p,pl,v:{"results":[]}; main._notion_write=lambda mth,p,pl:{"id":"x"}; main._call_cache.clear()
ok("B weightlog accepts RIR 5th (volume unaffected)", main.weightlog_upsert(page_id="exact",session="Push",lifts=[["Bench",60,4,8,2]])["total_volume"]==1920)


# ================= FINAL Hardening Patch regression =================
# ---- P1-1: training logging must never fail silently ----
def _qfail(m,p,pl,v):
    if "query" in p: raise RuntimeError("boom")
    return {"results":[]}
main._log_training=_orig_log_training
main._notion=_qfail
_r=main._log_training("2026-08-10",[{"activityId":1,"activityName":"R","activityType":{"typeKey":"running"},"duration":1800,"distance":5000,"calories":400}])
ok("P1-1 training query fail = truthful, not 0/0 success", _r["created"]==0 and _r["failed"]==1 and "error" in _r)
def _okq(m,p,pl,v): return {"results":[]}
main._notion=_okq
ok("P1-1 genuine no-activity day still clean 0/0", main._log_training("2026-08-10",[])=={"created":0,"failed":0})

# ---- P1-2: table replacement is data-safe ----
_del=[]
def _af_notion(m,p,pl,v):
    if m=="DELETE": _del.append(p); return {}
    if p.endswith("/children?page_size=100"): return {"results":[{"id":"tbl","type":"table"}]}
    if "/children?page_size=1" in p: return {"results":[_RR(main._MEAL_HEADER)]}
    return {"results":[]}
def _af_write(m,p,pl): raise RuntimeError("append failed")
main._replace_table=_orig_replace_table
main._notion=_af_notion; main._notion_write=_af_write
try:
    main._replace_table("bid", {"object":"block","type":"table","table":{}}, header=main._MEAL_HEADER); _raised=False
except Exception: _raised=True
ok("P1-2 append-fail propagates + old table NOT deleted (data safe)", _raised and _del==[])

def _newest(m,p,pl,v):
    if p.startswith("/blocks/pg/children"): return {"results":[{"id":"tm1","type":"table"},{"id":"tm2","type":"table"}]}
    if "/tm1/" in p: return {"results":[_RR(["เวลา","รายการ","kcal","p","c","f"]),_RR(["08:00","old",100,1,1,1])]}
    if "/tm2/" in p: return {"results":[_RR(["เวลา","รายการ","kcal","p","c","f"]),_RR(["12:00","new",500,20,60,10])]}
    return {"results":[]}
main._notion=_newest
ok("P1-2 _parse_meals prefers NEWEST matching table (stale dup safe)", main._parse_meals("pg")==[["12:00","new",500.0,20.0,60.0,10.0]])

def _rt_fail(bid,tb,header=None): raise RuntimeError("delete failed")
main._replace_table=_rt_fail
main._notion=lambda m,p,pl,v:{"results":[]} if "query" in p else {"id":"w"}
main._notion_write=lambda m,p,pl:{"id":"x"}
_r=main.weightlog_upsert(page_id="x1",session="Pull",lifts=[])
ok("P1-2 lifts=[] delete failure = NOT lifts-cleared", _r["status"]=="clear-failed" and "error" in _r)

# ---- P1-3: calibration correctness ----
main._body_scans=lambda:[]
main.call=lambda *a,**k:{"points":[]}
main.foodlog_get_range=lambda s,e:[{"kcal":1500,"deficit_actual":500},{"kcal":1600,"deficit_actual":400},{"kcal":1400}]
_r=main.calibrate_report(days=14)
ok("P1-3 coverage counts deficit-days not kcal-days", _r["days_with_deficit"]==2)

_rng=[]
def _fgr(s,e): _rng.append((s,e)); return [{"kcal":1,"deficit_actual":-500} for _ in range(14)]
main.foodlog_get_range=_fgr
main._body_scans=lambda:[
  {"date":"2026-08-01","fatMass":20.0,"leanMass":55.0,"w":80.0,"source":"InBody","condition":"morning-fasted","visceral":8,"smm":30,"score":80},
  {"date":"2026-08-15","fatMass":19.0,"leanMass":55.0,"w":79.0,"source":"InBody","condition":"morning-fasted","visceral":8,"smm":30,"score":81}]
_r=main.calibrate_report()
ok("P1-3 scan-pair deficit window excludes s1 (off-by-one)", _r.get("span_days")==14 and bool(_rng) and _rng[-1]==("2026-08-01","2026-08-14"))

# ---- F2: body-scan read failure must fail-visible (READ unknown != empty) ----
def _bs_fail(): raise RuntimeError("bodymetrics down")
main._body_scans=_bs_fail
_r=main.calibrate_report()
ok("F2 body-scan read failure -> error surfaced (no silent scale fallback)", isinstance(_r,dict) and "error" in _r)

# ---- P1-4A: analyze_activity.session carries RPE/feel when present ----
main.call=_orig_call; main._call_cache.clear()
class _GA:
    def get_activities(s,a,b): return [{"activityId":"77","activityType":{"typeKey":"running"},"duration":1800,"distance":5000}]
    def get_activity(s,aid): return {"activityId":"77","activityName":"Run","activityType":{"typeKey":"running"},"duration":1800,"distance":5000,"averageHR":150,"directWorkoutRpe":70,"directWorkoutFeel":75}
    def get_activity_splits(s,aid): return {"lapDTOs":[]}
    def get_activity_hr_in_timezones(s,aid): return []
    def get_activities_by_date(s,*a): return []
main.client=lambda:_GA(); main._fit_records=lambda aid:[]
_r=main.analyze_activity()
ok("P1-4A analyze_activity.session carries RPE/feel when Garmin has them", _r["session"].get("directWorkoutRpe")==70 and _r["session"].get("directWorkoutFeel")==75)

# release-blocker: get_activity() is NESTED — flat list item stays canonical meta, detail only enriches RPE/feel
main.call=_orig_call; main._call_cache.clear()
class _GN:
    def get_activities(s,a,b): return [{"activityId":77,"activityName":"Run","activityType":{"typeKey":"running"},"startTimeLocal":"2026-08-10T07:00:00","duration":1800,"distance":5000,"averageHR":150}]
    def get_activity(s,aid): return {"activityId":77,"activityName":"Run","activityTypeDTO":{"typeKey":"running"},"summaryDTO":{"startTimeLocal":"2026-08-10T07:00:00","duration":1800,"distance":5000,"averageHR":150,"directWorkoutRpe":70,"directWorkoutFeel":75}}
    def get_activity_splits(s,aid): return {"lapDTOs":[]}
    def get_activity_hr_in_timezones(s,aid): return []
    def get_activities_by_date(s,*a): return []
main.client=lambda:_GN(); main._fit_records=lambda aid:[]
_ss=main.analyze_activity()["session"]
ok("blocker: nested get_activity -> flat meta preserved + RPE/feel from summaryDTO",
   _ss.get("activityId")==77 and _ss.get("distance")==5000 and _ss.get("duration")==1800
   and _ss.get("averageHR")==150 and _ss.get("typeKey")=="running"
   and _ss.get("directWorkoutRpe")==70 and _ss.get("directWorkoutFeel")==75)

# ================= FINAL FINAL: table CLEAR truthfulness =================
# Test 1 — Food CLEAR discovery failure -> NOT a false success
main._replace_table=_orig_replace_table
def _clr_fail(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"pg","properties":{"kcal":{"number":1}}}]}
    if m=="GET" and "/children" in p: raise RuntimeError("children read down")
    return {"results":[]}
main._notion=_clr_fail; main._notion_write=lambda m,p,pl:{"id":"x"}
main._find_row=lambda d:{"id":"pg","properties":{"kcal":{"number":1}}}
_r=main.foodlog_upsert(meals=[])
ok("FF food CLEAR discovery-fail = top-level error, not cleared", "error" in _r and _r.get("status")=="partial-failure")

# Test 2 — Weight CLEAR discovery failure -> clear-failed (never lifts-cleared)
main._replace_table=_orig_replace_table
def _wclr_fail(m,p,pl,v):
    if "query" in p: return {"results":[]}
    if m=="GET" and "/children" in p: raise RuntimeError("children down")
    if p=="/pages": return {"id":"w1"}
    return {"results":[]}
main._notion=_wclr_fail; main._notion_write=lambda m,p,pl:{"id":"x"}
_r=main.weightlog_upsert(session="Pull",lifts=[])
ok("FF weight CLEAR discovery-fail = clear-failed (not lifts-cleared)", _r["status"]=="clear-failed" and "error" in _r)

# Test 3 — Meal table rebuild (append) fails -> top-level error
main._replace_table=_orig_replace_table
def _rebuild_ok_get(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"pg","properties":{"kcal":{"number":1}}}]}
    if m=="GET" and "/children" in p: return {"results":[]}
    return {"results":[]}
def _rebuild_fail_write(m,p,pl):
    if "/children" in p: raise RuntimeError("append failed")
    return {"id":"x"}
main._notion=_rebuild_ok_get; main._notion_write=_rebuild_fail_write
main._find_row=lambda d:{"id":"pg","properties":{"kcal":{"number":1}}}
_r=main.foodlog_upsert(meals=[["12:00","rice",500,20,60,10]])
ok("FF meal-table rebuild fail = top-level error (not silent updated)", "error" in _r and _r.get("status")=="partial-failure")

# Test 4 — Normal CLEAR still works (verified owned table deleted)
main._replace_table=_orig_replace_table
_deleted=[]
def _clr_ok(m,p,pl,v):
    if "query" in p: return {"results":[]}
    if m=="GET" and p.endswith("/children?page_size=100"): return {"results":[{"id":"tl","type":"table"}]}
    if m=="GET" and "?page_size=1" in p: return {"results":[_RR(main._LIFT_HEADER)]}
    if m=="DELETE": _deleted.append(p); return {}
    if p=="/pages": return {"id":"w1"}
    return {"results":[]}
main._notion=_clr_ok; main._notion_write=lambda m,p,pl:{"id":"x"}
_r=main.weightlog_upsert(session="Pull",lifts=[])
ok("FF normal CLEAR still works (verified table deleted)", _r["status"]=="lifts-cleared" and len(_deleted)==1)

# LAST verification fix: CLEAR header-verify failure must fail closed
main._replace_table=_orig_replace_table
def _hdr_fail(m,p,pl,v):
    if "query" in p: return {"results":[]}
    if m=="GET" and p.endswith("/children?page_size=100"): return {"results":[{"id":"tl","type":"table"}]}
    if m=="GET" and "?page_size=1" in p: raise RuntimeError("header read down")
    if p=="/pages": return {"id":"w1"}
    return {"results":[]}
main._notion=_hdr_fail; main._notion_write=lambda m,p,pl:{"id":"x"}
_r=main.weightlog_upsert(session="Pull",lifts=[])
ok("FF2 CLEAR header-verify fail = clear-failed (ownership unknown, not lifts-cleared)", _r["status"]=="clear-failed" and "error" in _r)

# ================= FINAL P1: READ UNKNOWN != EMPTY =================
def _thr(msg):
    def _f(m,p,pl,v): raise RuntimeError(msg)
    return _f
# T1 meal page-children read fail -> raise (not [])
def _t1(m,p,pl,v):
    if p.startswith("/blocks/pg/children"): raise RuntimeError("children down")
    return {"results":[]}
main._notion=_t1
try: main._parse_meals("pg"); _r=False
except Exception: _r=True
ok("RP-T1 meal page-children read fail = raise (not [])", _r)
# T2 meal table-rows read fail -> raise
def _t2(m,p,pl,v):
    if p.startswith("/blocks/pg/children") and "page_size=50" in p: return {"results":[{"id":"tm","type":"table"}]}
    if "/tm/" in p: raise RuntimeError("rows down")
    return {"results":[]}
main._notion=_t2
try: main._parse_meals("pg"); _r=False
except Exception: _r=True
ok("RP-T2 meal table-rows read fail = raise (not [])", _r)
# T3 malformed meal row -> raise (never partial list)
def _t3(m,p,pl,v):
    if p.startswith("/blocks/pg/children") and "page_size=50" in p: return {"results":[{"id":"tm","type":"table"}]}
    if "/tm/" in p: return {"results":[_RR(["เวลา","รายการ","kcal","p","c","f"]),_RR(["12:00","rice","BAD","20","60","10"])]}
    return {"results":[]}
main._notion=_t3
try: main._parse_meals("pg"); _r=False
except Exception: _r=True
ok("RP-T3 malformed meal row = raise (never drops a meal)", _r)
# T4 genuine no meal table (user table only) -> []
def _t4(m,p,pl,v):
    if p.startswith("/blocks/pg/children") and "page_size=50" in p: return {"results":[{"id":"tu","type":"table"}]}
    if "/tu/" in p: return {"results":[_RR(["date","mood"]),_RR(["1/1","ok"])]}
    return {"results":[]}
main._notion=_t4
ok("RP-T4 verified no meal table = [] (not error)", main._parse_meals("pg")==[])
# T5 lift page-children read fail -> raise
def _t5(m,p,pl,v):
    if p.startswith("/blocks/pg/children"): raise RuntimeError("down")
    return {"results":[]}
main._notion=_t5
try: main._parse_lift_table("pg"); _r=False
except Exception: _r=True
ok("RP-T5 lift page-children read fail = raise (not [])", _r)
# T6 lift table-rows read fail -> raise
def _t6(m,p,pl,v):
    if p.startswith("/blocks/pg/children") and "page_size=50" in p: return {"results":[{"id":"tl","type":"table"}]}
    if "/tl/" in p: raise RuntimeError("rows down")
    return {"results":[]}
main._notion=_t6
try: main._parse_lift_table("pg"); _r=False
except Exception: _r=True
ok("RP-T6 lift table-rows read fail = raise (not [])", _r)
# T7 genuine no lift table -> []
def _t7(m,p,pl,v):
    if p.startswith("/blocks/pg/children") and "page_size=50" in p: return {"results":[{"id":"tu","type":"table"}]}
    if "/tu/" in p: return {"results":[_RR(["date","note"]),_RR(["1/1","x"])]}
    return {"results":[]}
main._notion=_t7
ok("RP-T7 verified no lift table = [] (not error)", main._parse_lift_table("pg")==[])
# lazy lift row stays valid (not malformed)
def _tlazy(m,p,pl,v):
    if p.startswith("/blocks/pg/children") and "page_size=50" in p: return {"results":[{"id":"tl","type":"table"}]}
    if "/tl/" in p: return {"results":[_RR(main._LIFT_HEADER),_RR(["Deadlift","-","-","-","-","-"])]}
    return {"results":[]}
main._notion=_tlazy
ok("RP lazy lift row ('-') stays valid, not malformed", main._parse_lift_table("pg")==[["Deadlift",None,None,None,None]])
# E2E foodlog_get meal read fail -> top-level error + meals != []
def _e2e_f(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"pg","properties":{"kcal":{"number":1}}}]}
    if p.startswith("/blocks/pg/children"): raise RuntimeError("down")
    return {"results":[]}
main._notion=_e2e_f
main._find_row=lambda d:{"id":"pg","properties":{"kcal":{"number":1}}}
_r=main.foodlog_get("2026-08-10")
ok("RP-E2E foodlog_get meal read fail = top-level error + meals is None", "error" in _r and _r.get("meals") is None)
# E2E traininglog_read weights lift read fail -> error, never lifts=[]
def _e2e_t(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"w1","properties":{"session":{"title":[{"plain_text":"Push"}]},"type":{"select":{"name":"weights"}},"date":{"date":{"start":"2026-08-10"}}}}],"has_more":False}
    if p.startswith("/blocks/w1/children"): raise RuntimeError("down")
    return {"results":[]}
main._notion=_e2e_t
_r=main.traininglog_read("2026-08-10",type="weights")
ok("RP-E2E traininglog_read lift read fail = error (never lifts=[])", isinstance(_r,dict) and "error" in _r)

# ================= P2 micro-fix: FoodLog read fail must NOT infer fasted =================
main.call=_orig_call; main._call_cache.clear()
class _GAf:
    def get_activities(s,a,b): return [{"activityId":"88","activityType":{"typeKey":"running"},"startTimeLocal":"2026-08-10T07:00:00","duration":1800,"distance":5000,"averageHR":150}]
    def get_activity(s,aid): return {"activityId":"88","activityName":"Run","activityType":{"typeKey":"running"},"startTimeLocal":"2026-08-10T07:00:00","duration":1800,"distance":5000,"averageHR":150}
    def get_activity_splits(s,aid): return {"lapDTOs":[]}
    def get_activity_hr_in_timezones(s,aid): return []
    def get_activities_by_date(s,*a): return []
    def get_sleep_data(s,d): return {}
main.client=lambda:_GAf(); main._fit_records=lambda aid:[]
main.foodlog_get_range=lambda a,b:[]
_orig_fg=main.foodlog_get
# read FAILURE -> pre_workout_fuel_error present, pre_workout_fuel absent, no fasted
main.foodlog_get=lambda d="":{"date":d,"meals":None,"error":"meal-table-read-failed: down"}
_r=main.analyze_activity()
ok("P2 foodlog read fail = pre_workout_fuel_error, never fasted",
   "pre_workout_fuel_error" in _r and "pre_workout_fuel" not in _r)
# verified EMPTY -> fasted=True still correct
main.foodlog_get=lambda d="":{"date":d,"meals":[]}
_r2=main.analyze_activity()
ok("P2 verified-empty meals still -> fasted=True",
   isinstance(_r2.get("pre_workout_fuel"),dict) and _r2["pre_workout_fuel"].get("fasted") is True)
main.foodlog_get=_orig_fg

# foodlog_upsert echoes the FULL saved table (coach can't show only the new meal)
_seen=[]
def _fu(m,p,pl,v):
    if "query" in p: return {"results":[{"id":"pg","properties":{"kcal":{"number":1}}}]}
    return {"results":[]}
main._notion=_fu; main._notion_write=lambda m,p,pl:{"id":"x"}
main._find_row=lambda d:{"id":"pg","properties":{"kcal":{"number":1}}}
main._replace_table=lambda bid,tb,header=None:_seen.append(1)
_r=main.foodlog_upsert(meals=[["12:00","rice",500,20,60,10],["08:00","egg",160,12,2,10]])
ok("foodlog_upsert returns FULL saved table (sorted) + totals",
   isinstance(_r.get("meals"),list) and len(_r["meals"])==2 and _r["meals"][0][0]=="08:00"
   and _r.get("totals",{}).get("kcal")==660)

# ================= FoodLib dedup + smart search =================
os.environ["NOTION_FOODLIB_DS"]="flib"
FL=[{"id":"f1","properties":{"name":{"title":[{"plain_text":"Whey Shake 350ml"}]},"kcal":{"number":190},"p":{"number":35}}},
    {"id":"f2","properties":{"name":{"title":[{"plain_text":"ไข่ต้ม 1 ฟอง"}]},"kcal":{"number":70}}}]
def _fln(m,p,pl,v):
    if "query" in p: return {"results":FL,"has_more":False}
    if p=="/pages": return {"id":"newf"}
    return {"results":[]}
main._notion=_fln; main._notion_write=lambda m,p,pl:{"id":"x"}
main._call_cache.clear()
_r=main.foodlib_find("whey")
ok("foodlib_find case-insensitive finds 'Whey' + page_id", bool(_r) and _r[0].get("page_id")=="f1")
main._call_cache.clear()
ok("foodlib_find thai contains match", (lambda r: bool(r) and r[0]["name"].startswith("ไข่ต้ม"))(main.foodlib_find("ไข่ต้ม")))
main._call_cache.clear()
_r=main.foodlib_upsert(name="Whey Shake 350ml", c=9)
ok("foodlib_upsert exact name = UPDATE (no dup)", _r["status"]=="updated" and _r["page_id"]=="f1")
main._call_cache.clear()
_r=main.foodlib_upsert(name="Totally New Snack 50g", kcal=100)
ok("foodlib_upsert new name = create", _r["status"]=="created" and _r["page_id"]=="newf")
main._call_cache.clear()
_r=main.foodlib_upsert(name="Whey Shake", kcal=190)
ok("foodlib_upsert flags similar_existing (near-dup nudge)", _r["status"]=="created" and "similar_existing" in _r and any("350ml" in s for s in _r["similar_existing"]))
main._call_cache.clear()
_r=main.foodlib_upsert(name="Anything", page_id="f2", kcal=75)
ok("foodlib_upsert page_id = precise update", _r["status"]=="updated" and _r["page_id"]=="f2")

# ================= Phase 1: category tag + cardio de-fragmentation =================
ok("category: weights->weight", main._category("weights")=="weight")
ok("category: tempo->cardio", main._category("tempo")=="cardio" and main._category("walk")=="cardio")
ok("category: hyrox->hiit", main._category("hyrox-sim")=="hiit")
ok("category: unknown->other", main._category("yoga")=="other")
# fragmented run: warmup 16:00(10m) + main 16:15(30m) + cooldown 16:50(5m) = 1 group; evening 20:00 = 2nd
_A=[{"startTimeLocal":"2026-09-01 16:00:00","duration":600},
    {"startTimeLocal":"2026-09-01 16:15:00","duration":1800},
    {"startTimeLocal":"2026-09-01 16:50:00","duration":300},
    {"startTimeLocal":"2026-09-01 20:00:00","duration":1200}]
ok("group_activities: 4 fragmented acts -> 2 real sessions", len(main._group_activities(_A))==2)
ok("group_activities: different day = separate group",
   len(main._group_activities([{"startTimeLocal":"2026-09-01 16:00:00","duration":600},
                               {"startTimeLocal":"2026-09-02 16:05:00","duration":600}]))==2)
ok("group_activities: unparseable start still kept (not dropped)",
   len(main._group_activities([{"startTimeLocal":None,"duration":0}]))==1)

print("\n=== %d passed, %d failed ===" % (P[0], len(F)))
if F: print("FAILURES:", F); raise SystemExit(1)
