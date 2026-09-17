# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.10,<2", "garminconnect>=0.3.2", "fitparse>=1.2.0"]
# ///
"""MCP-Server „garmin“ für Claude Code – läuft auf PC und in Cloud-Sessions (Smartphone) identisch.

Start (stdio):   uv run scripts/garmin_mcp_server.py
Nur Abhängigkeiten installieren (Session-Start-Hook):  uv run scripts/garmin_mcp_server.py --warmup

Anmeldung über Umgebungsvariablen, siehe garmin_auth.py:
  GARMIN_EMAIL, GARMIN_PASSWORD           (Passwort nur nötig, wenn keine Tokens vorhanden)
  GARMINTOKENS                            Token-Ordner (Standard ~/.garminconnect)
  GARMIN_TOKENS_B64 / GARMIN_TOKENS_JSON  Token-Inhalt für Cloud-Sessions (aus garmin_login.py --show-token)

Tools liefern kompakte, normalisierte Daten (Pace in s/km + "m:ss", Distanzen in m, Zeiten in s).
Die Sekunden-Zeitreihe wird nur ausgedünnt geliefert; die vollständige Analyse macht analyze_run
(speichert alles unter data/garmin/<datum>_<id>/ und gibt den Bericht zurück).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

if "--warmup" in sys.argv:
    import fitparse  # noqa: F401
    import garminconnect  # noqa: F401
    import mcp  # noqa: F401

    print("garmin-mcp: Abhängigkeiten installiert.")
    raise SystemExit(0)

from mcp.server.fastmcp import FastMCP  # noqa: E402

import garmin_auth  # noqa: E402
import garmin_export as ge  # noqa: E402
import garmin_workout as gw  # noqa: E402

mcp_server = FastMCP("garmin")
_client: Any = None


def _client_or_raise():
    global _client
    if _client is None:
        try:
            _client = garmin_auth.connect(interactive=False)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Garmin-Anmeldung fehlgeschlagen: {exc}. "
                "Tokens fehlen oder sind abgelaufen: auf dem PC `uv run scripts/garmin_login.py --force` "
                "ausführen; in einer Cloud-Session `uv run scripts/garmin_login.py --mfa-file /tmp/mfa.txt` "
                "starten und den MFA-Code in diese Datei schreiben. Danach GARMIN_TOKENS_B64 aktualisieren "
                "(`garmin_login.py --show-token`)."
            ) from exc
    return _client


def _call(fn_name: str, *args: Any, **kwargs: Any) -> Any:
    c = _client_or_raise()
    try:
        return getattr(c, fn_name)(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Garmin-API-Fehler in {fn_name}: {exc}") from exc


def _compact(act: dict[str, Any]) -> dict[str, Any]:
    n = ge.normalize_summary_api(act)
    return {
        "activity_id": n["activity_id"],
        "name": n["name"],
        "type": n["type"],
        "start_local": n["start_local"],
        "date": n["date"],
        "distance_km": round((n["distance_m"] or 0) / 1000, 2),
        "duration_s": n["duration_s"],
        "duration_str": ge.fmt_dur(n["duration_s"]),
        "pace_str": ge.fmt_pace(n["pace_s_per_km"]),
        "avg_hr": n["avg_hr"],
        "max_hr": n["max_hr"],
        "elev_gain_m": n["elev_gain_m"],
        "avg_cadence_spm": n["avg_cadence_spm"],
    }


def _type_key(act: dict[str, Any]) -> str | None:
    return (act.get("activityType") or act.get("activityTypeDTO") or {}).get("typeKey")


def _base_dir(out_dir: str | None) -> Path:
    return Path(out_dir or os.environ.get("LAUFANALYSE_DATA_DIR") or "data/garmin")


# ---------------------------------------------------------------------------
# Aktivitäten finden
# ---------------------------------------------------------------------------


@mcp_server.tool()
def get_activities(start: int = 0, limit: int = 10, activity_type: str | None = None) -> list[dict[str, Any]]:
    """Letzte Aktivitäten (neueste zuerst), kompakt. activity_type z. B. "running" filtert serverseitig."""
    acts = _call("get_activities", start, limit, activity_type) or []
    return [_compact(a) for a in acts]


@mcp_server.tool()
def get_activities_by_date(start_date: str, end_date: str, activity_type: str | None = "running") -> list[dict[str, Any]]:
    """Aktivitäten im Zeitraum (YYYY-MM-DD), kompakt. Standardfilter: running."""
    acts = _call("get_activities_by_date", start_date, end_date, activity_type) or []
    return [_compact(a) for a in acts]


@mcp_server.tool()
def get_last_run() -> dict[str, Any]:
    """Der neueste Lauf (Aktivitätstyp enthält 'running'), kompakt."""
    for start in (0, 20, 40):
        acts = _call("get_activities", start, 20) or []
        if not acts:
            break
        for a in acts:
            if ge.is_run(_type_key(a)):
                return _compact(a)
    raise RuntimeError("Kein Lauf unter den letzten 60 Aktivitäten gefunden.")


@mcp_server.tool()
def get_activity(activity_id: int) -> dict[str, Any]:
    """Zusammenfassung einer Aktivität (normalisiert: Distanz m, Dauer s, Pace, HF, Kadenz, Höhenmeter, TE, VO2max)."""
    n = ge.normalize_summary_api(_call("get_activity", activity_id))
    n["pace_str"] = ge.fmt_pace(n["pace_s_per_km"])
    n["duration_str"] = ge.fmt_dur(n["duration_s"])
    return n


# ---------------------------------------------------------------------------
# Detaildaten
# ---------------------------------------------------------------------------


@mcp_server.tool()
def get_activity_laps(activity_id: int) -> list[dict[str, Any]]:
    """Laps/Splits (Rundentaste bzw. Workout-Schritte): Nr, Start s, Distanz m, Dauer s, Pace, Ø-HF, Max-HF, Kadenz, intensity (bei Workouts)."""
    activity = _call("get_activity", activity_id)
    start = ge.parse_garmin_time(ge.normalize_summary_api(activity).get("start_gmt"))
    laps = ge.normalize_laps_api(_call("get_activity_splits", activity_id) or {}, start)
    for lap in laps:
        lap["pace_str"] = ge.fmt_pace(lap["pace_s_per_km"])
        lap["duration_str"] = ge.fmt_dur(lap["duration_s"])
    return laps


@mcp_server.tool()
def get_activity_typed_splits(activity_id: int) -> Any:
    """Rohdaten /typedsplits (Intervallstruktur strukturierter Workouts)."""
    return _call("get_activity_typed_splits", activity_id)


@mcp_server.tool()
def get_activity_timeseries(activity_id: int, step_s: int = 10, max_chart: int = 100000) -> dict[str, Any]:
    """Ausgedünnte Zeitreihe (alle step_s Sekunden): t_s, distance_m, hr, pace_s_per_km, elev_m, cadence_spm, power_w.
    Für Sekundenauflösung analyze_run nutzen (schreibt timeseries.csv)."""
    details = _call("get_activity_details", activity_id, maxchart=max_chart, maxpoly=1)
    ts = ge.normalize_timeseries_api(details or {})
    keep = ["t_s", "distance_m", "hr", "pace_s_per_km", "elev_m", "cadence_spm", "power_w"]
    rows, next_t = [], 0.0
    for r in ts:
        if r["t_s"] >= next_t:
            rows.append({k: (round(r[k], 1) if isinstance(r.get(k), float) else r.get(k)) for k in keep if r.get(k) is not None})
            next_t = r["t_s"] + step_s
    return {"points_total": len(ts), "step_s": step_s, "rows": rows}


@mcp_server.tool()
def get_activity_hr_zones(activity_id: int) -> list[dict[str, Any]]:
    """Zeit je HF-Zone: zone, low_bpm, seconds, minutes, percent."""
    zones = ge.normalize_zones_api(_call("get_activity_hr_in_timezones", activity_id))
    total = sum(z["seconds"] for z in zones)
    return [{**z, "minutes": round(z["seconds"] / 60, 1), "percent": round(100 * z["seconds"] / total, 1) if total else None} for z in zones]


@mcp_server.tool()
def get_activity_weather(activity_id: int) -> dict[str, Any]:
    """Wetter während der Aktivität (temp_c, feels_like_c, humidity_pct, wind_kmh, condition) plus Rohwerte."""
    raw = _call("get_activity_weather", activity_id)
    return {**ge.normalize_weather_api(raw), "raw": raw}


# ---------------------------------------------------------------------------
# Komplettanalyse + Sicherung
# ---------------------------------------------------------------------------


@mcp_server.tool()
def analyze_run(
    activity_id: int | None = None,
    date: str | None = None,
    recovery_hr: int = 140,
    work_factor: float = 0.93,
    min_lap_km: float = 0.2,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Lauf komplett laden (Summary, Laps, Sekunden-Zeitreihe, HF-Zonen, Wetter), unter
    <out_dir>/<datum>_<id>/ als CSV/JSON sichern und analysieren. Ohne activity_id/date: letzter Lauf.
    Rückgabe: output_dir, summary_md (fertiger Bericht) und analysis (Laps mit Typ/HF-Anstieg, Intervall-Kennzahlen, Zonen)."""
    c = _client_or_raise()
    aid = ge.resolve_activity_id(c, activity_id=activity_id, date=date)
    summary, laps, ts, zones, weather, raw, errors = ge.fetch_from_api(c, aid, max_chart=100000)
    analysis = ge.analyze(summary, laps, ts, zones, weather, recovery_hr=recovery_hr, work_factor=work_factor, min_lap_km=min_lap_km)
    if errors:
        analysis["notes"] = [f"API-Fehler: {e}" for e in errors] + analysis["notes"]
    out = _base_dir(out_dir) / f"{summary.get('date')}_{summary.get('activity_id')}"
    ge.write_outputs(out, analysis, ts, raw)
    analysis["output_dir"] = str(out.resolve())
    return {"output_dir": str(out.resolve()), "summary_md": ge.render_markdown(analysis), "analysis": analysis}


