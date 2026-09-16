# /// script
# requires-python = ">=3.11"
# dependencies = ["garminconnect>=0.3.2", "fitparse>=1.2.0"]
# ///
"""Rohdaten eines Garmin-Laufs sichern und Intervall-Kennzahlen berechnen.

Speichert Laps, Sekunden-Zeitreihe, HF-Zonen und Wetter als CSV/JSON in
    <out>/<YYYY-MM-DD>_<aktivitaets-id>/
und berechnet daraus analysis.json + summary.md (deutsch, Pace in min/km, Zeiten mm:ss).

Beispiele:
    uv run scripts/garmin_export.py                      # letzter Lauf
    uv run scripts/garmin_export.py --date 2026-09-14    # Lauf an diesem Datum
    uv run scripts/garmin_export.py --id 1234567890      # Aktivitäts-ID
    uv run scripts/garmin_export.py --fit export.fit     # Fallback: FIT-Datei aus Garmin Connect
    uv run scripts/garmin_export.py --list 5             # letzte 5 Aktivitäten anzeigen
    uv run scripts/garmin_export.py --exported           # bereits gesicherte Läufe auflisten

Ausgabe-Ordner: --out, sonst $LAUFANALYSE_DATA_DIR, sonst ./data/garmin
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import statistics
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ----------------------------------------------------------------------------
# Formatierung (deutsch)
# ----------------------------------------------------------------------------


def fmt_pace(sec_per_km: float | None) -> str:
    if sec_per_km is None or not math.isfinite(sec_per_km) or sec_per_km <= 0:
        return "–"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}"


def fmt_dur(sec: float | None) -> str:
    if sec is None or not math.isfinite(sec):
        return "–"
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_km(meters: float | None, digits: int = 2) -> str:
    if meters is None:
        return "–"
    return f"{meters / 1000:.{digits}f}".replace(".", ",")


def fmt_num(x: float | None, digits: int = 0, unit: str = "") -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    s = f"{x:.{digits}f}".replace(".", ",")
    return f"{s}{unit}"


def pace_from(dist_m: float | None, dur_s: float | None) -> float | None:
    if not dist_m or not dur_s or dist_m <= 0 or dur_s <= 0:
        return None
    return dur_s / (dist_m / 1000.0)


def parse_garmin_time(value: str | None) -> datetime | None:
    """Garmin liefert '2026-09-14 06:12:34' oder '2026-09-14T06:12:34.0'."""
    if not value:
        return None
    v = value.replace("T", " ").split(".")[0]
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_run(type_key: str | None) -> bool:
    return "run" in (type_key or "").lower()


# ----------------------------------------------------------------------------
# Normalisierung: Garmin-Connect-API -> einheitliche Struktur
# ----------------------------------------------------------------------------


def normalize_summary_api(activity: dict[str, Any]) -> dict[str, Any]:
    s = activity.get("summaryDTO") or activity  # get_activity() hat summaryDTO, Listen sind flach
    type_key = (
        (activity.get("activityTypeDTO") or {}).get("typeKey")
        or (activity.get("activityType") or {}).get("typeKey")
    )
    start_local = s.get("startTimeLocal") or activity.get("startTimeLocal")
    start_gmt = s.get("startTimeGMT") or activity.get("startTimeGMT")
    dist = s.get("distance")
    dur = s.get("duration")
    return {
        "activity_id": activity.get("activityId"),
        "name": activity.get("activityName"),
        "type": type_key,
        "start_local": start_local,
        "start_gmt": start_gmt,
        "date": (start_local or start_gmt or "")[:10],
        "distance_m": dist,
        "duration_s": dur,
        "moving_duration_s": s.get("movingDuration"),
        "pace_s_per_km": pace_from(dist, dur),
        "avg_hr": s.get("averageHR"),
        "max_hr": s.get("maxHR"),
        "avg_cadence_spm": s.get("averageRunCadence")
        or s.get("averageRunningCadenceInStepsPerMinute"),
        "elev_gain_m": s.get("elevationGain"),
        "elev_loss_m": s.get("elevationLoss"),
        "calories": s.get("calories"),
        "avg_power_w": s.get("avgPower") or s.get("averagePower"),
        "aerobic_te": s.get("aerobicTrainingEffect") or s.get("trainingEffect"),
        "anaerobic_te": s.get("anaerobicTrainingEffect"),
        "vo2max": s.get("vO2MaxValue"),
        "source": "garmin-connect-api",
    }


def normalize_laps_api(splits: dict[str, Any], activity_start: datetime | None) -> list[dict[str, Any]]:
    laps_raw = splits.get("lapDTOs") or splits.get("laps") or []
    laps: list[dict[str, Any]] = []
    cum = 0.0
    for i, lap in enumerate(laps_raw, start=1):
        dist = lap.get("distance")
        dur = lap.get("duration") or lap.get("elapsedDuration")
        start_dt = parse_garmin_time(lap.get("startTimeGMT"))
        if start_dt and activity_start:
            start_s = (start_dt - activity_start).total_seconds()
        else:
            start_s = cum
        laps.append(
            {
                "nr": i,
                "start_s": round(start_s, 1),
                "end_s": round(start_s + (dur or 0), 1),
                "distance_m": dist,
                "duration_s": dur,
                "moving_duration_s": lap.get("movingDuration"),
                "pace_s_per_km": pace_from(dist, dur),
                "avg_hr": lap.get("averageHR"),
                "max_hr": lap.get("maxHR"),
                "avg_cadence_spm": lap.get("averageRunCadence"),
                "max_cadence_spm": lap.get("maxRunCadence"),
                "elev_gain_m": lap.get("elevationGain"),
                "elev_loss_m": lap.get("elevationLoss"),
                "avg_power_w": lap.get("averagePower") or lap.get("avgPower"),
                "intensity": (lap.get("intensityType") or "").lower() or None,
                "workout_step": lap.get("wktStepIndex"),
            }
        )
        cum += dur or 0
    return laps


# Bekannte Metrik-Schlüssel der Garmin-Details-Zeitreihe -> unsere Spaltennamen
DETAIL_KEYS = {
    "directTimestamp": "timestamp_ms",
    "sumDuration": "t_s",
    "sumElapsedDuration": "elapsed_s",
    "sumMovingDuration": "moving_s",
    "sumDistance": "distance_m",
    "directSpeed": "speed_m_s",
    "directHeartRate": "hr",
    "directElevation": "elev_m",
    "directRunCadence": "cadence_spm",
    "directDoubleCadence": "cadence_spm",
    "directPower": "power_w",
    "directGradeAdjustedSpeed": "gap_speed_m_s",
    "directAirTemperature": "temp_c",
    "directVerticalOscillation": "vert_osc_mm",
    "directGroundContactTime": "gct_ms",
    "directStrideLength": "stride_cm",
}


def normalize_timeseries_api(details: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = details.get("metricDescriptors") or []
    rows_raw = details.get("activityDetailMetrics") or []
    col_by_index: dict[int, str] = {}
    for d in descriptors:
        key = d.get("key")
        idx = d.get("metricsIndex")
        if key in DETAIL_KEYS and idx is not None and DETAIL_KEYS[key] not in col_by_index.values():
            col_by_index[idx] = DETAIL_KEYS[key]
    ts: list[dict[str, Any]] = []
    for r in rows_raw:
        m = r.get("metrics") or []
        row: dict[str, Any] = {}
        for idx, col in col_by_index.items():
            if idx < len(m):
                row[col] = m[idx]
        ts.append(row)
    return _finalize_timeseries(ts)


def _finalize_timeseries(ts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """t_s relativ zum Start, Pace aus Geschwindigkeit, Timestamp als ISO."""
    if not ts:
        return ts
    t0_ms = next((r.get("timestamp_ms") for r in ts if r.get("timestamp_ms") is not None), None)
    for r in ts:
        if r.get("timestamp_ms") is not None:
            r["timestamp"] = datetime.fromtimestamp(r["timestamp_ms"] / 1000, tz=timezone.utc).isoformat()
            if r.get("t_s") is None and t0_ms is not None:
                r["t_s"] = (r["timestamp_ms"] - t0_ms) / 1000.0
        spd = r.get("speed_m_s")
        r["pace_s_per_km"] = (1000.0 / spd) if spd and spd > 0.3 else None
    ts = [r for r in ts if r.get("t_s") is not None]
    ts.sort(key=lambda r: r["t_s"])
    return ts


def normalize_zones_api(zones: Any) -> list[dict[str, Any]]:
    if not isinstance(zones, list):
        return []
    out = []
    for z in zones:
        out.append(
            {
                "zone": z.get("zoneNumber"),
                "seconds": z.get("secsInZone") or 0.0,
                "low_bpm": z.get("zoneLowBoundary"),
            }
        )
    return sorted(out, key=lambda z: z["zone"] or 0)


def normalize_weather_api(w: dict[str, Any] | None) -> dict[str, Any]:
    """Annahme (siehe docs/garmin-tools.md): Garmin liefert temp/apparentTemp in °F, windSpeed in mph."""
    if not w:
        return {}

    def f_to_c(f: float | None) -> float | None:
        return round((f - 32) * 5 / 9, 1) if isinstance(f, (int, float)) else None

    ws = w.get("windSpeed")
    return {
        "temp_c": f_to_c(w.get("temp")),
        "feels_like_c": f_to_c(w.get("apparentTemp")),
        "humidity_pct": w.get("relativeHumidity"),
        "wind_kmh": round(ws * 1.609, 1) if isinstance(ws, (int, float)) else None,
        "wind_dir": w.get("windDirectionCompassPoint"),
        "condition": (w.get("weatherTypeDTO") or {}).get("desc"),
        "raw_temp": w.get("temp"),
        "raw_wind": ws,
    }


# ----------------------------------------------------------------------------
# Fallback: FIT-Datei (manueller Export aus Garmin Connect) -> gleiche Struktur
# ----------------------------------------------------------------------------


def _fit_val(msg, *names, default=None):
    for n in names:
        v = msg.get_value(n)
        if v is not None:
            return v
    return default


def parse_fit(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    from fitparse import FitFile

    data = path.read_bytes()
    if data[:2] == b"PK":  # Garmin-Download kommt als ZIP mit .fit darin
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".fit"))
            data = zf.read(name)
    fit = FitFile(io.BytesIO(data))

    session = None
    laps_raw: list[Any] = []
    records: list[Any] = []
    hr_zone_bounds: list[int] = []
    for msg in fit.get_messages():
        if msg.name == "session":
            session = msg
        elif msg.name == "lap":
            laps_raw.append(msg)
        elif msg.name == "record":
            records.append(msg)
        elif msg.name == "hr_zone":
            hb = msg.get_value("high_bpm")
            if hb is not None:
                hr_zone_bounds.append(int(hb))

    if session is None:
        raise SystemExit("FIT-Datei enthält keine Session-Nachricht.")

    sport = str(_fit_val(session, "sport", default="") or "")
    cad_factor = 2 if "run" in sport.lower() else 1  # FIT: Laufkadenz pro Fuß -> Schritte/min

    start = _fit_val(session, "start_time")
    start_dt = start.replace(tzinfo=timezone.utc) if isinstance(start, datetime) else None
    dist = _fit_val(session, "total_distance")
    dur = _fit_val(session, "total_timer_time")
    avg_cad = _fit_val(session, "avg_running_cadence", "avg_cadence")
    summary = {
        "activity_id": path.stem,
        "name": path.name,
        "type": sport or "running",
        "start_local": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else None,
        "start_gmt": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else None,
        "date": start_dt.strftime("%Y-%m-%d") if start_dt else "unbekannt",
        "distance_m": dist,
        "duration_s": dur,
        "moving_duration_s": None,
        "pace_s_per_km": pace_from(dist, dur),
        "avg_hr": _fit_val(session, "avg_heart_rate"),
        "max_hr": _fit_val(session, "max_heart_rate"),
        "avg_cadence_spm": avg_cad * cad_factor if avg_cad is not None else None,
        "elev_gain_m": _fit_val(session, "total_ascent"),
        "elev_loss_m": _fit_val(session, "total_descent"),
        "calories": _fit_val(session, "total_calories"),
        "avg_power_w": _fit_val(session, "avg_power"),
        "aerobic_te": _fit_val(session, "total_training_effect"),
        "anaerobic_te": _fit_val(session, "total_anaerobic_training_effect"),
        "vo2max": None,
        "source": f"fit:{path.name}",
    }

    laps: list[dict[str, Any]] = []
    cum = 0.0
    for i, lap in enumerate(laps_raw, start=1):
        ldist = _fit_val(lap, "total_distance")
        ldur = _fit_val(lap, "total_timer_time", "total_elapsed_time")
        lstart = _fit_val(lap, "start_time")
        if isinstance(lstart, datetime) and start_dt:
            start_s = (lstart.replace(tzinfo=timezone.utc) - start_dt).total_seconds()
        else:
            start_s = cum
        lcad = _fit_val(lap, "avg_running_cadence", "avg_cadence")
        intensity = _fit_val(lap, "intensity")
        laps.append(
            {
                "nr": i,
                "start_s": round(start_s, 1),
                "end_s": round(start_s + (ldur or 0), 1),
                "distance_m": ldist,
                "duration_s": ldur,
                "moving_duration_s": None,
                "pace_s_per_km": pace_from(ldist, ldur),
                "avg_hr": _fit_val(lap, "avg_heart_rate"),
                "max_hr": _fit_val(lap, "max_heart_rate"),
                "avg_cadence_spm": lcad * cad_factor if lcad is not None else None,
                "max_cadence_spm": None,
                "elev_gain_m": _fit_val(lap, "total_ascent"),
                "elev_loss_m": _fit_val(lap, "total_descent"),
                "avg_power_w": _fit_val(lap, "avg_power"),
                "intensity": str(intensity).lower() if intensity is not None else None,
                "workout_step": _fit_val(lap, "wkt_step_index"),
            }
        )
        cum += ldur or 0

    ts: list[dict[str, Any]] = []
    for r in records:
        t = _fit_val(r, "timestamp")
        if not isinstance(t, datetime):
            continue
        cad = _fit_val(r, "cadence")
        ts.append(
            {
                "timestamp_ms": int(t.replace(tzinfo=timezone.utc).timestamp() * 1000),
                "distance_m": _fit_val(r, "distance"),
                "speed_m_s": _fit_val(r, "enhanced_speed", "speed"),
                "hr": _fit_val(r, "heart_rate"),
                "elev_m": _fit_val(r, "enhanced_altitude", "altitude"),
                "cadence_spm": cad * cad_factor if cad is not None else None,
                "power_w": _fit_val(r, "power"),
            }
        )
    ts = _finalize_timeseries(ts)

    zones: list[dict[str, Any]] = []
    tiz = _fit_val(session, "time_in_hr_zone")
    if isinstance(tiz, (list, tuple)):
        # Garmin schreibt meist 6 Werte (Index 0 = unterhalb Zone 1); bei 5 Werten sind es Zonen 1–5
        offset = 0 if len(tiz) > 5 else 1
        for i, secs in enumerate(tiz):
            zone = i + offset
            low = hr_zone_bounds[zone - 2] + 1 if 2 <= zone <= len(hr_zone_bounds) + 1 else (0 if zone == 1 else None)
            zones.append({"zone": zone, "seconds": float(secs or 0), "low_bpm": low})
    return summary, laps, ts, zones


# ----------------------------------------------------------------------------
# Analyse: Lap-Typen, HF-Anstieg, Intervall-Kennzahlen, Erholung, Zonen
# ----------------------------------------------------------------------------


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def _slope(ys: list[float]) -> float | None:
    """Steigung einer Ausgleichsgeraden über den Index 1..n (Einheit pro Intervall)."""
    ys = [y for y in ys if y is not None]
    n = len(ys)
    if n < 2:
        return None
    xs = list(range(n))
    xm, ym = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - xm) ** 2 for x in xs)
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / den if den else None


def _ts_window(ts: list[dict[str, Any]], t_from: float, t_to: float) -> list[dict[str, Any]]:
    return [r for r in ts if t_from <= r["t_s"] < t_to]


def classify_laps(laps: list[dict[str, Any]], overall_pace: float | None, work_factor: float, min_lap_km: float) -> str:
    """Setzt lap['type'] in {'belastung','erholung','aufwaermen','auslaufen','normal'}.

    Rückgabe: Quelle der Klassifikation ('workout' = Garmin-Intensitätstyp, 'pace' = Heuristik).
    """
    intensities = {lap.get("intensity") for lap in laps if lap.get("intensity")}
    use_workout = bool(intensities & {"active", "interval", "rest", "recovery", "warmup", "cooldown"})
    if use_workout:
        mapping = {
            "active": "belastung", "interval": "belastung",
            "rest": "erholung", "recovery": "erholung",
            "warmup": "aufwaermen", "cooldown": "auslaufen",
        }
        for lap in laps:
            lap["type"] = mapping.get(lap.get("intensity") or "", "normal")
        return "workout"

    # Heuristik: Laps nach Pace in eine schnelle und eine langsame Gruppe teilen (größte Lücke in der
    # sortierten Pace-Liste). Belastung = schnelle Gruppe, wenn sie deutlich (Faktor work_factor)
    # schneller als die langsame Gruppe UND schneller als der Gesamt-Ø ist. Langsame Laps vor dem
    # ersten Intervall = Aufwärmen, danach = Auslaufen, dazwischen = Erholung.
    for lap in laps:
        lap["type"] = "normal"
    cands = [lap for lap in laps if lap.get("pace_s_per_km") and (lap.get("distance_m") or 0) >= min_lap_km * 1000]
    if len(cands) < 3:
        return "pace"
    ordered = sorted(cands, key=lambda lap: lap["pace_s_per_km"])
    paces = [lap["pace_s_per_km"] for lap in ordered]
    gaps = [(paces[i + 1] / paces[i], i) for i in range(len(paces) - 1)]
    ratio, split = max(gaps)
    fast, slow = ordered[: split + 1], ordered[split + 1 :]
    if not fast or not slow:
        return "pace"
    fast_mean = statistics.fmean(p["pace_s_per_km"] for p in fast)
    slow_mean = statistics.fmean(p["pace_s_per_km"] for p in slow)
    ref = overall_pace or statistics.median(paces)
    is_interval = (
        len(fast) >= 2
        and slow_mean / fast_mean >= 1 / work_factor
        and fast_mean <= ref * work_factor
    )
    if not is_interval:
        return "pace"
    fast_ids = {id(lap) for lap in fast}
    for lap in laps:
        if id(lap) in fast_ids:
            lap["type"] = "belastung"
    idx_work = [i for i, lap in enumerate(laps) if lap["type"] == "belastung"]
    first_w, last_w = idx_work[0], idx_work[-1]
    for i, lap in enumerate(laps):
        if lap["type"] == "belastung":
            continue
        lap["type"] = "aufwaermen" if i < first_w else "auslaufen" if i > last_w else "erholung"
    return "pace"


def analyze(
    summary: dict[str, Any],
    laps: list[dict[str, Any]],
    ts: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    weather: dict[str, Any],
    *,
    recovery_hr: int,
    work_factor: float,
    min_lap_km: float,
    edge_window_s: float = 5.0,
) -> dict[str, Any]:
    source = classify_laps(laps, summary.get("pace_s_per_km"), work_factor, min_lap_km)

    # HF-Anfang/-Ende je Lap aus der Zeitreihe (Mittel der ersten/letzten 5 s)
    has_ts = bool(ts)
    for lap in laps:
        a, b = lap["start_s"], lap["end_s"]
        win = _ts_window(ts, a, b) if has_ts else []
        hr_start = _mean([r.get("hr") for r in _ts_window(win, a, a + edge_window_s)]) if win else None
        hr_end = _mean([r.get("hr") for r in _ts_window(win, max(a, b - edge_window_s), b)]) if win else None
        if hr_start is None and win:
            hr_start = next((r.get("hr") for r in win if r.get("hr") is not None), None)
        if hr_end is None and win:
            hr_end = next((r.get("hr") for r in reversed(win) if r.get("hr") is not None), None)
        lap["hr_start"] = round(hr_start) if hr_start is not None else None
        lap["hr_end"] = round(hr_end) if hr_end is not None else None
        lap["hr_rise"] = (lap["hr_end"] - lap["hr_start"]) if hr_start is not None and hr_end is not None else None
        if lap.get("avg_hr") is None and win:
            lap["avg_hr"] = round(_mean([r.get("hr") for r in win]) or 0) or None
        if lap.get("max_hr") is None and win:
            hrs = [r["hr"] for r in win if r.get("hr") is not None]
            lap["max_hr"] = max(hrs) if hrs else None
        if lap.get("avg_cadence_spm") is None and win:
            lap["avg_cadence_spm"] = _mean([r.get("cadence_spm") for r in win])
        lap["pace_str"] = fmt_pace(lap.get("pace_s_per_km"))
        lap["duration_str"] = fmt_dur(lap.get("duration_s"))

    work = [lap for lap in laps if lap["type"] == "belastung"]
    rest = [lap for lap in laps if lap["type"] == "erholung"]
    is_interval = len(work) >= 2

    # Erholungszeit nach jedem Belastungs-Lap: bis HF < Schwelle (Suche bis zum nächsten Belastungs-Lap)
    for idx, lap in enumerate(work):
        lap["recovery_to_threshold_s"] = None
        if not has_ts:
            continue
        t_end = lap["end_s"]
        t_limit = work[idx + 1]["start_s"] if idx + 1 < len(work) else (ts[-1]["t_s"] + 1)
        for r in ts:
            if r["t_s"] < t_end:
                continue
            if r["t_s"] > t_limit:
                break
            if r.get("hr") is not None and r["hr"] < recovery_hr:
                lap["recovery_to_threshold_s"] = round(r["t_s"] - t_end)
                break

    interval_stats: dict[str, Any] = {"count": len(work)}
    if work:
        tot_d = sum(lap.get("distance_m") or 0 for lap in work)
        tot_t = sum(lap.get("duration_s") or 0 for lap in work)
        paces = [lap["pace_s_per_km"] for lap in work if lap.get("pace_s_per_km")]
        hrs = [lap["avg_hr"] for lap in work if lap.get("avg_hr") is not None]
        durs = [lap.get("duration_s") or 0 for lap in work if lap.get("avg_hr") is not None]
        hr_weighted = (sum(h * d for h, d in zip(hrs, durs)) / sum(durs)) if hrs and sum(durs) else _mean(hrs)
        pace_slope = _slope(paces)
        hr_slope = _slope(hrs)
        rec = [lap["recovery_to_threshold_s"] for lap in work if lap.get("recovery_to_threshold_s") is not None]
        interval_stats.update(
            {
                "total_distance_m": tot_d,
                "total_duration_s": tot_t,
                "avg_pace_s_per_km": pace_from(tot_d, tot_t),
                "avg_pace_str": fmt_pace(pace_from(tot_d, tot_t)),
                "avg_hr": round(hr_weighted) if hr_weighted is not None else None,
                "max_hr": max((lap["max_hr"] for lap in work if lap.get("max_hr") is not None), default=None),
                "pace_fastest_s_per_km": min(paces) if paces else None,
                "pace_slowest_s_per_km": max(paces) if paces else None,
                "pace_stdev_s_per_km": round(statistics.pstdev(paces), 1) if len(paces) > 1 else 0.0,
                "pace_range_s_per_km": round(max(paces) - min(paces), 1) if paces else None,
                "pace_trend_s_per_km_per_interval": round(pace_slope, 2) if pace_slope is not None else None,
                "hr_trend_bpm_per_interval": round(hr_slope, 2) if hr_slope is not None else None,
                "hr_first_vs_last_bpm": (hrs[-1] - hrs[0]) if len(hrs) >= 2 else None,
                "pace_first_vs_last_s_per_km": round(paces[-1] - paces[0], 1) if len(paces) >= 2 else None,
                "avg_hr_rise_in_lap": round(_mean([lap["hr_rise"] for lap in work if lap.get("hr_rise") is not None]) or 0, 1)
                if any(lap.get("hr_rise") is not None for lap in work)
                else None,
                "recovery_hr_threshold": recovery_hr,
                "recovery_to_threshold_s_avg": round(statistics.fmean(rec)) if rec else None,
                "recovery_to_threshold_s_list": [lap.get("recovery_to_threshold_s") for lap in work],
                "recovery_lap_avg_hr": round(_mean([lap["avg_hr"] for lap in rest if lap.get("avg_hr") is not None]) or 0) or None,
            }
        )
        interval_stats["trend_text"] = _trend_text(pace_slope, hr_slope)

    total_secs = sum(z["seconds"] for z in zones) or (summary.get("duration_s") or 0)
    zones_out = [
        {
            **z,
            "minutes": round(z["seconds"] / 60, 1),
            "percent": round(100 * z["seconds"] / total_secs, 1) if total_secs else None,
        }
        for z in zones
    ]

    return {
        "summary": {
            **summary,
            "pace_str": fmt_pace(summary.get("pace_s_per_km")),
            "duration_str": fmt_dur(summary.get("duration_s")),
        },
        "weather": weather,
        "laps": laps,
        "lap_classification_source": source,
        "is_interval_session": is_interval,
        "intervals": interval_stats,
        "hr_zones": zones_out,
        "timeseries_points": len(ts),
        "timeseries_columns": sorted({k for r in ts for k in r.keys()}),
        "notes": _data_notes(ts, zones, weather, laps),
    }


def _trend_text(pace_slope: float | None, hr_slope: float | None) -> str:
    parts = []
    ps = fmt_num(pace_slope, 1)
    hs = fmt_num(hr_slope, 1)
    if pace_slope is None:
        parts.append("Zu wenige Intervalle für einen Trend.")
    elif pace_slope > 3:
        parts.append(f"Pace wird über die Intervalle langsamer (≈ +{ps} s/km je Intervall).")
    elif pace_slope < -3:
        parts.append(f"Pace wird über die Intervalle schneller (≈ {ps} s/km je Intervall).")
    else:
        parts.append("Pace bleibt über die Intervalle stabil.")
    if hr_slope is not None:
        if hr_slope > 1 and pace_slope is not None and abs(pace_slope) <= 3:
            parts.append(f"HF steigt bei gleicher Pace (≈ +{hs} bpm je Intervall) – Hinweis auf Ermüdung/Drift.")
        elif hr_slope > 1:
            parts.append(f"HF steigt (≈ +{hs} bpm je Intervall).")
        elif hr_slope < -1:
            parts.append(f"HF sinkt (≈ {hs} bpm je Intervall).")
        else:
            parts.append("HF bleibt über die Intervalle stabil.")
    return " ".join(parts)


def fmt_datetime(value: str | None) -> str:
    dt = parse_garmin_time(value)
    return dt.strftime("%d.%m.%Y %H:%M") if dt else (value or "–")


def _data_notes(ts, zones, weather, laps) -> list[str]:
    notes = []
    if not ts:
        notes.append("Keine Zeitreihe verfügbar: HF-Anfang/-Ende je Lap und Erholungszeit konnten nicht berechnet werden.")
    elif not any(r.get("hr") is not None for r in ts):
        notes.append("Zeitreihe ohne Herzfrequenz.")
    if not zones:
        notes.append("Keine HF-Zonen-Daten verfügbar.")
    if not weather:
        notes.append("Keine Wetterdaten verfügbar.")
    if not laps:
        notes.append("Keine Laps verfügbar.")
    return notes


# ----------------------------------------------------------------------------
# Ausgabe: Dateien + Markdown-Bericht
# ----------------------------------------------------------------------------

LAP_CSV_COLS = [
    "nr", "type", "start_s", "end_s", "distance_m", "duration_s", "pace_s_per_km", "pace_str",
    "avg_hr", "max_hr", "hr_start", "hr_end", "hr_rise", "avg_cadence_spm", "elev_gain_m",
    "elev_loss_m", "avg_power_w", "intensity", "recovery_to_threshold_s",
]
TS_CSV_COLS = [
    "t_s", "timestamp", "distance_m", "speed_m_s", "pace_s_per_km", "hr", "elev_m",
    "cadence_spm", "power_w", "gap_speed_m_s", "temp_c",
]


def _write_csv(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def render_markdown(a: dict[str, Any]) -> str:
    s, w, iv = a["summary"], a.get("weather") or {}, a.get("intervals") or {}
    lines: list[str] = []
    lines.append(f"# Laufanalyse {s.get('date')} – {s.get('name') or 'Lauf'} (ID {s.get('activity_id')})")
    lines.append("")
    lines.append("## 1. Überblick")
    lines.append("")
    lines.append("| Datum | Distanz | Dauer | Ø-Pace | Ø-HF | Max-HF | Höhenmeter | Kadenz |")
    lines.append("|---|---|---|---|---|---|---|---|")
    lines.append(
        f"| {fmt_datetime(s.get('start_local')) if s.get('start_local') else s.get('date')} | {fmt_km(s.get('distance_m'))} km | {s['duration_str']} "
        f"| {s['pace_str']} min/km | {fmt_num(s.get('avg_hr'))} | {fmt_num(s.get('max_hr'))} "
        f"| ↑{fmt_num(s.get('elev_gain_m'))} m / ↓{fmt_num(s.get('elev_loss_m'))} m | {fmt_num(s.get('avg_cadence_spm'))} spm |"
    )
    if w:
        lines.append("")
        lines.append(
            f"Wetter: {w.get('condition') or '–'}, {fmt_num(w.get('temp_c'), 1)} °C "
            f"(gefühlt {fmt_num(w.get('feels_like_c'), 1)} °C), Luftfeuchte {fmt_num(w.get('humidity_pct'))} %, "
            f"Wind {fmt_num(w.get('wind_kmh'), 1)} km/h {w.get('wind_dir') or ''}"
        )
    else:
        lines.append("")
        lines.append("Wetter: keine Daten.")

    lines.append("")
    lines.append(f"## 2. Lap-Tabelle (Klassifikation: {'Garmin-Workout' if a['lap_classification_source'] == 'workout' else 'Pace-Heuristik'})")
    lines.append("")
    lines.append("| Nr | Typ | Distanz | Zeit | Pace | Ø-HF | Max-HF | HF-Anstieg | Kadenz |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    type_label = {"belastung": "**Belastung**", "erholung": "Erholung", "aufwaermen": "Aufwärmen", "auslaufen": "Auslaufen", "normal": "–"}
    for lap in a["laps"]:
        rise = lap.get("hr_rise")
        rise_s = "–" if rise is None else f"{rise:+d} ({lap['hr_start']}→{lap['hr_end']})"
        lines.append(
            f"| {lap['nr']} | {type_label.get(lap['type'], lap['type'])} | {fmt_km(lap.get('distance_m'))} km | {lap['duration_str']} "
            f"| {lap['pace_str']} | {fmt_num(lap.get('avg_hr'))} | {fmt_num(lap.get('max_hr'))} | {rise_s} | {fmt_num(lap.get('avg_cadence_spm'))} |"
        )

    lines.append("")
    lines.append("## 3. Intervall-Auswertung (nur Belastungs-Laps)")
    lines.append("")
    if iv.get("count", 0) == 0:
        lines.append("Keine Belastungs-Intervalle erkannt (Dauerlauf oder gleichmäßiges Tempo).")
    else:
        lines.append(f"- Anzahl: {iv['count']} × Ø {fmt_km(iv['total_distance_m'] / iv['count'])} km")
        lines.append(f"- Ø-Pace: {iv['avg_pace_str']} min/km (schnellstes {fmt_pace(iv['pace_fastest_s_per_km'])}, langsamstes {fmt_pace(iv['pace_slowest_s_per_km'])})")
        lines.append(f"- Streuung der Pace: ±{fmt_num(iv['pace_stdev_s_per_km'], 1)} s/km (Spanne {fmt_num(iv['pace_range_s_per_km'], 1)} s/km)")
        lines.append(f"- Ø-HF: {fmt_num(iv['avg_hr'])} bpm, Max-HF: {fmt_num(iv['max_hr'])} bpm, Ø-HF-Anstieg innerhalb der Intervalle: {fmt_num(iv['avg_hr_rise_in_lap'], 1)} bpm")
        lines.append(f"- Trend: {iv['trend_text']}")
        rec = iv.get("recovery_to_threshold_s_avg")
        rec_list = ", ".join("–" if r is None else fmt_dur(r) for r in iv.get("recovery_to_threshold_s_list", []))
        lines.append(
            f"- Erholung bis HF < {iv['recovery_hr_threshold']} bpm: "
            + (f"Ø {fmt_dur(rec)} (je Intervall: {rec_list})" if rec is not None else f"Schwelle nicht erreicht oder keine Zeitreihe (je Intervall: {rec_list})")
        )
        if iv.get("recovery_lap_avg_hr"):
            lines.append(f"- Ø-HF in den Erholungs-Laps: {iv['recovery_lap_avg_hr']} bpm")

    lines.append("")
    lines.append("## 4. HF-Zonen")
    lines.append("")
    if a["hr_zones"]:
        lines.append("| Zone | ab bpm | Minuten | Anteil |")
        lines.append("|---|---|---|---|")
        for z in a["hr_zones"]:
            lines.append(f"| {z['zone']} | {fmt_num(z.get('low_bpm'))} | {fmt_num(z['minutes'], 1)} | {fmt_num(z.get('percent'), 1)} % |")
    else:
        lines.append("Keine HF-Zonen-Daten verfügbar.")

    if a.get("notes"):
        lines.append("")
        lines.append("## Hinweise zur Datenlage")
        lines.append("")
        for n in a["notes"]:
            lines.append(f"- {n}")
    lines.append("")
    lines.append(f"_Quelle: {s.get('source')}, Zeitreihe: {a['timeseries_points']} Punkte._")
    return "\n".join(lines) + "\n"


def write_outputs(out_dir: Path, analysis: dict[str, Any], ts: list[dict[str, Any]], raw: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    for name, obj in raw.items():
        if obj is not None:
            _write_json(out_dir / "raw" / f"{name}.json", obj)
    _write_json(out_dir / "analysis.json", analysis)
    _write_json(out_dir / "laps.json", analysis["laps"])
    _write_csv(out_dir / "laps.csv", analysis["laps"], LAP_CSV_COLS)
    _write_csv(out_dir / "timeseries.csv", ts, TS_CSV_COLS)
    (out_dir / "summary.md").write_text(render_markdown(analysis), encoding="utf-8")


# ----------------------------------------------------------------------------
# Garmin-API-Zugriff
# ----------------------------------------------------------------------------


def _safe(fn, *args, label: str = "", **kwargs):
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{label or getattr(fn, '__name__', 'call')}: {exc}"


def activity_row(act: dict[str, Any]) -> str:
    n = normalize_summary_api(act)
    return (
        f"{n['start_local'] or n['date']:<20} {n['type'] or '':<18} {fmt_km(n['distance_m']):>7} km "
        f"{fmt_dur(n['duration_s']):>8}  {fmt_pace(n['pace_s_per_km']):>5} min/km  Ø-HF {fmt_num(n['avg_hr']):>3}  "
        f"ID {n['activity_id']}  {n['name'] or ''}"
    )


def print_activity_list(client, limit: int = 5) -> None:
    acts = client.get_activities(0, limit) or []
    print(f"Letzte {len(acts)} Aktivitäten:")
    for act in acts:
        print("  " + activity_row(act))
    runs = [a for a in acts if is_run((a.get("activityType") or {}).get("typeKey"))]
    if not runs:
        more = client.get_activities(0, 30) or []
        runs = [a for a in more if is_run((a.get("activityType") or {}).get("typeKey"))]
    if runs:
        n = normalize_summary_api(runs[0])
        print()
        print("Letzter Lauf:")
        print(f"  Datum:    {n['start_local']}")
        print(f"  Distanz:  {fmt_km(n['distance_m'])} km")
        print(f"  Dauer:    {fmt_dur(n['duration_s'])}")
        print(f"  Ø-Pace:   {fmt_pace(n['pace_s_per_km'])} min/km")
        print(f"  Ø-HF:     {fmt_num(n['avg_hr'])} bpm (Max {fmt_num(n['max_hr'])})")
        print(f"  ID:       {n['activity_id']}")
    else:
        print("Kein Lauf unter den letzten 30 Aktivitäten gefunden.")


def resolve_activity_id(client, *, activity_id: int | None, date: str | None) -> int:
    if activity_id:
        return int(activity_id)
    if date:
        acts = client.get_activities_by_date(date, date, "running") or []
        acts = [a for a in acts if is_run((a.get("activityType") or {}).get("typeKey"))]
        if not acts:
            raise SystemExit(f"Kein Lauf am {date} gefunden.")
        if len(acts) > 1:
            print(f"Mehrere Läufe am {date}, nehme den ersten:", file=sys.stderr)
            for a in acts:
                print("  " + activity_row(a), file=sys.stderr)
        return int(acts[0]["activityId"])
    for start in (0, 20, 40):
        acts = client.get_activities(start, 20) or []
        if not acts:
            break
        for a in acts:
            if is_run((a.get("activityType") or {}).get("typeKey")):
                return int(a["activityId"])
    raise SystemExit("Kein Lauf unter den letzten 60 Aktivitäten gefunden.")


def fetch_from_api(client, activity_id: int, *, max_chart: int) -> tuple[dict, list, list, list, dict, dict, list[str]]:
    errors: list[str] = []
    activity, err = _safe(client.get_activity, activity_id, label="get_activity")
    if err:
        raise SystemExit(f"Aktivität {activity_id} konnte nicht geladen werden: {err}")
    summary = normalize_summary_api(activity)
    start_gmt = parse_garmin_time(summary.get("start_gmt"))

    splits, err = _safe(client.get_activity_splits, activity_id, label="get_activity_splits")
    errors += [err] if err else []
    typed, err = _safe(client.get_activity_typed_splits, activity_id, label="get_activity_typed_splits")
    errors += [err] if err else []
    details, err = _safe(client.get_activity_details, activity_id, maxchart=max_chart, maxpoly=1, label="get_activity_details")
    errors += [err] if err else []
    zones, err = _safe(client.get_activity_hr_in_timezones, activity_id, label="get_activity_hr_in_timezones")
    errors += [err] if err else []
    weather, err = _safe(client.get_activity_weather, activity_id, label="get_activity_weather")
    errors += [err] if err else []

    laps = normalize_laps_api(splits or {}, start_gmt)
    ts = normalize_timeseries_api(details or {})
    if ts and start_gmt is None and laps:
        pass  # Laps sind dann kumulativ ab 0 s ausgerichtet
    raw = {"activity": activity, "splits": splits, "typed_splits": typed, "details": details, "hr_zones": zones, "weather": weather}
    return summary, laps, ts, normalize_zones_api(zones), normalize_weather_api(weather), raw, errors


def list_exported(base: Path) -> None:
    if not base.exists():
        print(f"Kein Datenordner: {base}")
        return
    rows = []
    for d in sorted(base.iterdir()):
        f = d / "analysis.json"
        if f.is_file():
            try:
                a = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            s, iv = a["summary"], a.get("intervals") or {}
            rows.append(
                f"{d.name:<26} {fmt_km(s.get('distance_m')):>7} km {s.get('duration_str'):>8}  {s.get('pace_str'):>5} min/km  "
                f"Ø-HF {fmt_num(s.get('avg_hr')):>3}  Intervalle: {iv.get('count', 0)}"
                + (f" × Ø {fmt_pace(iv.get('avg_pace_s_per_km'))}" if iv.get('count') else "")
            )
    print(f"Gesicherte Läufe in {base}:")
    print("\n".join("  " + r for r in rows) if rows else "  (keine)")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--last", action="store_true", help="letzter Lauf (Standard)")
    sel.add_argument("--date", help="Lauf an diesem Datum (YYYY-MM-DD)")
    sel.add_argument("--id", type=int, help="Garmin-Aktivitäts-ID")
    sel.add_argument("--fit", type=Path, help="FIT-Datei (oder ZIP mit FIT) statt API")
    sel.add_argument("--list", type=int, metavar="N", help="nur die letzten N Aktivitäten anzeigen")
    sel.add_argument("--exported", action="store_true", help="bereits gesicherte Läufe auflisten")
    ap.add_argument("--out", type=Path, default=None, help="Basisordner (Standard: $LAUFANALYSE_DATA_DIR oder ./data/garmin)")
    ap.add_argument("--recovery-hr", type=int, default=int(os.environ.get("LAUFANALYSE_RECOVERY_HR", "140")),
                    help="Schwelle für Erholungszeit in bpm (Standard 140 bzw. $LAUFANALYSE_RECOVERY_HR)")
    ap.add_argument("--work-factor", type=float, default=0.93,
                    help="Belastung, wenn Pace <= Faktor × Gesamt-Ø-Pace (Standard 0.93 = mind. 7 %% schneller)")
    ap.add_argument("--min-lap-km", type=float, default=0.2, help="kürzere Laps werden nicht klassifiziert")
    ap.add_argument("--max-chart", type=int, default=100000, help="max. Punkte der Zeitreihe von der API")
    ap.add_argument("--print", action="store_true", help="summary.md nach der Sicherung ausgeben")
    ap.add_argument("--json", action="store_true", help="analysis.json (kompakt) nach stdout ausgeben")
    ap.add_argument("--no-write", action="store_true", help="nichts speichern (nur Ausgabe)")
    args = ap.parse_args()

    base = args.out or Path(os.environ.get("LAUFANALYSE_DATA_DIR") or "data/garmin")

    if args.exported:
        list_exported(base)
        return 0

    raw: dict[str, Any] = {}
    errors: list[str] = []
    if args.fit:
        if not args.fit.is_file():
            raise SystemExit(f"FIT-Datei nicht gefunden: {args.fit}")
        summary, laps, ts, zones = parse_fit(args.fit)
        weather: dict[str, Any] = {}
    else:
        import garmin_auth

        client = garmin_auth.connect(interactive=sys.stdin.isatty())
        if args.list:
            print_activity_list(client, limit=args.list)
            return 0
        activity_id = resolve_activity_id(client, activity_id=args.id, date=args.date)
        summary, laps, ts, zones, weather, raw, errors = fetch_from_api(client, activity_id, max_chart=args.max_chart)

    analysis = analyze(
        summary, laps, ts, zones, weather,
        recovery_hr=args.recovery_hr, work_factor=args.work_factor, min_lap_km=args.min_lap_km,
    )
    if errors:
        analysis["notes"] = [f"API-Fehler: {e}" for e in errors] + analysis["notes"]

    out_dir = base / f"{summary.get('date')}_{summary.get('activity_id')}"
    if not args.no_write:
        write_outputs(out_dir, analysis, ts, raw)
        analysis["output_dir"] = str(out_dir.resolve())
        print(f"Gesichert in: {out_dir.resolve()}", file=sys.stderr)
        if errors:
            for e in errors:
                print(f"Hinweis: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(analysis, ensure_ascii=False, default=str))
    if args.print or not args.json:
        print(render_markdown(analysis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
