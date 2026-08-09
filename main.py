"""Garmin MCP server — personal health data bridge for Claude.

Env vars:
  GARMINTOKENS_B64  base64 Garmin OAuth token (from gen_token.py)
  MCP_SECRET        secret path segment so only you can reach the server
  PORT              set by Cloud Run
"""
import os
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

mcp = FastMCP(
    "garmin",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_garmin = None


def client():
    """Lazy login; reuse session across requests in the same instance."""
    global _garmin
    if _garmin is None:
        from garminconnect import Garmin
        g = Garmin()
        try:
            g.login(os.environ["GARMINTOKENS_B64"])
        except Exception:
            email = os.environ.get("GARMIN_EMAIL")
            pw = os.environ.get("GARMIN_PASSWORD")
            if not (email and pw):
                raise
            g = Garmin(email=email, password=pw)
            g.login()
        _garmin = g
    return _garmin


# Universal noise keys stripped from every Garmin response: array-format
# descriptors (useless once the array itself is dropped), chart-rendering
# offsets, internal profile ids, and redundant timestamp variants.
_JUNK_SUFFIX = ("DescriptorDTOList", "DescriptorsDTOList", "ValueDescriptorDTOList",
                "ValueDescriptorsDTOList", "ChartValueOffset", "ChartYAxisOrigin")
_JUNK_EXACT = ("userProfilePK", "userProfileId", "userDailySummaryId", "uuid",
               "startTimestampGMT", "endTimestampGMT",
               "startTimestampLocal", "endTimestampLocal")


def _is_junk(k):
    return k in _JUNK_EXACT or k.endswith(_JUNK_SUFFIX)


def slim(obj, max_list=40, depth=0):
    """Drop huge time-series arrays + universal metadata noise so responses stay small."""
    if depth > 8:
        return "..."
    if isinstance(obj, dict):
        return {k: slim(v, max_list, depth + 1)
                for k, v in obj.items() if v is not None and not _is_junk(k)}
    if isinstance(obj, list):
        if len(obj) > max_list:
            return f"<{len(obj)} data points omitted>"
        return [slim(v, max_list, depth + 1) for v in obj]
    if isinstance(obj, float):
        return round(obj, 3)
    return obj


def _today_local():
    # Single source of truth for "today". Cloud Run runs in UTC, so a bare
    # date.today() is up to 7h behind and mis-files 00:00-07:00 events to the
    # previous day. Everything that means "the user's today" must go through here.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(os.environ.get("TZ_NAME", "Asia/Bangkok"))).date()


def day(d: str) -> str:
    today = _today_local()
    if not d or d == "today":
        return today.isoformat()
    if d == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return d


def _tabulate(obj):
    """Compact a homogeneous list of dicts into cols/rows (keys sent once, not per row)."""
    if isinstance(obj, list) and len(obj) >= 3 and all(isinstance(x, dict) for x in obj):
        cols = []
        for x in obj:
            for k in x:
                if k not in cols:
                    cols.append(k)
        if len(cols) >= 4:
            return {"cols": cols, "rows": [[x.get(c) for c in cols] for x in obj]}
    if isinstance(obj, dict):
        return {k: _tabulate(v) for k, v in obj.items()}
    return obj


_call_cache = {}  # key -> (ts, value, ttl_seconds)
_usage = {}  # tool -> [calls, chars, cache_hits]


def _cget(key):
    import time as _t
    hit = _call_cache.get(key)
    if hit and _t.time() - hit[0] < hit[2]:
        return hit[1]
    return None


def _cput(key, val, ttl):
    import time as _t
    _call_cache[key] = (_t.time(), val, ttl)
    if len(_call_cache) > 800:
        _call_cache.clear()


def _bump(tool, result):
    import json as _j
    u = _usage.setdefault(tool, [0, 0, 0])
    u[0] += 1
    try:
        u[1] += len(_j.dumps(result, default=str))
    except Exception:
        pass
    return u


def _contains_error(obj):
    """True if a dict/list contains an 'error' key anywhere (so partial-failure composite results
    like get_coach_snapshot with out['sleep']={'error':...} are NOT cached as if successful)."""
    if isinstance(obj, dict):
        return "error" in obj or any(_contains_error(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_error(v) for v in obj)
    return False


def call(fn, *args, retry=True, ckey=None):
    global _garmin
    import sys
    import time as _t
    tool = sys._getframe(1).f_code.co_name
    key = (tool, ckey if ckey is not None else args)  # ckey = explicit key when args are hidden in a closure
    cacheable = tool.startswith("get_")
    if cacheable:
        hit = _cget(key)
        if hit is not None:
            _bump(tool, hit)[2] += 1
            return hit
    try:
        r = _tabulate(slim(fn(client())(*args)))
    except Exception as e:
        if not retry:
            return {"error": str(e)}  # non-idempotent write — never blind-retry (avoid duplicates)
        _garmin = None  # token likely expired in-session: retry once with fresh login
        try:
            r = _tabulate(slim(fn(client())(*args)))
        except Exception as e2:
            return {"error": str(e2)}
    if cacheable and not _contains_error(r):
        _cput(key, r, 600)
    _bump(tool, r)
    return r


_SLEEP_NOISE = (
    "sleepLevels", "sleepMovement", "sleepRestlessMoments", "sleepHeartRate",
    "sleepStress", "sleepBodyBattery", "hrvData", "breathingDisruptionData",
    "wellnessEpochRespirationDataDTOList", "wellnessEpochRespirationAveragesList",
    "wellnessEpochSPO2DataDTOList", "sleepNeed", "nextSleepNeed",
)


def get_sleep(date: str = "", full: bool = False) -> dict:
    """Sleep for a night: score, duration, deep/light/REM/awake, HRV during sleep, resting HR, body battery change. date=YYYY-MM-DD, default today (i.e. last night). full=true returns raw time-series too."""
    r = call(lambda g: g.get_sleep_data, day(date))
    if not full and isinstance(r, dict):
        r = {k: v for k, v in r.items() if k not in _SLEEP_NOISE}
    return r


def get_hrv(date: str = "") -> dict:
    """HRV status for a night: last-night avg, weekly avg, baseline, status. date=YYYY-MM-DD."""
    return call(lambda g: g.get_hrv_data, day(date))


def get_stress(date: str = "") -> dict:
    """All-day stress summary for a date."""
    return call(lambda g: g.get_stress_data, day(date))


def get_body_battery(date: str = "") -> dict:
    """Body Battery levels for a date (charged/drained, high/low)."""
    d = day(date)
    return call(lambda g: g.get_body_battery, d, d)


_DS_KEYS = ("calendarDate", "totalKilocalories", "activeKilocalories", "bmrKilocalories",
            "totalSteps", "dailyStepGoal", "totalDistanceMeters",
            "moderateIntensityMinutes", "vigorousIntensityMinutes", "intensityMinutesGoal",
            "restingHeartRate", "lastSevenDaysAvgRestingHeartRate", "minHeartRate", "maxHeartRate",
            "averageStressLevel", "bodyBatteryMostRecentValue", "bodyBatteryAtWakeTime",
            "bodyBatteryHighestValue", "bodyBatteryLowestValue",
            "sleepingSeconds", "floorsAscended", "lastSyncTimestampGMT")


@mcp.tool()
def get_daily_summary(date: str = "", full: bool = False) -> dict:
    """Daily wellness summary: steps, calories, distance, intensity minutes, heart rate, stress, body battery. Compact by default; full=true returns every raw field."""
    r = call(lambda g: g.get_stats, day(date))
    if full or not isinstance(r, dict):
        return r
    return {k: r[k] for k in _DS_KEYS if k in r}


def get_heart_rate(date: str = "") -> dict:
    """Heart rate summary for a date: resting, min, max, last 7 days avg resting."""
    return call(lambda g: g.get_heart_rates, day(date))


def get_spo2(date: str = "") -> dict:
    """Blood oxygen (SpO2) summary for a date."""
    return call(lambda g: g.get_spo2_data, day(date))


def get_respiration(date: str = "") -> dict:
    """Respiration rate summary for a date."""
    return call(lambda g: g.get_respiration_data, day(date))


def get_training_readiness(date: str = "") -> dict:
    """Training readiness score and contributing factors."""
    return call(lambda g: g.get_training_readiness, day(date))


def get_training_status(date: str = "") -> dict:
    """Training status: load, VO2max, acute/chronic load."""
    return call(lambda g: g.get_training_status, day(date))


# Compact keep-list for activity LISTS (coach_snapshot, get_activities, analyze).
# Running-form / power detail (vertical oscillation, ground contact, stride length,
# avgPower, maxSpeed) is intentionally omitted here — fetch it on demand via
# get_activity(view="summary"), which returns the full untrimmed activity.
_ACT_KEEP = (
    "activityId", "activityName", "startTimeLocal", "distance",
    "duration", "calories", "averageHR", "maxHR", "averageSpeed",
    "activityType", "aerobicTrainingEffect", "anaerobicTrainingEffect",
    "averageRunningCadenceInStepsPerMinute", "vO2MaxValue",
)


def _act_slim(acts):
    return [{k: a.get(k) for k in _ACT_KEEP if a.get(k) is not None} for a in (acts or [])]


def _activities_recent(limit: int = 10) -> list | dict:
    """Recent activities (runs, rides, workouts...). Returns key fields per activity."""
    return call(lambda g: lambda: _act_slim(g.get_activities(0, min(limit, 50))))


def get_body_composition(date: str = "") -> dict:
    """Weight / body composition entries for a date."""
    return call(lambda g: g.get_body_composition, day(date))


def get_activity_details(activity_id: str) -> dict:
    """Full summary of one activity: cadence, power, VO2max, running dynamics, weather. Get activity_id from get_activities."""
    return call(lambda g: g.get_activity, activity_id)


def get_activity_splits(activity_id: str) -> dict:
    """Per-lap/km splits of one activity: pace, HR, cadence per split."""
    return call(lambda g: g.get_activity_splits, activity_id)


def get_activity_hr_zones(activity_id: str) -> list | dict:
    """Time spent in each heart-rate zone for one activity."""
    return call(lambda g: g.get_activity_hr_in_timezones, activity_id)


def get_activities_range(start_date: str, end_date: str = "", activity_type: str = "") -> list | dict:
    """Activities between two dates (YYYY-MM-DD). Optional activity_type: running, cycling, swimming, fitness_equipment..."""
    return call(lambda g: lambda: _act_slim(g.get_activities_by_date(start_date, end_date or None, activity_type or None)), ckey=(start_date, end_date, activity_type))


def get_race_predictions() -> dict:
    """Predicted race times for 5K, 10K, half marathon, marathon."""
    return call(lambda g: lambda: g.get_race_predictions())


def get_vo2max(date: str = "") -> dict:
    """VO2max and max metrics for a date."""
    return call(lambda g: g.get_max_metrics, day(date))


def get_fitness_age(date: str = "") -> dict:
    """Fitness age estimate and contributing factors."""
    return call(lambda g: g.get_fitnessage_data, day(date))


def get_endurance_score(date: str = "") -> dict:
    """Endurance score for a date."""
    return call(lambda g: g.get_endurance_score, day(date))


def get_hill_score(date: str = "") -> dict:
    """Hill score (running strength on hills) for a date."""
    return call(lambda g: g.get_hill_score, day(date))


def get_personal_records() -> list | dict:
    """All personal records (fastest 1K/5K/10K, longest run/ride, max steps...)."""
    return call(lambda g: lambda: g.get_personal_record())


@mcp.tool()
def get_weight_history(start_date: str, end_date: str = "") -> dict:
    """Weigh-in history between dates (YYYY-MM-DD)."""
    return call(lambda g: lambda: g.get_weigh_ins(start_date, end_date or day("")), ckey=(start_date, end_date))


def get_hydration(date: str = "") -> dict:
    """Water intake logged for a date."""
    return call(lambda g: g.get_hydration_data, day(date))


def get_blood_pressure(start_date: str = "", end_date: str = "") -> dict:
    """Blood pressure readings between dates (if logged in Garmin Connect)."""
    return call(lambda g: lambda: g.get_blood_pressure(start_date or day(""), end_date or None), ckey=(start_date, end_date))


def get_intensity_minutes(date: str = "") -> dict:
    """Intensity minutes (moderate/vigorous) for a date."""
    return call(lambda g: g.get_intensity_minutes_data, day(date))


def get_lactate_threshold() -> dict:
    """Latest lactate threshold (pace and heart rate)."""
    return call(lambda g: lambda: g.get_lactate_threshold(latest=True))


@mcp.tool()
def add_body_composition(
    weight_kg: float,
    percent_fat: float | None = None,
    muscle_mass_kg: float | None = None,
    bone_mass_kg: float | None = None,
    percent_hydration: float | None = None,
    visceral_fat_rating: float | None = None,
    metabolic_age: float | None = None,
    bmi: float | None = None,
    basal_met: float | None = None,
    timestamp: str = "",
) -> dict:
    """WRITE a weigh-in with body composition (e.g. from InBody) into Garmin Connect.
    Only call when the user explicitly asks to save/record. timestamp=YYYY-MM-DDTHH:MM:SS, default now."""
    def f(g):
        r = g.add_body_composition(
            timestamp or None,
            weight=weight_kg,
            percent_fat=percent_fat,
            percent_hydration=percent_hydration,
            bone_mass=bone_mass_kg,
            muscle_mass=muscle_mass_kg,
            basal_met=basal_met,
            metabolic_age=metabolic_age,
            visceral_fat_rating=visceral_fat_rating,
            bmi=bmi,
        )
        return {"status": "saved", "response": r}
    return call(lambda g: lambda: f(g), retry=False)


@mcp.tool()
def get_coach_snapshot() -> dict:
    """ONE-CALL coaching snapshot: today's training readiness, last night's sleep summary (score/HRV/RHR/body battery), today's status, and last 7 days activities (compact). Prefer this over separate calls for daily coaching questions."""
    def f(g):
        from datetime import date as _d, timedelta as _td
        today = _today_local().isoformat()
        week_ago = (_today_local() - _td(days=7)).isoformat()
        out = {}
        try:
            tr = g.get_training_readiness(today)
            if isinstance(tr, list) and tr:
                tr = tr[0]
            if isinstance(tr, dict):
                keys = ("score", "level", "feedbackShort", "sleepScore",
                        "recoveryTime", "acuteLoad", "hrvFactorPercent",
                        "sleepHistoryFactorPercent")
                tr = {k: tr.get(k) for k in keys if tr.get(k) is not None}
            out["readiness"] = tr
        except Exception as e:
            out["readiness"] = {"error": str(e)}
        try:
            s = g.get_sleep_data(today) or {}
            dto = s.get("dailySleepDTO") or {}
            out["sleep"] = {
                "score": ((dto.get("sleepScores") or {}).get("overall") or {}).get("value"),
                "sleepTimeSeconds": dto.get("sleepTimeSeconds"),
                "deepSeconds": dto.get("deepSleepSeconds"),
                "remSeconds": dto.get("remSleepSeconds"),
                "awakeSeconds": dto.get("awakeSleepSeconds"),
                "avgOvernightHrv": s.get("avgOvernightHrv"),
                "hrvStatus": s.get("hrvStatus"),
                "restingHeartRate": s.get("restingHeartRate"),
                "bodyBatteryChange": s.get("bodyBatteryChange"),
            }
        except Exception as e:
            out["sleep"] = {"error": str(e)}
        try:
            ds = g.get_stats(today) or {}
            keys = ("totalSteps", "totalKilocalories", "restingHeartRate",
                    "lastSevenDaysAvgRestingHeartRate", "bodyBatteryMostRecentValue",
                    "averageStressLevel")
            out["today"] = {k: ds.get(k) for k in keys}
        except Exception as e:
            out["today"] = {"error": str(e)}
        try:
            acts = g.get_activities_by_date(week_ago, today) or []
            keep = ("activityName", "startTimeLocal", "distance", "duration",
                    "calories", "averageHR", "maxHR", "aerobicTrainingEffect",
                    "anaerobicTrainingEffect")
            out["last7d_activities"] = [
                {k: a.get(k) for k in keep if a.get(k) is not None} for a in acts]
        except Exception as e:
            out["last7d_activities"] = {"error": str(e)}
        return out
    return call(lambda g: lambda: f(g))


# ---- Nightly close-day: write real TDEE from Garmin into Notion FoodLog ----
import json as _json
import urllib.request as _url

FOODLOG_DS = os.environ.get("NOTION_FOODLOG_DS", "")
TRAINING_DS = os.environ.get("NOTION_TRAININGLOG_DS", "")
EXERCISELIB_DS = os.environ.get("NOTION_EXERCISELIB_DS", "")
BODYMETRICS_DS = os.environ.get("NOTION_BODYMETRICS_DS", "")


def _notion(method, path, payload, version):
    req = _url.Request(
        "https://api.notion.com/v1" + path,
        data=_json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Authorization": "Bearer " + os.environ.get("NOTION_TOKEN", ""),
            "Notion-Version": version,
            "Content-Type": "application/json",
        },
    )
    with _url.urlopen(req, timeout=30) as r:
        return _json.loads(r.read())


def _notion_query_all(ds, filt=None):
    """Query a Notion db/data_source following pagination — for places that need COMPLETE history
    (avoids silent truncation at 100 as history grows). Returns the flat list of result rows."""
    out, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if filt:
            payload["filter"] = filt
        if cursor:
            payload["start_cursor"] = cursor
        try:
            r = _notion("POST", f"/databases/{ds}/query", payload, "2022-06-28")
        except Exception:
            r = _notion("POST", f"/data_sources/{ds}/query", payload, "2025-09-03")
        out.extend(r.get("results", []))
        if not r.get("has_more"):
            break
        cursor = r.get("next_cursor")
    return out


def _find_row(d):
    flt = {"filter": {"property": "date", "date": {"equals": d}}}
    try:
        r = _notion("POST", f"/databases/{FOODLOG_DS}/query", flt, "2022-06-28")
    except Exception:
        r = _notion("POST", f"/data_sources/{FOODLOG_DS}/query", flt, "2025-09-03")
    res = r.get("results", [])
    return res[0] if res else None


def _deficit_val(props):
    """deficit_actual may be a number (legacy) or a formula property (v10.2+)."""
    d = props.get("deficit_actual") or {}
    if d.get("type") == "formula" or "formula" in d:
        return (d.get("formula") or {}).get("number")
    return d.get("number")


_CARDIO = ("running", "cycling", "walking", "treadmill_running",
           "indoor_cycling", "lap_swimming", "open_water_swimming")
CARDIO_BURN_FACTOR = 0.90  # conservative user-set adjustment on Garmin kcal
OTHER_BURN_FACTOR = 0.85


def _fmt_dur(sec):
    sec = int(sec or 0)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _parse_dur(txt):
    """'1:11:18' or '45:31' -> seconds. Reverse of _fmt_dur."""
    try:
        parts = [int(x) for x in (txt or "").strip().split(":")]
    except Exception:
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return None


def _fmt_pace(sec, km):
    if not km:
        return ""
    p = int((sec or 0) / km)
    return f"{p // 60}:{p % 60:02d} /km"


def _tl_type(a):
    name = (a.get("activityName") or "").lower()
    t = ((a.get("activityType") or {}).get("typeKey") or "").lower()
    if "hyrox" in name:
        return "hyrox-sim"
    if "muay" in name or "boxing" in t or "kickbox" in t:
        return "muay-thai"
    if "run" in t or "run" in name:
        return "run"
    if "cycl" in t or "bik" in t or "ride" in name:
        return "ride"
    if "walk" in t or "hik" in t:
        return "walk"
    if "strength" in t or "weight" in t:
        return "weights"
    return "other"


_TE_LABEL_MAP = (
    ("RECOVERY", "recovery-run"), ("AEROBIC_BASE", "run"), ("BASE", "run"),
    ("TEMPO", "tempo"), ("THRESHOLD", "threshold"), ("VO2MAX", "vo2max"),
    ("ANAEROBIC", "interval"), ("SPRINT", "interval"),
)


def _run_subtype(aid):
    """Garmin's own trainingEffectLabel -> run subtype for the TrainingLog `type` select.
    Tolerant: returns None on ANY failure so _log_training always falls back to the basic
    type and the row is still created. Uses Garmin's classification, not a home-made one."""
    try:
        det = client().get_activity(str(aid)) or {}
        lbl = (((det.get("summaryDTO") or {}).get("trainingEffectLabel")) or "").upper()
        for key, val in _TE_LABEL_MAP:
            if key in lbl:
                return val
    except Exception:
        pass
    return None



def _log_training(d, acts):
    """Cron auto-creates a bare TrainingLog row per Garmin activity (idempotent by
    date+session title). Coach enriches coach_notes/body_signals later in chat."""
    if not TRAINING_DS or not acts:
        return {"created": 0, "failed": 0}
    existing = []
    try:
        flt = {"filter": {"property": "date", "date": {"equals": d}}, "page_size": 100}
        try:
            r = _notion("POST", f"/databases/{TRAINING_DS}/query", flt, "2022-06-28")
        except Exception:
            r = _notion("POST", f"/data_sources/{TRAINING_DS}/query", flt, "2025-09-03")
        for row in r.get("results", []):
            rp = row.get("properties", {})
            ti = (rp.get("session") or {}).get("title") or []
            dt = (rp.get("duration") or {}).get("rich_text") or []
            gd = (rp.get("garmin_activity_id") or {}).get("rich_text") or []
            existing.append({"title": "".join(x.get("plain_text", "") for x in ti).lower(),
                             "km": (rp.get("distance_km") or {}).get("number"),
                             "sec": _parse_dur("".join(x.get("plain_text", "") for x in dt)),
                             "gid": "".join(x.get("plain_text", "") for x in gd)})
    except Exception:
        return {"created": 0, "failed": 0}

    def _is_dup(aid, name, km):
        """PRIMARY identity = Garmin activityId (exact). Fallback for legacy rows without an id =
        name-substring + distance (never duration alone — two different workouts can share a duration)."""
        aid = str(aid) if aid else ""
        for e in existing:
            if aid and e.get("gid") and aid == e["gid"]:
                return True
        n = (name or "").lower().strip()
        for e in existing:
            if e.get("gid"):
                continue  # id-tagged rows already checked above
            if n and (e["title"] == n or n in e["title"]):
                if km and e["km"]:
                    if abs(km - e["km"]) < 0.2:
                        return True
                elif not km and not e["km"]:
                    return True
        return False
    made = 0
    failed = 0
    for a in acts:
        name = a.get("activityName") or ((a.get("activityType") or {}).get("typeKey") or "activity")
        tkey = ((a.get("activityType") or {}).get("typeKey") or "")
        dur = a.get("duration") or 0
        km = (a.get("distance") or 0) / 1000.0
        btype = _tl_type(a)
        if _is_dup(a.get("activityId"), name, round(km, 2) if km else None):
            continue
        cals = a.get("calories") or 0
        props = {
            "session": {"title": [{"text": {"content": name[:200]}}]},
            "date": {"date": {"start": d}},
            "type": {"select": {"name": (_run_subtype(a.get("activityId")) or btype) if btype == "run" else btype}},
            "kcal_burn_app": {"number": round(cals)},
            "kcal_burn_adjusted": {"number": round(cals * (CARDIO_BURN_FACTOR if tkey in _CARDIO else OTHER_BURN_FACTOR))},
        }
        if a.get("activityId"):
            props["garmin_activity_id"] = {"rich_text": [{"text": {"content": str(a["activityId"])}}]}
        if km:
            props["distance_km"] = {"number": round(km, 2)}
        if dur:
            props["duration"] = {"rich_text": [{"text": {"content": _fmt_dur(dur)}}]}
        if km and dur:
            props["pace"] = {"rich_text": [{"text": {"content": _fmt_pace(dur, km)}}]}
        if a.get("averageHR"):
            props["avg_hr"] = {"number": round(a["averageHR"])}
        if a.get("maxHR"):
            props["max_hr"] = {"number": round(a["maxHR"])}
        if a.get("aerobicTrainingEffect") is not None:
            props["training_effect_aerobic"] = {"number": round(a["aerobicTrainingEffect"], 1)}
        if a.get("anaerobicTrainingEffect") is not None:
            props["training_effect_anaerobic"] = {"number": round(a["anaerobicTrainingEffect"], 1)}
        try:
            try:
                _notion("POST", "/pages",
                        {"parent": {"database_id": TRAINING_DS}, "properties": props}, "2022-06-28")
            except Exception:
                _notion("POST", "/pages",
                        {"parent": {"type": "data_source_id", "data_source_id": TRAINING_DS},
                         "properties": props}, "2025-09-03")
            made += 1
        except Exception:
            failed += 1
    return {"created": made, "failed": failed}


def _recovery_props(d):
    """A day's recovery metrics from Garmin as Notion number props (non-None only).
    Sleep for day D = the night ending the morning of D. Pure data-gather, no writes."""
    out = {}
    try:
        s = client().get_sleep_data(d) or {}
        dto = s.get("dailySleepDTO") or {}
        secs = dto.get("sleepTimeSeconds")
        for k, v in {
            "sleep_score": ((dto.get("sleepScores") or {}).get("overall") or {}).get("value"),
            "sleep_hrs": round(secs / 3600, 1) if secs else None,
            "hrv": s.get("avgOvernightHrv"),
            "rhr": s.get("restingHeartRate"),
            "body_battery_change": s.get("bodyBatteryChange"),
        }.items():
            if v is not None:
                out[k] = {"number": v}
    except Exception:
        pass
    try:
        tr = client().get_training_readiness(d)
        if isinstance(tr, list) and tr:
            tr = tr[0]
        if isinstance(tr, dict) and tr.get("score") is not None:
            out["readiness"] = {"number": tr["score"]}
    except Exception:
        pass
    return out



def _close_one(d):
    # Auto-log workouts to TrainingLog FIRST — independent of whether food was
    # logged that day (a training day with no food row must still get its rows).
    try:
        acts = client().get_activities_by_date(d, d) or []
        acts_ok = True
    except Exception:
        acts = []
        acts_ok = False  # unknown activity state — do NOT infer "no activity"
    try:
        trained = _log_training(d, acts)
    except Exception:
        trained = {"created": 0, "failed": 0}
    row = _find_row(d)
    if not row:
        return {"date": d, "status": "no-foodlog-row", "trained": trained}
    props = row.get("properties", {})
    kcal = (props.get("kcal") or {}).get("number")
    row_burn = (props.get("exercise_burn") or {}).get("number") or 0
    try:
        stats = client().get_stats(d) or {}
    except Exception:
        stats = {}
    total = stats.get("totalKilocalories")
    new_props = {}
    if total:
        tdee = round(total)
        if acts_ok and not acts and row_burn:
            tdee = round(total + row_burn)
        tag = "synced"
    else:
        base = os.environ.get("TDEE_BASELINE", "")
        if not base:
            return {"date": d, "status": "no-garmin-data"}
        tdee = round(float(base) + row_burn)
        tag = "estimated"
    old = (props.get("tdee_est") or {}).get("number")
    old_tag = (((props.get("sync") or {}).get("select")) or {}).get("name")
    if old is None or abs(old - tdee) >= 1 or old_tag != tag:
        new_props["tdee_est"] = {"number": tdee}
        if kcal is not None and (props.get("deficit_actual") or {}).get("type") == "number":
            new_props["deficit_actual"] = {"number": tdee - kcal}
        new_props["sync"] = {"select": {"name": tag}}
    if acts:
        names, burn = [], 0.0
        for a in acts:
            t = ((a.get("activityType") or {}).get("typeKey") or "")
            burn += (a.get("calories") or 0) * (CARDIO_BURN_FACTOR if t in _CARDIO else OTHER_BURN_FACTOR)
            names.append(a.get("activityName") or t)
        if not ((props.get("exercise_type") or {}).get("rich_text") or []):
            new_props["exercise_type"] = {"rich_text": [{"text": {"content": ", ".join(names)[:200]}}]}
        if (props.get("exercise_burn") or {}).get("number") in (None, 0):
            new_props["exercise_burn"] = {"number": round(burn)}
    # recovery: same pattern as exercise_type/burn above — add only if this day's row
    # doesn't already carry it (keeps the nightly 3-day re-close from refetching).
    if any((props.get(k) or {}).get("number") is None for k in ("sleep_score", "readiness")):
        new_props.update(_recovery_props(d))
    if not new_props:
        return {"date": d, "status": "already-synced", "tdee": tdee, "trained": trained}
    _notion_write("PATCH", "/pages/" + row["id"], {"properties": new_props})
    return {"date": d, "status": "updated", "tdee": tdee, "tag": tag,
            "wrote": list(new_props), "trained": trained}


def _update_progress(page_id):
    total, days = 0.0, 0
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        try:
            r = _notion("POST", f"/databases/{FOODLOG_DS}/query", payload, "2022-06-28")
        except Exception:
            r = _notion("POST", f"/data_sources/{FOODLOG_DS}/query", payload, "2025-09-03")
        for row in r.get("results", []):
            v = _deficit_val(row.get("properties", {}))
            if v is not None:
                total += v
                days += 1
        if not r.get("has_more"):
            break
        cursor = r.get("next_cursor")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(os.environ.get("TZ_NAME", "Asia/Bangkok"))).date().isoformat()
    text = (f"\U0001F525 Total deficit: {round(total):,} kcal \u2248 {total/7700:.1f} kg fat "
            f"| logged days: {days} | updated {today}")
    kids = _notion("GET", f"/blocks/{page_id}/children?page_size=100", None, "2022-06-28")
    block_id = None
    for b in kids.get("results", []):
        if b.get("type") == "callout":
            rt = (b.get("callout") or {}).get("rich_text") or []
            if rt and rt[0].get("plain_text", "").startswith("\U0001F525"):
                block_id = b["id"]
                break
    body = {"callout": {"rich_text": [{"type": "text", "text": {"content": text}}]}}
    if block_id:
        _notion("PATCH", "/blocks/" + block_id, body, "2022-06-28")
    else:
        _notion("PATCH", f"/blocks/{page_id}/children",
                {"children": [{"object": "block", "type": "callout",
                               "callout": {"rich_text": [{"type": "text", "text": {"content": text}}],
                                           "icon": {"type": "emoji", "emoji": "\U0001F525"}}}]},
                "2022-06-28")
    return {"progress": text}


