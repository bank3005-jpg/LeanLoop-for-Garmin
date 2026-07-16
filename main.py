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


def slim(obj, max_list=40, depth=0):
    """Drop huge time-series arrays so responses stay small."""
    if depth > 8:
        return "..."
    if isinstance(obj, dict):
        return {k: slim(v, max_list, depth + 1) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        if len(obj) > max_list:
            return f"<{len(obj)} data points omitted>"
        return [slim(v, max_list, depth + 1) for v in obj]
    return obj


def day(d: str) -> str:
    if not d or d in ("today",):
        return date.today().isoformat()
    if d == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return d


def call(fn, *args):
    global _garmin
    try:
        return slim(fn(client())(*args))
    except Exception:
        _garmin = None  # token likely expired in-session: retry with fresh login
        try:
            return slim(fn(client())(*args))
        except Exception as e:
            return {"error": str(e)}


_SLEEP_NOISE = (
    "sleepLevels", "sleepMovement", "sleepRestlessMoments", "sleepHeartRate",
    "sleepStress", "sleepBodyBattery", "hrvData", "breathingDisruptionData",
    "wellnessEpochRespirationDataDTOList", "wellnessEpochRespirationAveragesList",
    "wellnessEpochSPO2DataDTOList", "sleepNeed", "nextSleepNeed",
)


@mcp.tool()
def get_sleep(date: str = "", full: bool = False) -> dict:
    """Sleep for a night: score, duration, deep/light/REM/awake, HRV during sleep, resting HR, body battery change. date=YYYY-MM-DD, default today (i.e. last night). full=true returns raw time-series too."""
    r = call(lambda g: g.get_sleep_data, day(date))
    if not full and isinstance(r, dict):
        r = {k: v for k, v in r.items() if k not in _SLEEP_NOISE}
    return r


@mcp.tool()
def get_hrv(date: str = "") -> dict:
    """HRV status for a night: last-night avg, weekly avg, baseline, status. date=YYYY-MM-DD."""
    return call(lambda g: g.get_hrv_data, day(date))


@mcp.tool()
def get_stress(date: str = "") -> dict:
    """All-day stress summary for a date."""
    return call(lambda g: g.get_stress_data, day(date))


@mcp.tool()
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


@mcp.tool()
def get_heart_rate(date: str = "") -> dict:
    """Heart rate summary for a date: resting, min, max, last 7 days avg resting."""
    return call(lambda g: g.get_heart_rates, day(date))


@mcp.tool()
def get_spo2(date: str = "") -> dict:
    """Blood oxygen (SpO2) summary for a date."""
    return call(lambda g: g.get_spo2_data, day(date))


@mcp.tool()
def get_respiration(date: str = "") -> dict:
    """Respiration rate summary for a date."""
    return call(lambda g: g.get_respiration_data, day(date))


@mcp.tool()
def get_training_readiness(date: str = "") -> dict:
    """Training readiness score and contributing factors."""
    return call(lambda g: g.get_training_readiness, day(date))


@mcp.tool()
def get_training_status(date: str = "") -> dict:
    """Training status: load, VO2max, acute/chronic load."""
    return call(lambda g: g.get_training_status, day(date))


@mcp.tool()
def get_activities(limit: int = 10) -> list | dict:
    """Recent activities (runs, rides, workouts...). Returns key fields per activity."""
    def f(g):
        acts = g.get_activities(0, min(limit, 50))
        keep = (
            "activityId", "activityName", "startTimeLocal", "distance",
            "duration", "calories", "averageHR", "maxHR", "averageSpeed",
            "elevationGain", "activityType", "aerobicTrainingEffect",
            "anaerobicTrainingEffect", "avgStressLevel",
            "averageRunningCadenceInStepsPerMinute", "maxRunningCadenceInStepsPerMinute",
            "avgPower", "vO2MaxValue", "avgVerticalOscillation",
            "avgGroundContactTime", "avgStrideLength", "maxSpeed", "movingDuration",
        )
        return [{k: a.get(k) for k in keep if a.get(k) is not None} for a in acts]
    return call(lambda g: lambda: f(g))


@mcp.tool()
def get_body_composition(date: str = "") -> dict:
    """Weight / body composition entries for a date."""
    return call(lambda g: g.get_body_composition, day(date))


@mcp.tool()
def get_activity_details(activity_id: str) -> dict:
    """Full summary of one activity: cadence, power, VO2max, running dynamics, weather. Get activity_id from get_activities."""
    return call(lambda g: g.get_activity, activity_id)


@mcp.tool()
def get_activity_splits(activity_id: str) -> dict:
    """Per-lap/km splits of one activity: pace, HR, cadence per split."""
    return call(lambda g: g.get_activity_splits, activity_id)


@mcp.tool()
def get_activity_hr_zones(activity_id: str) -> list | dict:
    """Time spent in each heart-rate zone for one activity."""
    return call(lambda g: g.get_activity_hr_in_timezones, activity_id)


@mcp.tool()
def get_activities_range(start_date: str, end_date: str = "", activity_type: str = "") -> list | dict:
    """Activities between two dates (YYYY-MM-DD). Optional activity_type: running, cycling, swimming, fitness_equipment..."""
    return call(lambda g: lambda: g.get_activities_by_date(start_date, end_date or None, activity_type or None))


@mcp.tool()
def get_race_predictions() -> dict:
    """Predicted race times for 5K, 10K, half marathon, marathon."""
    return call(lambda g: lambda: g.get_race_predictions())


@mcp.tool()
def get_vo2max(date: str = "") -> dict:
    """VO2max and max metrics for a date."""
    return call(lambda g: g.get_max_metrics, day(date))


@mcp.tool()
def get_fitness_age(date: str = "") -> dict:
    """Fitness age estimate and contributing factors."""
    return call(lambda g: g.get_fitnessage_data, day(date))


@mcp.tool()
def get_endurance_score(date: str = "") -> dict:
    """Endurance score for a date."""
    return call(lambda g: g.get_endurance_score, day(date))


@mcp.tool()
def get_hill_score(date: str = "") -> dict:
    """Hill score (running strength on hills) for a date."""
    return call(lambda g: g.get_hill_score, day(date))


@mcp.tool()
def get_personal_records() -> list | dict:
    """All personal records (fastest 1K/5K/10K, longest run/ride, max steps...)."""
    return call(lambda g: lambda: g.get_personal_record())


@mcp.tool()
def get_weight_history(start_date: str, end_date: str = "") -> dict:
    """Weigh-in history between dates (YYYY-MM-DD)."""
    return call(lambda g: lambda: g.get_weigh_ins(start_date, end_date or day("")))


@mcp.tool()
def get_hydration(date: str = "") -> dict:
    """Water intake logged for a date."""
    return call(lambda g: g.get_hydration_data, day(date))


@mcp.tool()
def get_blood_pressure(start_date: str = "", end_date: str = "") -> dict:
    """Blood pressure readings between dates (if logged in Garmin Connect)."""
    return call(lambda g: lambda: g.get_blood_pressure(start_date or day(""), end_date or None))


@mcp.tool()
def get_intensity_minutes(date: str = "") -> dict:
    """Intensity minutes (moderate/vigorous) for a date."""
    return call(lambda g: g.get_intensity_minutes_data, day(date))


@mcp.tool()
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
    return call(lambda g: lambda: f(g))


@mcp.tool()
def get_coach_snapshot() -> dict:
    """ONE-CALL coaching snapshot: today's training readiness, last night's sleep summary (score/HRV/RHR/body battery), today's status, and last 7 days activities (compact). Prefer this over separate calls for daily coaching questions."""
    def f(g):
        from datetime import date as _d, timedelta as _td
        today = _d.today().isoformat()
        week_ago = (_d.today() - _td(days=7)).isoformat()
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


def _close_one(d):
    row = _find_row(d)
    if not row:
        return {"date": d, "status": "no-foodlog-row"}
    props = row.get("properties", {})
    kcal = (props.get("kcal") or {}).get("number")
    row_burn = (props.get("exercise_burn") or {}).get("number") or 0
    try:
        stats = client().get_stats(d) or {}
    except Exception:
        stats = {}
    total = stats.get("totalKilocalories")
    try:
        acts = client().get_activities_by_date(d, d) or []
    except Exception:
        acts = []
    new_props = {}
    if total:
        tdee = round(total)
        if not acts and row_burn:
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
        cardio = ("running", "cycling", "walking", "treadmill_running",
                  "indoor_cycling", "lap_swimming", "open_water_swimming")
        names, burn = [], 0.0
        for a in acts:
            t = ((a.get("activityType") or {}).get("typeKey") or "")
            burn += (a.get("calories") or 0) * (0.90 if t in cardio else 0.85)
            names.append(a.get("activityName") or t)
        if not ((props.get("exercise_type") or {}).get("rich_text") or []):
            new_props["exercise_type"] = {"rich_text": [{"text": {"content": ", ".join(names)[:200]}}]}
        if (props.get("exercise_burn") or {}).get("number") in (None, 0):
            new_props["exercise_burn"] = {"number": round(burn)}
    if not new_props:
        return {"date": d, "status": "already-synced", "tdee": tdee}
    _notion_write("PATCH", "/pages/" + row["id"], {"properties": new_props})
    return {"date": d, "status": "updated", "tdee": tdee, "tag": tag,
            "wrote": list(new_props)}


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
    try:
        _notion("PATCH", f"/databases/{FOODLOG_DS}",
                {"description": [{"type": "text", "text": {"content": text}}]},
                "2022-06-28")
    except Exception:
        pass
    if block_id:
        _notion("PATCH", "/blocks/" + block_id, body, "2022-06-28")
    else:
        _notion("PATCH", f"/blocks/{page_id}/children",
                {"children": [{"object": "block", "type": "callout",
                               "callout": {"rich_text": [{"type": "text", "text": {"content": text}}],
                                           "icon": {"type": "emoji", "emoji": "\U0001F525"}}}]},
                "2022-06-28")
    return {"progress": text}


async def closeday(request):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from starlette.responses import JSONResponse
    today = datetime.now(ZoneInfo(os.environ.get("TZ_NAME", "Asia/Bangkok"))).date()
    out = []
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
    mid = len(work) // 2
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


@mcp.tool()
def get_activity_stream(activity_id: str, metrics: str = "heart_rate,speed,cadence",
                        max_points: int = 60) -> dict:
    """Downsampled second-by-second sensor streams from an activity's FIT file. metrics: comma list from heart_rate,speed,cadence,power,altitude,distance. Returns ~max_points averaged buckets."""
    def f():
        recs = _fit_records(activity_id)
        if not recs:
            return {"error": "no record data in FIT file"}
        want = [m.strip() for m in metrics.split(",") if m.strip()]
        t0 = recs[0]["timestamp"]
        n = max(1, len(recs) // max(1, min(max_points, 200)))
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
    return call(lambda g: lambda: f())


@mcp.tool()
def get_aerobic_decoupling(activity_id: str, skip_warmup_min: float = 5.0) -> dict:
    """Aerobic decoupling (Pa:Hr drift) for a steady activity: compares speed/HR efficiency of first vs second half. <5% = strong aerobic base. Use on steady runs/rides, not intervals."""
    def f():
        return _decoupling_calc(_fit_records(activity_id), skip_warmup_min)
    return call(lambda g: lambda: f())


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


@mcp.tool()
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
            "tdee_est": num("tdee_est"), "deficit_actual": _deficit_val(p)}


@mcp.tool()
def foodlog_get_range(start_date: str, end_date: str = "") -> list | dict:
    """Read FoodLog rows for a date range (inclusive, YYYY-MM-DD) in ONE call — compact rows sorted by date. Use this for weekly summaries instead of calling foodlog_get per day."""
    s, e = day(start_date), day(end_date)
    flt = {"filter": {"and": [
        {"property": "date", "date": {"on_or_after": s}},
        {"property": "date", "date": {"on_or_before": e}},
    ]}, "page_size": 100}
    try:
        try:
            r = _notion("POST", f"/databases/{FOODLOG_DS}/query", flt, "2022-06-28")
        except Exception:
            r = _notion("POST", f"/data_sources/{FOODLOG_DS}/query", flt, "2025-09-03")
    except Exception as ex:
        return {"error": str(ex)}
    out = []
    for row in r.get("results", []):
        p = row.get("properties", {})

        def num(k):
            return (p.get(k) or {}).get("number")

        def txt(k):
            rt = (p.get(k) or {}).get("rich_text") or []
            return "".join(t.get("plain_text", "") for t in rt) or None

        title = (p.get("day") or {}).get("title") or []
        out.append({"date": ((p.get("date") or {}).get("date") or {}).get("start"),
                    "day": "".join(t.get("plain_text", "") for t in title) or None,
                    "kcal": num("kcal"), "p": num("p"), "c": num("c"), "f": num("f"),
                    "exercise_type": txt("exercise_type"), "exercise_burn": num("exercise_burn"),
                    "tdee_est": num("tdee_est"), "deficit_actual": _deficit_val(p),
                    "sync": (((p.get("sync") or {}).get("select")) or {}).get("name")})
    out.sort(key=lambda x: x["date"] or "")
    return out


@mcp.tool()
def foodlog_upsert(date: str = "", kcal: float | None = None, p: float | None = None,
                   c: float | None = None, f: float | None = None,
                   exercise_type: str | None = None,
                   exercise_burn: float | None = None,
                   tdee_est: float | None = None) -> dict:
    """Create or update the Notion FoodLog row for a date (one row per day, exact match — never creates duplicates). Only provided fields are written; omitted fields stay unchanged. date=YYYY-MM-DD, default today."""
    d = day(date)
    props = {}
    for k, v in (("kcal", kcal), ("p", p), ("c", c), ("f", f),
                 ("exercise_burn", exercise_burn), ("tdee_est", tdee_est)):
        if v is not None:
            props[k] = {"number": v}
    if exercise_type is not None:
        props["exercise_type"] = {"rich_text": [{"text": {"content": exercise_type[:200]}}]}
    if not props:
        return {"error": "no fields provided"}
    if any(k in props for k in ("kcal", "p", "c", "f")) and "tdee_est" not in props:
        props["sync"] = {"select": {"name": "pending"}}

    try:
        row = _find_row(d)
        if row:
            _notion_write("PATCH", "/pages/" + row["id"], {"properties": props})
            return {"date": d, "status": "updated", "page_id": row["id"],
                    "wrote": list(props)}
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
        return {"date": d, "status": "created", "page_id": r.get("id"), "day": title}
    except Exception as e:
        return {"error": str(e)}


_playbook_cache = {"text": "", "ts": 0.0}


_PB_ONDEMAND = ("post-workout", "weekly summary", "body scans", "alcohol")


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
    """The latest coaching rules. Call once (no args) at the start of any food/training/coaching conversation: returns the core rules plus a list of on-demand sections. The moment an on-demand topic comes up, call again with section="<name>" to get those rules."""
    text = _pb_fetch()
    if "\n## " not in text:
        return text
    head, *parts = text.split("\n## ")
    secs = []
    for pt in parts:
        h, _, b = pt.partition("\n")
        secs.append((h.strip(), b))
    if section:
        q = section.lower()
        for h, b in secs:
            if q in h.lower():
                return f"## {h}\n{b}"
        return "Section not found. Available: " + " | ".join(h for h, _ in secs)
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
SECRET = os.environ.get("MCP_SECRET", "dev")

import contextlib


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


root = Starlette(
    routes=[
        Route("/", lambda r: PlainTextResponse("ok")),
        Route(f"/{SECRET}/closeday", closeday),
        Mount(f"/{SECRET}", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(root, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