@mcp_server.tool()
def analyze_fit(
    fit_path: str,
    recovery_hr: int = 140,
    work_factor: float = 0.93,
    min_lap_km: float = 0.2,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Fallback ohne API: FIT-Datei (oder ZIP aus Garmin Connect „Original exportieren“) wie analyze_run verarbeiten."""
    p = Path(fit_path).expanduser()
    if not p.is_file():
        raise RuntimeError(f"FIT-Datei nicht gefunden: {p}")
    summary, laps, ts, zones = ge.parse_fit(p)
    analysis = ge.analyze(summary, laps, ts, zones, {}, recovery_hr=recovery_hr, work_factor=work_factor, min_lap_km=min_lap_km)
    out = _base_dir(out_dir) / f"{summary.get('date')}_{summary.get('activity_id')}"
    ge.write_outputs(out, analysis, ts, {})
    analysis["output_dir"] = str(out.resolve())
    return {"output_dir": str(out.resolve()), "summary_md": ge.render_markdown(analysis), "analysis": analysis}


@mcp_server.tool()
def list_exported(out_dir: str | None = None) -> list[dict[str, Any]]:
    """Bereits gesicherte Läufe (Ordner, Datum, ID, km, Dauer, Pace, Ø-HF, Intervalle) – für Vergleiche ohne neuen API-Zugriff."""
    import json

    base = _base_dir(out_dir)
    rows = []
    if base.exists():
        for d in sorted(base.iterdir()):
            f = d / "analysis.json"
            if f.is_file():
                a = json.loads(f.read_text(encoding="utf-8"))
                s, iv = a["summary"], a.get("intervals") or {}
                rows.append({
                    "dir": str(d.resolve()), "date": s.get("date"), "activity_id": s.get("activity_id"), "name": s.get("name"),
                    "distance_km": round((s.get("distance_m") or 0) / 1000, 2), "duration_str": s.get("duration_str"),
                    "pace_str": s.get("pace_str"), "avg_hr": s.get("avg_hr"), "intervals": iv.get("count", 0),
                    "interval_pace_str": iv.get("avg_pace_str"), "interval_avg_hr": iv.get("avg_hr"),
                })
    return rows


# ---------------------------------------------------------------------------
# Kontext & Status
# ---------------------------------------------------------------------------


@mcp_server.tool()
def get_training_context(date: str) -> dict[str, Any]:
    """Trainingskontext für ein Datum (YYYY-MM-DD): Trainingsstatus, Trainingsbereitschaft, HRV, Schlaf (Kurzform), Ruhepuls."""
    out: dict[str, Any] = {}
    for key, fn, args in (
        ("training_status", "get_training_status", (date,)),
        ("training_readiness", "get_training_readiness", (date,)),
        ("hrv", "get_hrv_data", (date,)),
        ("sleep", "get_sleep_data", (date,)),
        ("resting_hr", "get_rhr_day", (date,)),
    ):
        try:
            val = _call(fn, *args)
            if key == "hrv" and isinstance(val, dict):
                val = {k: v for k, v in val.items() if k != "hrvReadings"}
            if key == "sleep" and isinstance(val, dict):
                val = val.get("dailySleepDTO", val)
            out[key] = val
        except Exception as exc:  # noqa: BLE001
            out[key] = {"error": str(exc)}
    return out


@mcp_server.tool()
def get_user_profile() -> Any:
    """Garmin-Profil (Name, Einheiten, Einstellungen)."""
    return _call("get_user_profile")


@mcp_server.tool()
def login_status() -> dict[str, Any]:
    """Prüft Token-Ordner, Umgebungsvariablen und ob die Anmeldung funktioniert."""
    info: dict[str, Any] = {
        "token_dir": str(garmin_auth.token_dir()),
        "tokens_present": garmin_auth.tokens_present(),
        "env_email_set": bool(os.environ.get("GARMIN_EMAIL")),
        "env_password_set": bool(os.environ.get("GARMIN_PASSWORD")),
        "env_tokens_blob_set": bool(os.environ.get("GARMIN_TOKENS_B64") or os.environ.get("GARMIN_TOKENS_JSON")),
        "data_dir": str(_base_dir(None).resolve()),
    }
    try:
        info["logged_in_as"] = garmin_auth.whoami(_client_or_raise())
        info["ok"] = True
    except Exception as exc:  # noqa: BLE001
        info["ok"] = False
        info["error"] = str(exc)
    return info


# ----------------------------------------------------------------------------
# Workouts anlegen (Skill /workout) – Schreibzugriffe auf das Garmin-Konto
# ----------------------------------------------------------------------------


@mcp_server.tool()
def list_workouts(limit: int = 20) -> list[dict[str, Any]]:
    """Workouts der Garmin-Bibliothek: workout_id, name, sport."""
    out = []
    for w in _call("get_workouts", 0, limit) or []:
        out.append({
            "workout_id": w.get("workoutId"),
            "name": w.get("workoutName"),
            "sport": (w.get("sportType") or {}).get("sportTypeKey"),
        })
    return out


@mcp_server.tool()
def get_workout(workout_id: int) -> dict[str, Any]:
    """Ein Workout aus der Bibliothek: lesbare Schrittliste (text) und Rohdaten (raw)."""
    w = _call("get_workout_by_id", workout_id)
    return {"workout_id": workout_id, "text": gw.describe(w), "raw": w}


@mcp_server.tool()
def create_workout(spec: dict[str, Any], schedule_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Workout aus einer Spezifikation anlegen (Schreibzugriff!) und optional im Kalender terminieren.

    spec = {"name": str, "sport": "running|cycling|swimming|walking|hiking|other", "description": str?,
            "steps": [ {"type": "warmup|interval|recovery|rest|cooldown", "duration_s": 120 | "distance_m": 1000 | "end": "lap",
                        "target": {"hr_bpm": [90, 130]} | {"hr_zone": 2} | {"pace_min_km": ["4:10", "4:20"]} | null,
                        "note": "Text auf der Uhr"?},
                       {"repeat": 6, "steps": [...]} ] }
    schedule_date: YYYY-MM-DD (z. B. morgen). dry_run=True zeigt nur die Struktur, lädt nichts hoch.
    Rückgabe: text (Schrittliste), workout_id, schedule (falls terminiert). Immer erst dry_run zeigen und
    den Nutzer bestätigen lassen.
    """
    payload = gw.build_workout(spec)
    result: dict[str, Any] = {"text": gw.describe(payload), "dry_run": dry_run}
    if dry_run:
        return result
    res = _call("upload_workout", payload)
    wid = res.get("workoutId")
    saved = _call("get_workout_by_id", wid)
    result.update({"workout_id": wid, "text": gw.describe(saved), "uploaded": True})
    if schedule_date:
        r = _call("schedule_workout", wid, schedule_date)
        result["schedule"] = {"date": schedule_date, "workout_schedule_id": r.get("workoutScheduleId") if isinstance(r, dict) else r}
    return result


@mcp_server.tool()
def schedule_workout(workout_id: int, date: str) -> dict[str, Any]:
    """Vorhandenes Workout an einem Datum (YYYY-MM-DD) in den Garmin-Kalender eintragen (Schreibzugriff)."""
    r = _call("schedule_workout", workout_id, date)
    return {"workout_id": workout_id, "date": date, "result": r}


@mcp_server.tool()
def list_scheduled_workouts(year: int, month: int) -> list[dict[str, Any]]:
    """Terminierte Workouts eines Monats im Garmin-Kalender: date, name, workout_id, schedule_id."""
    return gw.scheduled_workouts(_client_or_raise(), year, month)


@mcp_server.tool()
def unschedule_workout(schedule_id: int) -> dict[str, Any]:
    """Termin aus dem Kalender entfernen (schedule_id aus list_scheduled_workouts); das Workout bleibt in der Bibliothek."""
    _call("unschedule_workout", schedule_id)
    return {"schedule_id": schedule_id, "unscheduled": True}


@mcp_server.tool()
def delete_workout(workout_id: int) -> dict[str, Any]:
    """Workout aus der Bibliothek löschen (Schreibzugriff, nur auf ausdrücklichen Wunsch des Nutzers)."""
    _call("delete_workout", workout_id)
    return {"workout_id": workout_id, "deleted": True}


if __name__ == "__main__":
    mcp_server.run(transport="stdio")