async def health(request):
    """Setup self-check: which env vars are set + is Notion / playbook reachable.
    Values are never returned — only booleans/statuses. Behind the secret path."""
    from starlette.responses import JSONResponse
    keys = ["MCP_SECRET", "GARMINTOKENS_B64", "NOTION_TOKEN", "NOTION_FOODLOG_DS",
            "NOTION_FOODLIB_DS", "NOTION_TRAININGLOG_DS", "NOTION_BODYMETRICS_DS", "CONFIG_PAGE_ID", "D1_DATE",
            "PLAYBOOK_URL", "TDEE_BASELINE", "PROGRESS_PAGE_ID", "TZ_NAME"]
    env = {k: bool(os.environ.get(k)) for k in keys}
    missing = [k for k, v in env.items() if not v]
    checks = {}
    try:
        try:
            _notion("POST", f"/databases/{FOODLOG_DS}/query", {"page_size": 1}, "2022-06-28")
        except Exception:
            _notion("POST", f"/data_sources/{FOODLOG_DS}/query", {"page_size": 1}, "2025-09-03")
        checks["notion_foodlog"] = "ok"
    except Exception as e:
        checks["notion_foodlog"] = f"FAIL: {str(e)[:150]}"
    for dsname, dsid in (("notion_foodlib", os.environ.get("NOTION_FOODLIB_DS", "")),
                         ("notion_traininglog", os.environ.get("NOTION_TRAININGLOG_DS", "")),
                         ("notion_exerciselib", os.environ.get("NOTION_EXERCISELIB_DS", ""))):
        if not dsid:
            checks[dsname] = "not-set"
            continue
        try:
            try:
                _notion("POST", f"/databases/{dsid}/query", {"page_size": 1}, "2022-06-28")
            except Exception:
                _notion("POST", f"/data_sources/{dsid}/query", {"page_size": 1}, "2025-09-03")
            checks[dsname] = "ok"
        except Exception as e:
            checks[dsname] = f"FAIL: {str(e)[:150]}"
    try:
        checks["playbook"] = "ok" if len(_pb_fetch()) > 100 else "empty"
    except Exception as e:
        checks["playbook"] = f"FAIL: {str(e)[:150]}"
    ok = not missing and checks.get("notion_foodlog") == "ok"
    return JSONResponse({"ok": ok, "missing_env": missing, "env_set": env, "checks": checks})


async def closeday(request):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from starlette.responses import JSONResponse
    today = datetime.now(ZoneInfo(os.environ.get("TZ_NAME", "Asia/Bangkok"))).date()
    out = []
    # TODAY: auto-log finished workouts to TrainingLog (do NOT close the day for TDEE —
    # the day isn't over). A completed activity is loggable the moment it syncs.
    try:
        td = today.isoformat()
        acts0 = client().get_activities_by_date(td, td) or []
        out.append({"date": td, "status": "today-training-only", "trained": _log_training(td, acts0)})
    except Exception as e:
        out.append({"date": today.isoformat(), "training_error": str(e)})
    for i in range(1, 4):
        d = (today - timedelta(days=i)).isoformat()
        try:
            out.append(_close_one(d))
        except Exception as e:
            try:
                row = _find_row(d)
                if row:
                    _notion_write("PATCH", "/pages/" + row["id"],
                                  {"properties": {"sync": {"select": {"name": "error"}}}})
            except Exception:
                pass
            out.append({"date": d, "error": str(e)})
    page_id = os.environ.get("PROGRESS_PAGE_ID", "")
    if page_id:
        try:
            out.append(_update_progress(page_id))
        except Exception as e:
            out.append({"progress_error": str(e)})
    return JSONResponse(out)


# ---- FIT streams & aerobic decoupling ---------------------------------------
def _fit_records(activity_id: str) -> list:
    import io
    import zipfile
    import fitdecode
    from garminconnect import Garmin as _G
    g = client()
    data = g.download_activity(str(activity_id),
                               dl_fmt=_G.ActivityDownloadFormat.ORIGINAL)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".fit"))
        fit_bytes = z.read(name)
    recs = []
    with fitdecode.FitReader(io.BytesIO(fit_bytes)) as fr:
        for frame in fr:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "record":
                row = {}
                for f in ("timestamp", "heart_rate", "speed", "cadence",
                          "power", "altitude", "distance"):
                    if frame.has_field(f) and frame.get_value(f) is not None:
                        row[f] = frame.get_value(f)
                if row.get("timestamp") is not None:
                    recs.append(row)
    return recs


def _moving_time_split(rows, max_gap=10.0):
    """Index that splits rows at HALF of moving time (sum of dt between samples, capping pause gaps)
    instead of half the sample count — robust to pauses / Smart Recording where samples are not
    uniformly spaced. Pure/testable. Falls back to the midpoint if timestamps are unusable."""
    if len(rows) < 3:
        return len(rows) // 2
    dts = [0.0]
    for i in range(1, len(rows)):
        try:
            dt = (rows[i]["timestamp"] - rows[i - 1]["timestamp"]).total_seconds()
        except Exception:
            dt = 0.0
        dts.append(min(dt, max_gap) if dt > 0 else 0.0)
    total = sum(dts)
    if total <= 0:
        return len(rows) // 2
    acc, half = 0.0, total / 2
    for i in range(1, len(rows)):
        acc += dts[i]
        if acc >= half:
            return max(1, i)
    return len(rows) // 2


def _decoupling_calc(recs: list, skip_warmup_min: float = 5.0) -> dict:
    """Pure calculation so it can be unit-tested. recs: dicts with timestamp/heart_rate/speed."""
    moving = [r for r in recs
              if (r.get("speed") or 0) > 0.5 and (r.get("heart_rate") or 0) > 60]
    if len(moving) < 120:
        return {"error": "not enough moving data for decoupling analysis"}
    t0 = moving[0]["timestamp"]
    work = [r for r in moving
            if (r["timestamp"] - t0).total_seconds() >= skip_warmup_min * 60]
    if len(work) < 120:
        work = moving
    mid = _moving_time_split(work)
    h1, h2 = work[:mid], work[mid:]

    def _avg(rows, key):
        vals = [r[key] for r in rows if r.get(key)]
        return sum(vals) / len(vals) if vals else 0

    s1, hr1 = _avg(h1, "speed"), _avg(h1, "heart_rate")
    s2, hr2 = _avg(h2, "speed"), _avg(h2, "heart_rate")
    if not (s1 and s2 and hr1 and hr2):
        return {"error": "missing speed/HR data"}
    ef1, ef2 = s1 / hr1, s2 / hr2
    dec = (ef1 - ef2) / ef1 * 100

    def _pace(mps):
        if not mps:
            return None
        sec = 1000 / mps
        return f"{int(sec // 60)}:{int(sec % 60):02d}/km"

    verdict = ("excellent aerobic durability (<5%)" if dec < 5 else
               "moderate drift (5-8%) — acceptable on hard/hot days" if dec < 8 else
               "high drift (>8%) — fatigue, heat, dehydration, or aerobic base needs work")
    return {
        "decoupling_pct": round(dec, 1),
        "first_half": {"avg_pace": _pace(s1), "avg_hr": round(hr1)},
        "second_half": {"avg_pace": _pace(s2), "avg_hr": round(hr2)},
        "warmup_skipped_min": skip_warmup_min,
        "interpretation": verdict,
    }


def _pacing_calc(recs: list) -> dict:
    """Lap-independent pacing read from FIT records: walk/pause detection, true
    running pace (walks/pauses excluded), first-vs-second-half fade. Pure calculation
    so it can be unit-tested."""
    rows = [r for r in recs if r.get("timestamp") is not None]
    if len(rows) < 120:
        return {"error": "not enough data for pacing analysis"}
    run_cads = sorted(r["cadence"] for r in rows
                      if (r.get("speed") or 0) >= 2.3 and r.get("cadence"))
    cad_thr = run_cads[len(run_cads) // 2] * 0.8 if len(run_cads) >= 60 else None

    def _cls(r):
        sp = r.get("speed") or 0
        if sp <= 0.5:
            return "pause"
        cad = r.get("cadence")
        if cad_thr and cad and cad < cad_thr and sp < 2.6:
            return "walk"
        if not cad_thr and sp < 1.9:
            return "walk"
        return "run"

    t0 = rows[0]["timestamp"]
    state_time = {"run": 0.0, "walk": 0.0, "pause": 0.0}
    run_dist = 0.0
    km_walk = {}
    walk_segs = []
    cur = None  # [state, duration_s]
    prev = rows[0]
    for r in rows[1:]:
        dt = (r["timestamp"] - prev["timestamp"]).total_seconds()
        if dt <= 0:
            prev = r
            continue
        if dt > 10:  # gap in records = watch (auto-)paused
            state_time["pause"] += dt
            prev = r
            continue
        st = _cls(prev)
        state_time[st] += dt
        if st == "run":
            run_dist += (prev.get("speed") or 0) * dt
        elif st == "walk":
            km = int((prev.get("distance") or 0) // 1000)
            km_walk[km] = km_walk.get(km, 0) + dt
        if cur and cur[0] == st:
            cur[1] += dt
        else:
            if cur and cur[0] == "walk" and cur[1] >= 10:
                walk_segs.append(cur[1])
            cur = [st, dt]
        prev = r
    if cur and cur[0] == "walk" and cur[1] >= 10:
        walk_segs.append(cur[1])

    runrows = [r for r in rows if _cls(r) == "run" and r.get("speed")]
    fade = None
    if len(runrows) >= 120:
        mid = _moving_time_split(runrows)
        s1 = sum(r["speed"] for r in runrows[:mid]) / mid
        s2 = sum(r["speed"] for r in runrows[mid:]) / (len(runrows) - mid)
        if s1:
            fade = round((s1 - s2) / s1 * 100, 1)

    def _pace(mps):
        if not mps:
            return None
        sec = 1000 / mps
        return f"{int(sec // 60)}:{int(sec % 60):02d}/km"

    run_t = state_time["run"]
    out = {
        "elapsed_min": round((rows[-1]["timestamp"] - t0).total_seconds() / 60, 1),
        "run_min": round(run_t / 60, 1),
        "walk_min": round(state_time["walk"] / 60, 1),
        "pause_min": round(state_time["pause"] / 60, 1),
        "walk_breaks": len(walk_segs),
        "longest_walk_s": round(max(walk_segs, default=0)),
        "walk_by_km": {f"km{k + 1}": round(v) for k, v in sorted(km_walk.items()) if v >= 5},
        "true_run_pace": _pace(run_dist / run_t if run_t else 0),
        "fade_pct": fade,
    }
    if fade is not None:
        out["fade_note"] = (
            "even pacing" if abs(fade) < 3 else
            f"negative split — second half {abs(fade):.0f}% faster" if fade < 0 else
            "faded — second half slower; check pacing/fuel" if fade < 8 else
            "blew up — went out too fast or under-fuelled")
    return out


def get_activity_pacing(activity_id: str) -> dict:
    """Walk/pause detection + pacing fade from the FIT file: true running pace (walks excluded), walk seconds per km, first-vs-second-half fade."""
    def f():
        return _pacing_calc(_fit_records(activity_id))
    return call(lambda g: lambda: f(), ckey=("pacing", activity_id))


def get_activity_stream(activity_id: str, metrics: str = "heart_rate,speed,cadence",
                        max_points: int = 40) -> dict:
    """Downsampled second-by-second sensor streams from an activity's FIT file. metrics: comma list from heart_rate,speed,cadence,power,altitude,distance. Returns ~max_points averaged buckets."""
    def f():
        recs = _fit_records(activity_id)
        if not recs:
            return {"error": "no record data in FIT file"}
        want = [m.strip() for m in metrics.split(",") if m.strip()]
        t0 = recs[0]["timestamp"]
        n = max(1, -(-len(recs) // min(max(max_points, 1), 40)))  # ceil -> <=40 buckets (slim-safe)
        points = []
        for i in range(0, len(recs), n):
            chunk = recs[i:i + n]
            pt = {"t_s": int((chunk[0]["timestamp"] - t0).total_seconds())}
            for m in want:
                vals = [r[m] for r in chunk if r.get(m) is not None]
                if vals:
                    pt[m] = round(sum(vals) / len(vals), 2)
            points.append(pt)
        return {"activity_id": str(activity_id), "raw_records": len(recs),
                "points": points}
    return call(lambda g: lambda: f(), ckey=(activity_id, metrics, max_points))


def get_aerobic_decoupling(activity_id: str, skip_warmup_min: float = 5.0) -> dict:
    """Aerobic decoupling (Pa:Hr drift) for a steady activity: compares speed/HR efficiency of first vs second half. <5% = strong aerobic base. Use on steady runs/rides, not intervals."""
    def f():
        return _decoupling_calc(_fit_records(activity_id), skip_warmup_min)
    return call(lambda g: lambda: f(), ckey=("decoupling", activity_id, skip_warmup_min))


# ---- FoodLog direct tools (exact date query — no fuzzy search) --------------
def _day_title(d: str) -> str:
    """Row title: 'D[N] | date' when D1_DATE env is set, else the plain date."""
    d1 = os.environ.get("D1_DATE", "")
    if not d1:
        return d
    from datetime import date as _d
    y, m, dd = map(int, d.split("-"))
    y1, m1, dd1 = map(int, d1.split("-"))
    n = (_d(y, m, dd) - _d(y1, m1, dd1)).days + 1
    return f"D{n} | {d}"


def _notion_write(method, path, payload):
    try:
        return _notion(method, path, payload, "2022-06-28")
    except Exception:
        return _notion(method, path, payload, "2025-09-03")


_MEAL_HEADER = ["เวลา", "รายการ", "kcal", "p", "c", "f"]
_LIFT_HEADER = ["ท่า", "นน(kg)", "เซ็ต×ครั้ง", "volume", "e1RM"]


def _replace_table(bid, table_block, header=None):
    """Replace ONLY the LeanLoop-owned table — matched by its header row when `header` is given, so a
    user's own second table on the page is never deleted. Notes/images/callouts always kept.
    table_block=None just removes the matching table (used when clearing all meals/lifts)."""
    try:
        kids = _notion("GET", f"/blocks/{bid}/children?page_size=100", None, "2022-06-28")
    except Exception:
        kids = {"results": []}
    for b in kids.get("results", []):
        if b.get("type") != "table":
            continue
        if header is not None:
            try:
                rr = _notion("GET", f"/blocks/{b['id'].replace('-', '')}/children?page_size=1", None, "2022-06-28")
                fr = (rr.get("results") or [{}])[0]
                cells = ["".join(x.get("plain_text", "") for x in c).strip()
                         for c in (fr.get("table_row", {}).get("cells", []))]
                if cells != header:
                    continue  # not our table — leave it alone
            except Exception:
                continue  # can't verify -> don't delete (safe)
        try:
            _notion("DELETE", f"/blocks/{b['id']}", None, "2022-06-28")
        except Exception:
            pass
    if table_block is not None:
        _notion_write("PATCH", f"/blocks/{bid}/children", {"children": [table_block]})


def _parse_meals(page_id):
    """Read the meal table already on a FoodLog day page → list of [time, item, kcal, p, c, f]."""
    if not page_id:
        return []
    bid = page_id.replace("-", "")
    try:
        kids = _notion("GET", f"/blocks/{bid}/children?page_size=50", None, "2022-06-28")
    except Exception:
        return []
    out = []
    for b in kids.get("results", []):
        if b.get("type") != "table":
            continue
        tid = b["id"].replace("-", "")
        try:
            rows = _notion("GET", f"/blocks/{tid}/children?page_size=100", None, "2022-06-28")
        except Exception:
            return []
        for r in rows.get("results", []):
            if r.get("type") != "table_row":
                continue
            cells = r.get("table_row", {}).get("cells", [])

            def _t(cell):
                return "".join(x.get("plain_text", "") for x in cell).strip()

            v = [_t(c) for c in cells]
            if len(v) < 6 or v[0] == "เวลา" or v[1] == "รวม":
                continue
            try:
                out.append([v[0], v[1], float(v[2]), float(v[3]), float(v[4]), float(v[5])])
            except Exception:
                pass
        break
    return out


_REC_KEYS = ("sleep_score", "sleep_hrs", "hrv", "rhr", "body_battery_change", "readiness")


def foodlog_get(date: str = "") -> dict:
    """Read the Notion FoodLog row for a date (exact date match). Returns page_id and all fields. date=YYYY-MM-DD, default today."""
    d = day(date)
    try:
        row = _find_row(d)
    except Exception as e:
        return {"error": str(e)}
    if not row:
        return {"date": d, "status": "no-row", "day": _day_title(d)}
    p = row.get("properties", {})

    def num(k):
        return (p.get(k) or {}).get("number")

    def txt(k):
        rt = (p.get(k) or {}).get("rich_text") or []
        return "".join(t.get("plain_text", "") for t in rt) or None

    return {"date": d, "day": _day_title(d), "page_id": row["id"],
            "kcal": num("kcal"), "p": num("p"), "c": num("c"), "f": num("f"),
            "exercise_type": txt("exercise_type"), "exercise_burn": num("exercise_burn"),
            "tdee_est": num("tdee_est"), "deficit_actual": _deficit_val(p),
            "recovery": ({k: num(k) for k in _REC_KEYS if num(k) is not None} or None),
            "meals": _parse_meals(row["id"])}


def foodlog_get_range(start_date: str, end_date: str = "") -> list | dict:
    """Read FoodLog rows for a date range (inclusive, YYYY-MM-DD) in ONE call — compact rows sorted by date. Use this for weekly summaries instead of calling foodlog_get per day."""
    s, e = day(start_date), day(end_date)
    _today = _today_local().isoformat()
    _ck = ("foodlog", s, e)
    _cached = _cget(_ck)
    if _cached is not None:
        _bump("foodlog_read", _cached)[2] += 1
        return _cached
    flt = {"filter": {"and": [
        {"property": "date", "date": {"on_or_after": s}},
        {"property": "date", "date": {"on_or_before": e}},
    ]}, "page_size": 100}
    try:
        rows = _notion_query_all(FOODLOG_DS, flt.get("filter"))
    except Exception as ex:
        return {"error": str(ex)}
    out = []
    for row in rows:
        p = row.get("properties", {})

        def num(k):
            return (p.get(k) or {}).get("number")

        def txt(k):
            rt = (p.get(k) or {}).get("rich_text") or []
            return "".join(t.get("plain_text", "") for t in rt) or None

        title = (p.get("day") or {}).get("title") or []
        out.append({"page_id": row["id"],
                    "date": ((p.get("date") or {}).get("date") or {}).get("start"),
                    "day": "".join(t.get("plain_text", "") for t in title) or None,
                    "kcal": num("kcal"), "p": num("p"), "c": num("c"), "f": num("f"),
                    "exercise_type": txt("exercise_type"), "exercise_burn": num("exercise_burn"),
                    "tdee_est": num("tdee_est"), "deficit_actual": _deficit_val(p),
                    "sync": (((p.get("sync") or {}).get("select")) or {}).get("name"),
                    "recovery": ({k: num(k) for k in _REC_KEYS if num(k) is not None} or None)})
    out.sort(key=lambda x: x["date"] or "")
    _cput(_ck, out, 21600 if e < _today else 30)
    _bump("foodlog_read", out)
    return out


@mcp.tool()
def foodlog_upsert(date: str = "", kcal: float | None = None, p: float | None = None,
                   c: float | None = None, f: float | None = None,
                   exercise_type: str | None = None,
                   exercise_burn: float | None = None,
                   tdee_est: float | None = None,
                   meals: list | str | None = None,
                   meal_note: str | None = None) -> dict:
    """Create or update the Notion FoodLog row for a date (one row per day, exact match — never creates duplicates). Only provided fields are written; omitted fields stay unchanged.
    meals: the FULL day's meals so far — either a native array or a JSON string, each element ["HH:MM","dish",kcal,p,c,f] (both accepted). The server rebuilds a clean meal table on the day page and recomputes kcal/p/c/f from it, so send the whole running list on every add/edit/remove.
    date=YYYY-MM-DD, default today."""
    d = day(date)
    parsed_meals = None
    if meals is not None:
        try:
            import json as _j
            data = _j.loads(meals) if isinstance(meals, str) else meals
            parsed_meals = [[str(m[0]), str(m[1]), float(m[2]), float(m[3]),
                             float(m[4]), float(m[5])] for m in data]

            # keep the day's table in clock order: standard calendar day,
            # 00:00 -> 23:59 (01:00 = early morning, sorts first; 23:00 last).
            # Unparseable times sort last.
            def _mealkey(m):
                t = str(m[0])
                try:
                    return int(t[:2]) * 60 + int(t[3:5])
                except Exception:
                    return 99999
            parsed_meals.sort(key=_mealkey)
            # totals computed from the meal table = single source of truth
            kcal = round(sum(m[2] for m in parsed_meals))
            p = round(sum(m[3] for m in parsed_meals), 1)
            c = round(sum(m[4] for m in parsed_meals), 1)
            f = round(sum(m[5] for m in parsed_meals), 1)
        except Exception:
            parsed_meals = None
    props = {}
    for k, v in (("kcal", kcal), ("p", p), ("c", c), ("f", f),
                 ("exercise_burn", exercise_burn), ("tdee_est", tdee_est)):
        if v is not None:
            props[k] = {"number": v}
    if exercise_type is not None:
        props["exercise_type"] = {"rich_text": [{"text": {"content": exercise_type[:200]}}]}
    if not props and not meal_note and meals is None:
        return {"error": "no fields provided"}
    for _k in [k for k in list(_call_cache) if isinstance(k, tuple) and k and k[0] == "foodlog"]:
        _call_cache.pop(_k, None)

    note_err = [None]

    def _cell(v):
        return [{"type": "text", "text": {"content": str(v)[:200]}}]

    def _row(vals, bold=False):
        cells = [_cell(v) for v in vals]
        if bold:
            for c_ in cells:
                c_[0]["annotations"] = {"bold": True}
        return {"type": "table_row", "table_row": {"cells": cells}}

    def _note(pid, wrote):
        if not pid:
            return wrote
        bid = pid.replace("-", "")
        if meals and parsed_meals is None:
            note_err[0] = "meals parse failed (expect JSON [[time,item,kcal,p,c,f],...])"
        if parsed_meals is not None:
            try:
                if parsed_meals:
                    rows = [[m[0], m[1], round(m[2]), round(m[3], 1), round(m[4], 1), round(m[5], 1)]
                            for m in parsed_meals]
                    tot = [round(sum(r[i] for r in rows), 1) for i in (2, 3, 4, 5)]
                    tot = [int(x) if x == int(x) else x for x in tot]
                    trows = [_row(["เวลา", "รายการ", "kcal", "p", "c", "f"], bold=True)]
                    trows += [_row([m[0], m[1], int(m[2]) if m[2] == int(m[2]) else m[2],
                                    int(m[3]) if m[3] == int(m[3]) else m[3],
                                    int(m[4]) if m[4] == int(m[4]) else m[4],
                                    int(m[5]) if m[5] == int(m[5]) else m[5]]) for m in rows]
                    trows.append(_row(["", "รวม", tot[0], tot[1], tot[2], tot[3]], bold=True))
                    _replace_table(bid, {"object": "block", "type": "table",
                                         "table": {"table_width": 6, "has_column_header": True,
                                                   "has_row_header": False, "children": trows}}, header=_MEAL_HEADER)
                else:  # empty list = all meals removed -> remove the meal table only
                    _replace_table(bid, None, header=_MEAL_HEADER)
                wrote.append("meals")
            except Exception as e:
                note_err[0] = str(e)
        elif meal_note:
            try:
                _notion_write("PATCH", f"/blocks/{bid}/children",
                              {"children": [{"object": "block", "type": "bulleted_list_item",
                                             "bulleted_list_item": {"rich_text": [
                                                 {"text": {"content": meal_note[:300]}}]}}]})
                wrote.append("meal_note")
            except Exception as e:
                note_err[0] = str(e)
        return wrote
    if any(k in props for k in ("kcal", "p", "c", "f")) and "tdee_est" not in props:
        props["sync"] = {"select": {"name": "pending"}}

    try:
        row = _find_row(d)
        if row:
            if props:
                _notion_write("PATCH", "/pages/" + row["id"], {"properties": props})
            res = {"date": d, "status": "updated", "page_id": row["id"],
                   "wrote": _note(row["id"], list(props))}
            if note_err[0]:
                res["meal_note_error"] = note_err[0]
            return res
        title = _day_title(d)
        full_props = {"day": {"title": [{"text": {"content": title}}]},
                      "date": {"date": {"start": d}}, **props}
        try:
            r = _notion("POST", "/pages",
                        {"parent": {"database_id": FOODLOG_DS},
                         "properties": full_props}, "2022-06-28")
        except Exception:
            r = _notion("POST", "/pages",
                        {"parent": {"type": "data_source_id",
                                    "data_source_id": FOODLOG_DS},
                         "properties": full_props}, "2025-09-03")
        res = {"date": d, "status": "created", "page_id": r.get("id"), "day": title,
               "wrote": _note(r.get("id"), list(props))}
        if note_err[0]:
            res["meal_note_error"] = note_err[0]
        return res
    except Exception as e:
        return {"error": str(e)}


def _parse_lift_table(page_id):
    """Read the lift table already on a TrainingLog page -> [[exercise, load, sets, reps], ...]."""
    if not page_id:
        return []
    bid = page_id.replace("-", "")
    try:
        kids = _notion("GET", f"/blocks/{bid}/children?page_size=50", None, "2022-06-28")
    except Exception:
        return []
    out = []
    for b in kids.get("results", []):
        if b.get("type") != "table":
            continue
        tid = b["id"].replace("-", "")
        try:
            rows = _notion("GET", f"/blocks/{tid}/children?page_size=100", None, "2022-06-28")
        except Exception:
            return []
        for r in rows.get("results", []):
            if r.get("type") != "table_row":
                continue
            v = ["".join(x.get("plain_text", "") for x in c).strip() for c in r.get("table_row", {}).get("cells", [])]
            if len(v) < 4 or v[0] in ("ท่า", "") or v[1] == "รวม volume":
                continue
            sr = v[2].split("×") if "×" in v[2] else [v[2], ""]
            def _n(x):
                try:
                    return float(x)
                except Exception:
                    return None
            out.append([v[0], _n(v[1]), _n(sr[0]), _n(sr[1] if len(sr) > 1 else "")])
        break
    return out


@mcp.tool()
def weightlog_upsert(date: str = "", session: str = "", lifts: list | str | None = None, page_id: str = "") -> dict:
    """Log a weight-training session as a clean lift table on its TrainingLog day page.
    Creates/updates ONE TrainingLog row (type=weights) for the date + session name, then rebuilds
    the lift table from `lifts` = array of ["exercise", load_kg, sets, reps] (a JSON string is also
    accepted). The server computes volume (load*sets*reps) and estimated 1RM per lift plus total
    volume, so send the WHOLE session's lifts on every add/edit. date=YYYY-MM-DD, default today."""
    d = day(date)
    sess = (session or "Weights").strip()
    def _lift(l):
        l = list(l) + [None] * (4 - len(l))
        def _n(x):
            return None if x in (None, "") else float(x)
        return [str(l[0]), _n(l[1]), _n(l[2]), _n(l[3])]  # load/sets/reps optional = lazy mode
    lifts_given = lifts is not None
    try:
        import json as _j
        data = _j.loads(lifts) if isinstance(lifts, str) else (lifts or [])
        parsed = [_lift(l) for l in data]
    except Exception:
        return {"error": "lifts must be [[exercise, load_kg?, sets?, reps?], ...] (numbers optional = lazy)"}
    if not parsed and not session:
        return {"error": "give a session name and/or lifts"}
    if not TRAINING_DS:
        return {"error": "NOTION_TRAININGLOG_DS not set"}

    row_id = page_id or None  # explicit page_id (from traininglog_read) = precise edit, no guessing
    if not row_id:
        flt = {"filter": {"and": [{"property": "date", "date": {"equals": d}},
                                 {"property": "type", "select": {"equals": "weights"}}]}, "page_size": 50}
        try:
            try:
                r = _notion("POST", f"/databases/{TRAINING_DS}/query", flt, "2022-06-28")
            except Exception:
                r = _notion("POST", f"/data_sources/{TRAINING_DS}/query", flt, "2025-09-03")
            for row in r.get("results", []):
                ti = "".join(x.get("plain_text", "") for x in ((row.get("properties", {}).get("session") or {}).get("title") or []))
                if ti.strip().lower() == sess.lower():  # EXACT match — never clobber a different session
                    row_id = row["id"]
                    break
        except Exception as e:
            return {"error": f"query failed: {e}"}

    total_vol = round(sum(l[1] * l[2] * l[3] for l in parsed if l[1] is not None and l[2] and l[3]))
    props = {"session": {"title": [{"text": {"content": sess[:200]}}]},
             "date": {"date": {"start": d}}, "type": {"select": {"name": "weights"}}}
    if not row_id:
        try:
            try:
                cr = _notion("POST", "/pages", {"parent": {"database_id": TRAINING_DS}, "properties": props}, "2022-06-28")
            except Exception:
                cr = _notion("POST", "/pages", {"parent": {"type": "data_source_id", "data_source_id": TRAINING_DS}, "properties": props}, "2025-09-03")
            row_id = cr.get("id")
        except Exception as e:
            return {"error": f"create failed: {e}"}

    def _cell(v, bold=False):
        c = [{"type": "text", "text": {"content": str(v)[:200]}}]
        if bold:
            c[0]["annotations"] = {"bold": True}
        return c
    def _rowb(vals, bold=False):
        return {"type": "table_row", "table_row": {"cells": [_cell(v, bold) for v in vals]}}
    bid = (row_id or "").replace("-", "")
    if not lifts_given:  # lifts=None -> leave the existing lift table untouched
        return {"date": d, "session": sess, "page_id": row_id, "status": "session-row (lifts unchanged)"}
    if not parsed:  # lifts=[] -> explicitly clear the lift table (mirror meals=[])
        try:
            _replace_table(bid, None, header=_LIFT_HEADER)
        except Exception:
            pass
        return {"date": d, "session": sess, "page_id": row_id, "status": "lifts-cleared"}
    try:
        trows = [_rowb(["ท่า", "นน(kg)", "เซ็ต×ครั้ง", "volume", "e1RM"], bold=True)]
        for ex, load, sets, reps in parsed:
            if load is not None and sets and reps:
                e1 = round(load * (1 + reps / 30.0), 1)
                e1 = int(e1) if e1 == int(e1) else e1
                ld = int(load) if load == int(load) else load
                trows.append(_rowb([ex, ld, f"{int(sets)}×{int(reps)}", round(load * sets * reps), e1]))
            else:  # lazy row — logged without numbers
                trows.append(_rowb([ex, "-", "-", "-", "-"]))
        trows.append(_rowb(["", "รวม volume", "", total_vol, ""], bold=True))
        _replace_table(bid, {"object": "block", "type": "table",
                             "table": {"table_width": 5, "has_column_header": True,
                                       "has_row_header": False, "children": trows}}, header=_LIFT_HEADER)
    except Exception as e:
        return {"date": d, "session": sess, "page_id": row_id, "status": "row-ok-table-failed",
                "total_volume": total_vol, "error": str(e)}
    return {"date": d, "session": sess, "page_id": row_id, "status": "saved",
            "lifts": len(parsed), "total_volume": total_vol}



@mcp.tool()
def traininglog_read(date: str = "", end_date: str = "", type: str = "") -> list | dict:
    """Read TrainingLog rows (what was actually DONE) — the read side missing until now. One date (default today)
    or a range (end_date, inclusive). Optional `type` filter (run/tempo/threshold/interval/recovery-run/weights/
    muay-thai/...). Each row returns session/type/distance_km/duration/pace/avg_hr/max_hr/zone4_5_pct/training_effect/
    kcal_burn/coach_notes/body_signals, and for WEIGHT sessions the lift table on its page (`lifts`: [exercise,load,
    sets,reps]) + `page_id`. Read this BEFORE editing a weight session (so no lift is lost — resend the full list or
    pass page_id), and for strength progression, weekly volume-per-muscle, plan adherence, and any full training review."""
    d = day(date)
    e = day(end_date) if end_date else d
    if not TRAINING_DS:
        return {"error": "NOTION_TRAININGLOG_DS not set"}
    flt = {"filter": {"and": [{"property": "date", "date": {"on_or_after": d}},
                             {"property": "date", "date": {"on_or_before": e}}]}, "page_size": 100}
    if type:
        flt["filter"]["and"].append({"property": "type", "select": {"equals": type}})
    try:
        rows = _notion_query_all(TRAINING_DS, flt.get("filter"))
    except Exception as ex:
        return {"error": str(ex)}
    out = []
    for row in rows:
        p = row.get("properties", {})

        def num(k):
            return (p.get(k) or {}).get("number")

        def txt(k):
            rt = (p.get(k) or {}).get("rich_text") or []
            return "".join(t.get("plain_text", "") for t in rt) or None

        def sel(k):
            return (((p.get(k) or {}).get("select")) or {}).get("name")

        ttl = (p.get("session") or {}).get("title") or []
        rec = {"page_id": row["id"],
               "date": ((p.get("date") or {}).get("date") or {}).get("start"),
               "session": "".join(t.get("plain_text", "") for t in ttl) or None,
               "type": sel("type"), "distance_km": num("distance_km"), "duration": txt("duration"),
               "pace": txt("pace"), "avg_hr": num("avg_hr"), "max_hr": num("max_hr"),
               "zone4_5_pct": num("zone4_5_pct"), "training_effect_aerobic": num("training_effect_aerobic"),
               "kcal_burn_adjusted": num("kcal_burn_adjusted"),
               "coach_notes": txt("coach_notes"), "body_signals": txt("body_signals")}
        if sel("type") == "weights":
            rec["lifts"] = _parse_lift_table(row["id"])
        out.append(rec)
    out.sort(key=lambda x: (x["date"] or "", x["session"] or ""))
    return out


_WELLNESS = {"hrv": get_hrv, "stress": get_stress, "body_battery": get_body_battery,
             "heart_rate": get_heart_rate, "spo2": get_spo2, "respiration": get_respiration,
             "intensity_minutes": get_intensity_minutes, "hydration": get_hydration,
             "blood_pressure": get_blood_pressure, "body_composition": get_body_composition,
             "training_readiness": get_training_readiness, "training_status": get_training_status}

_FITNESS = {"vo2max": get_vo2max, "fitness_age": get_fitness_age,
            "endurance_score": get_endurance_score, "hill_score": get_hill_score}
_FITNESS_NODATE = {"race_predictions": get_race_predictions,
                   "lactate_threshold": get_lactate_threshold,
                   "personal_records": get_personal_records}


@mcp.tool()
def get_wellness(metric: str, date: str = "", full: bool = False) -> dict | list:
    """One daily health metric. metric = sleep (last night: score/stages/HRV/RHR/body battery; full=true adds raw series) | hrv | stress | body_battery | heart_rate | spo2 | respiration | intensity_minutes | hydration | blood_pressure | body_composition | training_readiness | training_status. date=YYYY-MM-DD, default today."""
    m = metric.strip().lower()
    if m == "sleep":
        return get_sleep(date, full)
    fn = _WELLNESS.get(m)
    if not fn:
        return {"error": f"unknown metric '{metric}'", "valid": ["sleep"] + sorted(_WELLNESS)}
    return fn(date)


@mcp.tool()
def get_fitness(metric: str, date: str = "") -> dict | list:
    """One long-term fitness metric. metric = vo2max | race_predictions (5K..marathon) | fitness_age | endurance_score | hill_score | lactate_threshold | personal_records. date optional (YYYY-MM-DD) where applicable."""
    m = metric.strip().lower()
    if m in _FITNESS_NODATE:
        return _FITNESS_NODATE[m]()
    fn = _FITNESS.get(m)
    if not fn:
        return {"error": f"unknown metric '{metric}'",
                "valid": sorted(list(_FITNESS) + list(_FITNESS_NODATE))}
    return fn(date)


@mcp.tool()
def get_activities(start_date: str = "", end_date: str = "", limit: int = 10,
                   activity_type: str = "") -> list | dict:
    """Activities (runs, rides, workouts...). No args = latest `limit` with key fields. With start_date (+ optional end_date, activity_type) = every activity in that date range."""
    if start_date:
        return get_activities_range(start_date, end_date, activity_type)
    return _activities_recent(limit)


@mcp.tool()
def get_activity(activity_id: str, view: str = "summary",
                 metrics: str = "heart_rate,speed,cadence", max_points: int = 60,
                 skip_warmup_min: float = 5.0) -> dict | list:
    """One activity, one view. view = summary (cadence/power/dynamics/weather) | splits (per-km pace/HR) | hr_zones (time per HR zone) | stream (downsampled FIT sensor series; metrics/max_points apply) | decoupling (Pa:Hr aerobic drift, steady sessions only; skip_warmup_min applies) | pacing (walk/pause detection from FIT: true running pace excluding walks, walk seconds per km, first-vs-second-half fade — use when overall pace may be misleading). Get activity_id from get_activities."""
    v = view.strip().lower()
    if v == "summary":
        return get_activity_details(activity_id)
    if v == "splits":
        return get_activity_splits(activity_id)
    if v == "hr_zones":
        return get_activity_hr_zones(activity_id)
    if v == "stream":
        return get_activity_stream(activity_id, metrics, max_points)
    if v == "decoupling":
        return get_aerobic_decoupling(activity_id, skip_warmup_min)
    if v == "pacing":
        return get_activity_pacing(activity_id)
    return {"error": f"unknown view '{view}'", "valid": ["summary", "splits", "hr_zones", "stream", "decoupling", "pacing"]}


@mcp.tool()
def foodlog_read(date: str = "", end_date: str = "") -> list | dict:
    """Read the Notion FoodLog. One day (default today) → a single object that ALSO includes `meals` (the per-meal table on that day's page: [time,item,kcal,p,c,f]) — read this before editing meals so nothing is lost across chats. A range (via end_date) → a list of compact daily rows sorted by date. Empty = nothing logged."""
    if not end_date or end_date == date:
        return foodlog_get(date)
    return foodlog_get_range(date, end_date)


def _weights_kg(wi):
    """Tolerant (date, kg) extractor from get_weigh_ins output."""
    pts = []
    try:
        for s in (wi or {}).get("dailyWeightSummaries", []):
            d = s.get("summaryDate")
            w = None
            for m in (s.get("allWeightMetrics") or []):
                if m.get("weight"):
                    w = m["weight"] / 1000.0
                    break
            if w is None and (s.get("latestWeight") or {}).get("weight"):
                w = s["latestWeight"]["weight"] / 1000.0
            if d and w:
                pts.append((d, round(w, 2)))
    except Exception:
        pass
    return sorted(pts)


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


@mcp.tool()
def weekly_report(days: int = 7) -> dict:
    """Pre-digested weekly review in ONE call: food averages **plus per-day rows (`food.by_day`)**, logging coverage + cron watchdog, activity list + totals, 14-day weight trend, VO2max. Coach: narrate averages to frame, then use by_day to name the specific days that missed target — do NOT re-fetch the raw data behind this."""
    from datetime import date as _d, timedelta as _td
    today = _today_local()
    start = (today - _td(days=days - 1)).isoformat()
    end = today.isoformat()
    out = {"window": f"{start}..{end}"}
    rows = foodlog_get_range(start, end)
    if isinstance(rows, dict):
        out["food_error"] = rows.get("error")
        rows = []
    logged = [r for r in rows if r.get("kcal") is not None]
    out["food"] = {
        "days_logged": len(logged), "days_in_window": days,
        "avg_kcal": _avg([r.get("kcal") for r in logged]),
        "avg_p": _avg([r.get("p") for r in logged]),
        "avg_c": _avg([r.get("c") for r in logged]),
        "avg_f": _avg([r.get("f") for r in logged]),
        "avg_deficit": _avg([r.get("deficit_actual") for r in logged]),
        "cron_missing_tdee": sum(1 for r in logged
                                 if r.get("tdee_est") is None and r.get("date") != end),
    }
    # per-day breakdown so the coach can name the specific days that missed target
    # (granularity > averages) — no extra fetch needed
    out["food"]["by_day"] = [{"date": r.get("date"), "kcal": r.get("kcal"),
                              "p": r.get("p"), "c": r.get("c"), "f": r.get("f"),
                              "deficit": r.get("deficit_actual"), "sync": r.get("sync")}
                             for r in rows]

    def f(g):
        res = {}
        try:
            acts = _act_slim(g.get_activities_by_date(start, end))
            res["activities"] = [{"name": a.get("activityName"),
                                  "start": a.get("startTimeLocal"),
                                  "type": ((a.get("activityType") or {}).get("typeKey")),
                                  "km": round((a.get("distance") or 0) / 1000, 2),
                                  "min": round((a.get("duration") or 0) / 60),
                                  "kcal": a.get("calories"), "avgHR": a.get("averageHR"),
                                  "TE_aer": a.get("aerobicTrainingEffect")} for a in acts]
            res["activity_totals"] = {"sessions": len(acts),
                                      "km": round(sum((a.get("distance") or 0) for a in acts) / 1000, 1),
                                      "kcal": round(sum((a.get("calories") or 0) for a in acts))}
        except Exception as e:
            res["activities_error"] = str(e)
        try:
            w14 = (today - _td(days=13)).isoformat()
            pts = _weights_kg(g.get_weigh_ins(w14, end))
            half = len(pts) // 2 if len(pts) >= 2 else 0
            res["weight"] = {"points": len(pts),
                             "first_half_avg": _avg([p[1] for p in pts[:half]]) if half else None,
                             "last_half_avg": _avg([p[1] for p in pts[half:]]) if half else None,
                             "latest": pts[-1][1] if pts else None}
        except Exception as e:
            res["weight_error"] = str(e)
        try:
            res["vo2max"] = g.get_max_metrics(end)
        except Exception as e:
            res["vo2max_error"] = str(e)
        return res

    r = call(lambda g: lambda: f(g))
    out.update(r if isinstance(r, dict) else {"garmin_error": r})
    return out


@mcp.tool()
def analyze_activity(activity_id: str = "") -> dict:
    """Full post-workout analysis bundle in ONE call: session summary, per-lap splits (pace/HR/maxHR/cadence), HR zones, aerobic decoupling (steady sessions >=25 min), `pacing` (runs >=15 min: walk/pause detection, true running pace excluding walks, walk seconds per km, first-vs-second-half fade — the overall pace can lie; this shows why), the previous SAME-type session PLUS `same_type_history` (last 8 same-type sessions, compact pace@HR — for a real trend, not just vs the last one), the pre-workout fuel (what was eaten in the 4h before the start — timing-aware, flags fasted), the last-3-day training load (cumulative fatigue), day-before carbs, and **`sleep_before`** (the night before the run: score/HRV/RHR/hours). `pre_workout_fuel` now includes full macros (p/c/f) and hours-before the last pre-run meal. Default = latest activity. Coach: compare pace at equal HR vs previous, max 3 ranked causes — do NOT re-fetch the raw data behind this."""
    from datetime import date as _d, timedelta as _td

    def f(g):
        res = {}
        if activity_id:
            meta = g.get_activity(activity_id) or {}
            aid = activity_id
        else:
            latest = (g.get_activities(0, 1) or [{}])[0]
            aid = str(latest.get("activityId", ""))
            meta = latest
        if not aid:
            return {"error": "no activity found"}
        tkey = ((meta.get("activityType") or {}).get("typeKey")) or ""
        res["session"] = {k: meta.get(k) for k in _ACT_KEEP if meta.get(k) is not None}
        res["session"]["typeKey"] = tkey
        start_local = str(meta.get("startTimeLocal") or "")[:10]
        try:
            laps = (g.get_activity_splits(aid) or {}).get("lapDTOs") or []
            res["splits"] = [{"km": round((l.get("distance") or 0) / 1000, 2),
                              "min": round((l.get("duration") or 0) / 60, 2),
                              "pace": _fmt_pace(l.get("movingDuration") or l.get("duration"),
                                                (l.get("distance") or 0) / 1000) or None,
                              "avgHR": l.get("averageHR"), "maxHR": l.get("maxHR"),
                              "cad": l.get("averageRunCadence")} for l in laps]
        except Exception as e:
            res["splits_error"] = str(e)
        try:
            res["hr_zones"] = g.get_activity_hr_in_timezones(aid)
        except Exception as e:
            res["hr_zones_error"] = str(e)
        recs = None
        try:
            if (meta.get("duration") or 0) >= 900:
                recs = _fit_records(aid)
        except Exception as e:
            res["fit_error"] = str(e)
        try:
            if (meta.get("duration") or 0) < 1500:
                res["decoupling"] = "skipped (<25 min)"
            elif recs:
                res["decoupling"] = _decoupling_calc(recs)
        except Exception as e:
            res["decoupling_error"] = str(e)
        try:
            if recs and ("run" in tkey or "walk" in tkey or "hik" in tkey):
                res["pacing"] = _pacing_calc(recs)
        except Exception as e:
            res["pacing_error"] = str(e)
        try:
            if start_local and tkey:
                back = (_d.fromisoformat(start_local) - _td(days=60)).isoformat()
                prev = [a for a in (g.get_activities_by_date(back, start_local, tkey) or [])
                        if str(a.get("activityId")) != str(aid)
                        and str(a.get("startTimeLocal", "")) < str(meta.get("startTimeLocal", ""))]
                prev_sorted = sorted(prev, key=lambda a: str(a.get("startTimeLocal", "")))
                if prev_sorted:
                    p = prev_sorted[-1]
                    res["previous_same_type"] = {k: p.get(k) for k in _ACT_KEEP if p.get(k) is not None}

                    # trend history: last up to 8 same-type sessions, compact pace@HR —
                    # granularity so the coach sees WHICH days ran well/badly across time,
                    # not just vs the immediately previous session.
                    def _hist(a):
                        dur = a.get("duration") or 0
                        dist = (a.get("distance") or 0) / 1000.0
                        return {"date": str(a.get("startTimeLocal", ""))[:10],
                                "time": str(a.get("startTimeLocal", ""))[11:16],
                                "km": round(dist, 2) if dist else None,
                                "pace": _fmt_pace(dur, dist) if dist else None,
                                "avgHR": a.get("averageHR"), "maxHR": a.get("maxHR"),
                                "TE_aer": a.get("aerobicTrainingEffect"),
                                "cad": a.get("averageRunningCadenceInStepsPerMinute")}
                    res["same_type_history"] = [_hist(a) for a in prev_sorted[-8:]]
                else:
                    res["previous_same_type"] = None
                    res["same_type_history"] = []
        except Exception as e:
            res["previous_error"] = str(e)
        try:
            back3 = (_d.fromisoformat(start_local) - _td(days=3)).isoformat()
            recent = [a for a in (g.get_activities_by_date(back3, start_local) or [])
                      if str(a.get("activityId")) != str(aid)]
            res["recent_load_3d"] = {"sessions": len(recent),
                                     "total_min": round(sum((a.get("duration") or 0) for a in recent) / 60)}
        except Exception as e:
            res["recent_load_error"] = str(e)
        # sleep the night BEFORE this run (Garmin sleep on the run's date = that night) —
        # one of the two biggest levers on how a run goes; always include it.
        try:
            if start_local:
                s = g.get_sleep_data(start_local) or {}
                dto = s.get("dailySleepDTO") or {}
                res["sleep_before"] = {
                    "score": ((dto.get("sleepScores") or {}).get("overall") or {}).get("value"),
                    "hours": round((dto.get("sleepTimeSeconds") or 0) / 3600, 1),
                    "avgOvernightHrv": s.get("avgOvernightHrv"),
                    "hrvStatus": s.get("hrvStatus"),
                    "restingHeartRate": s.get("restingHeartRate")}
        except Exception as e:
            res["sleep_before_error"] = str(e)
        res["_date"] = start_local
        res["_start"] = str(meta.get("startTimeLocal") or "")
        return res

    r = call(lambda g: lambda: f(g))
    if isinstance(r, dict) and r.get("_date"):
        sdate = r.pop("_date", "")
        start_full = r.pop("_start", "")
        try:
            prev_day = (_d.fromisoformat(sdate) - _td(days=1)).isoformat()
            rows = foodlog_get_range(prev_day, prev_day)
            r["day_before_carbs_g"] = rows[0].get("c") if isinstance(rows, list) and rows else None
        except Exception:
            pass
        # timing-aware pre-workout fuel: meals eaten in the 4h before the session start
        try:
            stime = start_full[11:16]
            dayrow = foodlog_get(sdate)
            meals = dayrow.get("meals") or [] if isinstance(dayrow, dict) else []
            if stime:
                start_min = int(stime[:2]) * 60 + int(stime[3:5])
                pre = []
                for m in meals:
                    t = str(m[0])
                    try:
                        mmin = int(t[:2]) * 60 + int(t[3:5])
                    except Exception:
                        continue
                    if 0 <= (start_min - mmin) <= 240:
                        pre.append(m)
                last = max(pre, key=lambda m: str(m[0])) if pre else None
                hrs_before = None
                if last:
                    lmin = int(str(last[0])[:2]) * 60 + int(str(last[0])[3:5])
                    hrs_before = round((start_min - lmin) / 60, 1)
                r["pre_workout_fuel"] = {
                    "window": "4h before start",
                    "kcal": round(sum(m[2] for m in pre)),
                    "carbs_g": round(sum(m[4] for m in pre)),
                    "protein_g": round(sum(m[3] for m in pre)),
                    "fat_g": round(sum(m[5] for m in pre)),
                    "fasted": len(pre) == 0,
                    "last_meal_before": (f"{last[0]} {last[1]}" if last else None),
                    "hours_before_last_meal": hrs_before}
        except Exception:
            pass
    return r


def _body_scans():
    """Body-composition scans with fatMass, sorted oldest->newest: date/fatMass/leanMass/w/source."""
    if not BODYMETRICS_DS:
        return []
    try:
        rows = _notion_query_all(BODYMETRICS_DS)
    except Exception:
        return []
    out = []
    for row in rows:
        p = row.get("properties", {})

        def num(k):
            return (p.get(k) or {}).get("number")

        dt = ((p.get("date") or {}).get("date") or {}).get("start")
        src = (((p.get("source") or {}).get("select")) or {}).get("name")
        cond = (((p.get("condition") or {}).get("select")) or {}).get("name")
        fm = num("fatMass")
        if dt and fm is not None:
            out.append({"date": dt, "fatMass": fm, "leanMass": num("leanMass"),
                        "w": num("w"), "source": src, "condition": cond,
                        "visceral": num("visceral"), "smm": num("smm"), "score": num("score")})
    out.sort(key=lambda x: x["date"])
    return out


@mcp.tool()
def calibrate_report(days: int = 14) -> dict:
    """Everything the 'calibrate' routine needs in ONE call: logging coverage, cumulative deficit, weigh-in trend, expected vs actual weight change, and the estimation bias (kcal/day). Coach: check coverage_ok, announce the bias, write it to the CALIBRATION line in Config."""
    from datetime import date as _d, timedelta as _td

    def _cum_deficit(s, e):
        rows = foodlog_get_range(s, e)
        if isinstance(rows, dict):
            return None, None, None
        logged = [r for r in rows if r.get("kcal") is not None]
        defs = [r.get("deficit_actual") for r in rows if r.get("deficit_actual") is not None]
        return round(sum(defs)), len(logged), rows

    # --- Preferred: InBody/body-scan fat-mass calibration (same source, latest pair) ---
    scans = _body_scans()

    def _clean(s):
        # untagged (old scans) or morning-fasted = trustworthy for a trend line
        return s.get("condition") in (None, "", "morning-fasted")

    if len(scans) >= 2:
        # prefer the latest CLEAN scan, paired with the latest prior clean same-source scan
        pool = [s for s in scans if _clean(s)]
        latest = pool[-1] if len(pool) >= 2 else scans[-1]
        prior = next((s for s in reversed([x for x in (pool if len(pool) >= 2 else scans)[:-1]
                                           if x["date"] < latest["date"]])
                      if s["source"] == latest["source"]), None)
        if prior:
            s0, s1 = prior["date"], latest["date"]
            span = max(1, (_d.fromisoformat(s1) - _d.fromisoformat(s0)).days)
            cum, nlog, _ = _cum_deficit(s0, s1)
            if cum is not None:
                need = max(1, round(span * 0.8))
                pred_fat = round(-cum / 7700, 2)
                actual_fat = round(latest["fatMass"] - prior["fatMass"], 2)
                lean = (round(latest["leanMass"] - prior["leanMass"], 2)
                        if latest.get("leanMass") is not None and prior.get("leanMass") is not None else None)
                _both_clean = _clean(latest) and _clean(prior)
                out = {"method": f"body-composition ({latest['source']}) fat-mass — most reliable",
                       "conditions": [prior.get("condition"), latest.get("condition")],
                       "condition_note": ("both morning-fasted/clean — trust this" if _both_clean
                                          else "scans taken under different/unknown conditions — treat bias as approximate; standardize to morning-fasted"),
                       "visceral_change": (round(latest["visceral"] - prior["visceral"], 1)
                                           if latest.get("visceral") is not None and prior.get("visceral") is not None else None),
                       "window": f"{s0}..{s1}", "span_days": span,
                       "days_logged": nlog, "days_required": need,
                       "coverage_ok": nlog >= need,
                       "cumulative_deficit_kcal": cum,
                       "predicted_fat_loss_kg": pred_fat,
                       "actual_fat_loss_kg": actual_fat,
                       "lean_mass_change_kg": lean,
                       "bias_kcal_per_day": round((actual_fat - pred_fat) * 7700 / span),
                       "bias_meaning": "positive = real intake ~that many kcal/day HIGHER than logged (or TDEE lower); add to future estimates. Near 0 = logging accurate.",
                       "muscle_note": ("lean mass preserved/gained — good" if (lean is None or lean >= -0.3)
                                       else "lean mass dropping — deficit may be too aggressive; eat more / more protein")}
                return out

    # --- Fallback: scale weigh-ins over the last `days` (noisier: water/glycogen) ---
    today = _today_local()
    start = (today - _td(days=days - 1)).isoformat()
    end = today.isoformat()
    cum, nlog, rows = _cum_deficit(start, end)
    if cum is None:
        return {"error": "could not read FoodLog"}
    out = {"method": "scale weigh-ins — approximate (weight includes water/glycogen; use an InBody scan for a reliable read)",
           "window": f"{start}..{end}",
           "days_logged": nlog, "days_required": max(1, round(days * 0.8)),
           "coverage_ok": nlog >= round(days * 0.8),
           "cumulative_deficit_kcal": cum,
           "expected_weight_change_kg": round(-cum / 7700, 2)}

    def f(g):
        return {"points": _weights_kg(g.get_weigh_ins(start, end))}

    r = call(lambda g: lambda: f(g))
    pts = r.get("points", []) if isinstance(r, dict) else []
    half = len(pts) // 2 if len(pts) >= 2 else 0
    if half:
        first, last = _avg([p[1] for p in pts[:half]]), _avg([p[1] for p in pts[half:]])
        actual = round(last - first, 2)
        out["weight"] = {"points": len(pts), "first_half_avg": first,
                         "last_half_avg": last, "actual_change_kg": actual}
        out["bias_kcal_per_day"] = round((actual - out["expected_weight_change_kg"]) * 7700 / days)
        out["bias_meaning"] = "positive = real intake ~that many kcal/day HIGHER than logged; add to future estimates. NOTE: scale is noisy — confirm with an InBody scan before trusting a large bias."
    else:
        out["weight"] = {"points": len(pts), "note": "not enough weigh-ins for a trend"}
    return out


@mcp.tool()
def get_config() -> str:
    """The user's Config page (profile, kcal/macro targets, carb tiers, calibration, common labels, training phase) as plain text — served fast from this server with a 10-min cache. Use this instead of fetching Config through the Notion connector."""
    pid = os.environ.get("CONFIG_PAGE_ID", "")
    if not pid:
        return "CONFIG_PAGE_ID is not set on this server — fetch the Config page via the Notion connector instead."
    c = _cget(("config",))
    if c is not None:
        _bump("get_config", c)[2] += 1
        return c
    try:
        r = _notion("GET", f"/blocks/{pid}/children?page_size=100", None, "2022-06-28")
        lines = []
        for b in r.get("results", []):
            t = b.get("type", "")
            rt = (b.get(t) or {}).get("rich_text") or []
            txt = "".join(x.get("plain_text", "") for x in rt)
            if txt:
                lines.append(txt)
        out = "\n".join(lines) or "(Config page is empty)"
    except Exception as e:
        return f"config fetch failed: {e}"
    _cput(("config",), out, 600)
    _bump("get_config", out)
    return out


@mcp.tool()
def foodlib_find(query: str) -> list | dict:
    """Search the user's FoodLib by dish name (contains match, max 10). Returns stored serving/kcal/macros to reuse for repeated dishes — much faster than searching via the Notion connector. Empty list = not in the library."""
    ds = os.environ.get("NOTION_FOODLIB_DS", "")
    if not ds:
        return {"error": "NOTION_FOODLIB_DS is not set on this server — search FoodLib via the Notion connector instead."}
    q = query.strip()
    ck = ("foodlib", q.lower())
    c = _cget(ck)
    if c is not None:
        _bump("foodlib_find", c)[2] += 1
        return c
    def _q(term):
        flt = {"filter": {"property": "name", "title": {"contains": term}}, "page_size": 10}
        try:
            try:
                return _notion("POST", f"/databases/{ds}/query", flt, "2022-06-28")
            except Exception:
                return _notion("POST", f"/data_sources/{ds}/query", flt, "2025-09-03")
        except Exception:
            return None
    r = _q(q)
    if r is None:
        return {"error": "FoodLib query failed"}
    if not r.get("results"):
        # keyword fallback: try the core words (longest first) so
        # "ข้าวมันไก่ ร้านเจ๊ 1 จาน" still finds "ข้าวมันไก่ — เจ๊กี"
        for w in sorted((w for w in q.split() if len(w) >= 3), key=len, reverse=True):
            rr = _q(w)
            if rr and rr.get("results"):
                r = rr
                break
    out = []
    for row in r.get("results", []):
        p = row.get("properties", {})

        def num(k):
            return (p.get(k) or {}).get("number")

        def txt(k):
            rt = (p.get(k) or {}).get("rich_text") or []
            return "".join(t.get("plain_text", "") for t in rt) or None

        title = (p.get("name") or {}).get("title") or []
        out.append({"name": "".join(t.get("plain_text", "") for t in title),
                    "serving": txt("serving"), "kcal": num("kcal"), "p": num("p"),
                    "c": num("c"), "f": num("f"), "notes": txt("notes")})
    _cput(ck, out, 600)
    _bump("foodlib_find", out)
    return out


@mcp.tool()
def exercise_find(query: str) -> list | dict:
    """Search the user's ExerciseLib by exercise/machine name (contains match, max 10). Returns the
    canonical name + muscle_group + default_load + notes, so a loose spoken name ("เครื่องดันอก")
    resolves to a known exercise and its muscle group when logging weights. Empty list = not saved yet."""
    ds = os.environ.get("NOTION_EXERCISELIB_DS", "")
    if not ds:
        return {"error": "NOTION_EXERCISELIB_DS is not set on this server — search ExerciseLib via the Notion connector instead."}
    q = query.strip()
    ck = ("exlib", q.lower())
    c = _cget(ck)
    if c is not None:
        _bump("exercise_find", c)[2] += 1
        return c

    def _q(term):
        flt = {"filter": {"property": "name", "title": {"contains": term}}, "page_size": 10}
        try:
            try:
                return _notion("POST", f"/databases/{ds}/query", flt, "2022-06-28")
            except Exception:
                return _notion("POST", f"/data_sources/{ds}/query", flt, "2025-09-03")
        except Exception:
            return None
    r = _q(q)
    if r is None:
        return {"error": "ExerciseLib query failed"}
    if not r.get("results"):
        for w in sorted((w for w in q.split() if len(w) >= 3), key=len, reverse=True):
            rr = _q(w)
            if rr and rr.get("results"):
                r = rr
                break
    out = []
    for row in r.get("results", []):
        p = row.get("properties", {})

        def num(k):
            return (p.get(k) or {}).get("number")

        def txt(k):
            rt = (p.get(k) or {}).get("rich_text") or []
            return "".join(t.get("plain_text", "") for t in rt) or None

        def sel(k):
            return (((p.get(k) or {}).get("select")) or {}).get("name")

        title = (p.get("name") or {}).get("title") or []
        out.append({"name": "".join(t.get("plain_text", "") for t in title),
                    "muscle_group": sel("muscle_group"), "default_load": num("default_load"),
                    "notes": txt("notes")})
    _cput(ck, out, 600)
    _bump("exercise_find", out)
    return out


_playbook_cache = {"text": "", "ts": 0.0}


_PB_ONDEMAND = ("post-workout", "weekly summary", "body scans", "alcohol", "injury", "exercise", "weight training", "training plan", "personal baselines", "coach me today", "progress check", "coaching brain")


def _pb_fetch():
    import time
    import urllib.request as _u
    url = os.environ.get("PLAYBOOK_URL", "")
    if not url:
        return "No PLAYBOOK_URL configured on the server."
    now = time.time()
    if _playbook_cache["text"] and now - _playbook_cache["ts"] < 900:
        return _playbook_cache["text"]
    try:
        with _u.urlopen(url, timeout=10) as r:
            t = r.read().decode("utf-8")
        _playbook_cache["text"] = t
        _playbook_cache["ts"] = now
        return t
    except Exception as e:
        return _playbook_cache["text"] or f"playbook fetch failed: {e}"


@mcp.tool()
def get_playbook(section: str = "") -> str:
    """The latest coaching rules. Call once (no args) at the start of any food/training/coaching conversation: returns the core rules plus a list of on-demand sections. The moment on-demand topics come up, call again with section="<name>" (or several at once: section="post-workout, coaching brain") to get those rules in one call."""
    text = _pb_fetch()
    if "\n## " not in text:
        return text
    head, *parts = text.split("\n## ")
    secs = []
    for pt in parts:
        h, _, b = pt.partition("\n")
        secs.append((h.strip(), b))
    if section:
        # accept ONE or MANY sections (comma-separated) in a single call — fewer round-trips
        wanted = [x.strip().lower() for x in section.split(",") if x.strip()]
        out = []
        for w in wanted:
            for h, b in secs:
                if w in h.lower():
                    out.append(f"## {h}\n{b}")
                    break
        if out:
            return "\n\n".join(out)
        return "Section(s) not found. Available: " + " | ".join(h for h, _ in secs)
    core = [head]
    skipped = []
    for h, b in secs:
        if any(k in h.lower() for k in _PB_ONDEMAND):
            skipped.append(h.split(" (")[0])
        else:
            core.append(f"## {h}\n{b}")
    core.append('## On-demand sections (not included above)\nThe moment one of these topics comes up, call get_playbook(section="<name>") and follow it: '
                + " · ".join(skipped))
    return "\n".join(core)


# ---- HTTP wiring -----------------------------------------------------------
SECRET = os.environ.get("MCP_SECRET")
if not SECRET:
    raise RuntimeError("MCP_SECRET must be set — refusing to start with a default secret")

import contextlib


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


root = Starlette(
    routes=[
        Route("/", lambda r: PlainTextResponse("ok")),
        Route(f"/{SECRET}/closeday", closeday),
        Route(f"/{SECRET}/health", health),
        Route(f"/{SECRET}/stats", lambda r: __import__("starlette.responses", fromlist=["JSONResponse"]).JSONResponse(
            {t: {"calls": v[0], "chars": v[1], "cache_hits": v[2]} for t, v in sorted(_usage.items())})),
        Mount(f"/{SECRET}", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(root, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
