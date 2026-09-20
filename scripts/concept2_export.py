# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""Ergometer-Einheiten (Rudern, Ski Erg, Bike Erg) aus dem Concept2 Logbook sichern und auswerten.

Quelle: Concept2 Logbook API (Daten von ErgData/PM5). Speichert Zusammenfassung, Splits/Intervalle und
Schlagdaten als CSV/JSON in
    <out>/<YYYY-MM-DD>_<result-id>/
und berechnet daraus analysis.json + summary.md (deutsch, Pace als m:ss.z /500 m, Zeiten mm:ss).

Beispiele:
    uv run scripts/concept2_export.py                      # letzte Einheit
    uv run scripts/concept2_export.py --type skierg        # letzte Ski-Erg-Einheit
    uv run scripts/concept2_export.py --date 2026-09-02    # Einheit(en) an diesem Datum
    uv run scripts/concept2_export.py --id 123456789       # Result-ID
    uv run scripts/concept2_export.py --rpe 7              # RPE in Bericht und Coach-Text übernehmen
    uv run scripts/concept2_export.py --list 10            # letzte 10 Einheiten anzeigen
    uv run scripts/concept2_export.py --exported           # bereits gesicherte Einheiten auflisten

Ausgabe-Ordner: --out, sonst $CONCEPT2_DATA_DIR, sonst ./data/concept2

Einheiten der API (bestätigt am Client pyconcept2 0.1.0): Zeiten in Zehntelsekunden, Distanzen in m,
Pace in Zehntelsekunden je 500 m, Schlagdaten t (Zehntelsekunden), d (Dezimeter), p (Pace), spm, hr.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import concept2_auth as c2  # noqa: E402

TYPE_DE = {
    "rower": "Rudern (RowErg)", "skierg": "Ski Erg", "bike": "Bike Erg", "dynamic": "Dynamic Indoor Rower",
    "slides": "Rudern auf Slides", "paddle": "Paddle", "water": "Rudern auf dem Wasser", "snow": "Ski (Schnee)",
    "rollerski": "Rollerski", "multierg": "MultiErg",
}
PACE_PER_M = {"bike": 1000}  # Bike Erg: Pace je 1000 m, sonst je 500 m
SEG_CSV_COLS = ["nr", "kind", "type", "start_s", "time_s", "distance_m", "pace_s", "pace_str", "watts", "spm", "hr_avg", "hr_min", "hr_max", "hr_end", "hr_start_strokes", "hr_end_strokes", "hr_rise", "rest_time_s", "rest_distance_m", "calories"]
STROKE_CSV_COLS = ["t_s", "distance_m", "pace_s", "spm", "hr", "segment"]


# ----------------------------------------------------------------------------
# Formatierung (deutsch)
# ----------------------------------------------------------------------------


def tenths_to_s(v: Any) -> float | None:
    try:
        return None if v is None else float(v) / 10.0
    except (TypeError, ValueError):
        return None


def fmt_time(sec: float | None, tenths: bool = True) -> str:
    """mm:ss.z (ab 1 h h:mm:ss.z)."""
    if sec is None or not math.isfinite(sec):
        return "–"
    total_tenths = int(round(sec * 10))
    s_total, t = divmod(total_tenths, 10)
    h, rest = divmod(s_total, 3600)
    m, s = divmod(rest, 60)
    frac = f".{t}" if tenths else ""
    return f"{h}:{m:02d}:{s:02d}{frac}" if h else f"{m}:{s:02d}{frac}"


def fmt_pace(sec: float | None) -> str:
    return fmt_time(sec) if sec else "–"


def fmt_num(x: float | None, digits: int = 0, unit: str = "") -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    return f"{x:.{digits}f}".replace(".", ",") + unit


def pace_unit_m(type_key: str | None) -> int:
    return PACE_PER_M.get(type_key or "", 500)


def pace_from(dist_m: float | None, time_s: float | None, unit_m: int = 500) -> float | None:
    if not dist_m or not time_s or dist_m <= 0 or time_s <= 0:
        return None
    return time_s / (dist_m / unit_m)


def watts_from_pace(pace_s_per_500m: float | None) -> float | None:
    """Concept2-Formel: Watt = 2,8 / (Pace je Meter)^3 – nur RowErg/SkiErg."""
    if not pace_s_per_500m or pace_s_per_500m <= 0:
        return None
    return 2.8 / (pace_s_per_500m / 500.0) ** 3


# ----------------------------------------------------------------------------
# Normalisierung
# ----------------------------------------------------------------------------


def _hr(d: dict[str, Any] | None) -> dict[str, int | None]:
    d = d or {}

    def g(k):
        v = d.get(k)
        return int(v) if isinstance(v, (int, float)) and v > 0 else None

    return {"avg": g("average"), "min": g("min"), "max": g("max"), "end": g("ending"), "recovery": g("recovery")}


def normalize_summary(r: dict[str, Any]) -> dict[str, Any]:
    t = r.get("type")
    unit = pace_unit_m(t)
    dist = float(r.get("distance") or 0)
    time_s = tenths_to_s(r.get("time")) or 0.0
    rest_s = tenths_to_s(r.get("rest_time")) or 0.0
    pace = pace_from(dist, time_s, unit)
    hr = _hr(r.get("heart_rate"))
    date_local = str(r.get("date") or "")
    return {
        "result_id": r.get("id"),
        "date": date_local[:10],
        "start_local": date_local,
        "timezone": r.get("timezone"),
        "type": t,
        "type_de": TYPE_DE.get(t or "", t or "–"),
        "workout_type": r.get("workout_type"),
        "source": r.get("source"),
        "distance_m": dist,
        "time_s": time_s,
        "time_str": fmt_time(time_s),
        "rest_time_s": rest_s,
        "rest_distance_m": float(r.get("rest_distance") or 0),
        "pace_unit_m": unit,
        "pace_s": pace,
        "pace_str": fmt_pace(pace),
        "watts": watts_from_pace(pace) if unit == 500 else None,
        "spm": r.get("stroke_rate"),
        "stroke_count": r.get("stroke_count"),
        "calories": r.get("calories_total"),
        "drag_factor": r.get("drag_factor"),
        "hr_avg": hr["avg"], "hr_min": hr["min"], "hr_max": hr["max"], "hr_end": hr["end"], "hr_recovery": hr["recovery"],
        "has_stroke_data": bool(r.get("stroke_data")),
        "comments": r.get("comments"),
        "verified": r.get("verified"),
    }


def normalize_segments(r: dict[str, Any], type_key: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splits (gleichmäßige Abschnitte) und Intervalle (mit Pausen) als normalisierte Listen mit Startzeit."""
    unit = pace_unit_m(type_key)
    w = r.get("workout") or {}

    def conv(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        out, start = [], 0.0
        for i, it in enumerate(items or [], 1):
            time_s = tenths_to_s(it.get("time")) or 0.0
            dist = float(it.get("distance") or 0)
            rest_s = tenths_to_s(it.get("rest_time")) or 0.0
            hr = _hr(it.get("heart_rate"))
            p = pace_from(dist, time_s, unit)
            out.append({
                "nr": i, "kind": kind, "type": it.get("type"), "start_s": round(start, 1), "end_s": round(start + time_s, 1),
                "time_s": time_s, "time_str": fmt_time(time_s), "distance_m": dist,
                "pace_s": p, "pace_str": fmt_pace(p), "watts": watts_from_pace(p) if unit == 500 else None,
                "spm": it.get("stroke_rate"), "hr_avg": hr["avg"], "hr_min": hr["min"], "hr_max": hr["max"], "hr_end": hr["end"],
                "rest_time_s": rest_s, "rest_distance_m": float(it.get("rest_distance") or 0), "calories": it.get("calories_total"),
                "machine": it.get("machine"),
            })
            start += time_s + rest_s
        return out

    splits, intervals = conv(w.get("splits") or [], "split"), conv(w.get("intervals") or [], "intervall")

    # Pausen fehlen je Intervall, stehen aber als Gesamtwert im Result (Beispiel im Concept2 API-Validator):
    # bei festen Intervallprogrammen (FixedTimeInterval, FixedDistanceInterval, FixedCalorieInterval) ist die
    # Pause je Intervall per Definition gleich lang → aus dem Gesamtwert verteilen; sonst nur vermerken.
    total_rest = tenths_to_s(r.get("rest_time")) or 0.0
    if intervals and total_rest > 0 and not any(i["rest_time_s"] for i in intervals):
        wt = str(r.get("workout_type") or "")
        if wt.startswith("Fixed") and len(intervals) > 0:
            per = round(total_rest / len(intervals), 1)
            start = 0.0
            for i in intervals:
                i["rest_time_s"] = per
                i["rest_source"] = "aus Gesamtpause verteilt"
                i["start_s"], i["end_s"] = round(start, 1), round(start + i["time_s"], 1)
                start += i["time_s"] + per
        else:
            for i in intervals:
                i["rest_source"] = "unbekannt (nur Gesamtpause im Result)"
    return splits, intervals


def normalize_strokes(strokes: list[dict[str, Any]], rests_s: list[float] | None = None) -> list[dict[str, Any]]:
    """Schlagdaten in Sekunden/Meter; t und d setzen sich je Intervall zurück → kumulieren (Segmentnummer mitführen).
    rests_s: Pausen je Intervall (aus den Intervall-Daten), damit t_s der echten verstrichenen Zeit entspricht."""
    rows, t_off, d_off, prev_t, prev_d, seg = [], 0.0, 0.0, 0.0, 0.0, 1
    for s in strokes:
        t_raw, d_raw = tenths_to_s(s.get("t")), s.get("d")
        if t_raw is None or d_raw is None:
            continue
        d_raw = float(d_raw) / 10.0
        if t_raw < prev_t or d_raw < prev_d:
            t_off += prev_t + (rests_s[seg - 1] if rests_s and len(rests_s) >= seg else 0.0)
            d_off += prev_d
            seg += 1
        rows.append({
            "t_s": round(t_off + t_raw, 1), "distance_m": round(d_off + d_raw, 1),
            "pace_s": tenths_to_s(s.get("p")), "spm": s.get("spm"),
            "hr": int(s["hr"]) if isinstance(s.get("hr"), (int, float)) and s["hr"] > 0 else None, "segment": seg,
        })
        prev_t, prev_d = t_raw, d_raw
    return rows


# ----------------------------------------------------------------------------
# Analyse
# ----------------------------------------------------------------------------


def _mean(v: list[float]) -> float | None:
    return statistics.fmean(v) if v else None


def _slope(ys: list[float]) -> float | None:
    n = len(ys)
    if n < 2:
        return None
    xs = list(range(n))
    xm, ym = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - xm) ** 2 for x in xs)
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / den if den else None


def _stroke_window(strokes: list[dict[str, Any]], a: float, b: float) -> list[dict[str, Any]]:
    return [s for s in strokes if a <= s["t_s"] < b]


def _hr_from_strokes(segs: list[dict[str, Any]], strokes: list[dict[str, Any]]) -> None:
    """HF-Anstieg je Abschnitt aus den Schlagdaten: bei Intervallen über die Segmentnummer (t/d setzen sich je
    Intervall zurück), bei Splits über das Zeitfenster; erster/letzter Schlag mit HF."""
    n_seg = max((x["segment"] for x in strokes), default=0)
    by_segment = bool(segs) and segs[0]["kind"] == "intervall" and n_seg == len(segs)
    for s in segs:
        if by_segment:
            win = [x for x in strokes if x["segment"] == s["nr"] and x.get("hr")]
        else:
            win = [x for x in _stroke_window(strokes, s["start_s"], s["end_s"] + 0.5) if x.get("hr")]
        s["hr_start_strokes"] = win[0]["hr"] if win else None
        s["hr_end_strokes"] = win[-1]["hr"] if win else None
        s["hr_rise"] = (win[-1]["hr"] - win[0]["hr"]) if len(win) >= 2 else None
        if s.get("hr_avg") is None and win:
            s["hr_avg"] = round(statistics.fmean(x["hr"] for x in win))
        if s.get("spm") is None:
            spm = [x["spm"] for x in win if x.get("spm")]
            s["spm"] = round(statistics.fmean(spm)) if spm else None


def _trend_text(pace_slope: float | None, hr_slope: float | None, unit_m: int, per: str = "Intervall") -> str:
    parts = []
    if pace_slope is not None:
        if abs(pace_slope) < 0.5:
            parts.append("Pace gleichmäßig")
        elif pace_slope > 0:
            parts.append(f"Pace wird langsamer (+{pace_slope:.1f} s/{unit_m} m je {per})".replace(".", ","))
        else:
            parts.append(f"Pace wird schneller ({pace_slope:.1f} s/{unit_m} m je {per})".replace(".", ","))
    if hr_slope is not None:
        if abs(hr_slope) < 0.5:
            parts.append("HF stabil")
        elif hr_slope > 0:
            parts.append(f"HF steigt (+{hr_slope:.1f} bpm je {per})".replace(".", ","))
        else:
            parts.append(f"HF fällt ({hr_slope:.1f} bpm je {per})".replace(".", ","))
    return ", ".join(parts) if parts else "–"


def analyze(result: dict[str, Any], strokes_raw: list[dict[str, Any]] | None, rpe: float | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = normalize_summary(result)
    unit = summary["pace_unit_m"]
    splits, intervals = normalize_segments(result, summary["type"])
    strokes = normalize_strokes(strokes_raw or [], rests_s=[i["rest_time_s"] for i in intervals] if intervals else None)
    notes: list[str] = []

    work = intervals if intervals else []
    segments = intervals if intervals else splits
    if strokes:
        _hr_from_strokes(segments, strokes)
    else:
        notes.append("Keine Schlagdaten (ErgData nicht verbunden oder stroke_data=false): kein HF-Verlauf innerhalb der Abschnitte.")
    if summary["hr_avg"] is None:
        notes.append("Keine Herzfrequenz in der Einheit (kein Gurt mit PM5/ErgData verbunden).")
    if not splits and not intervals:
        notes.append("Keine Splits/Intervalle in der Einheit (nur Gesamtwerte).")
    src = {i.get("rest_source") for i in intervals if i.get("rest_source")}
    if "aus Gesamtpause verteilt" in src:
        notes.append(f"Pause je Intervall nicht einzeln geliefert; Gesamtpause {fmt_time(summary['rest_time_s'], tenths=False)} gleichmäßig auf {len(intervals)} Intervalle verteilt (festes Intervallprogramm).")
    if any(s.startswith("unbekannt") for s in src):
        notes.append(f"Pause je Intervall nicht geliefert (Gesamtpause {fmt_time(summary['rest_time_s'], tenths=False)}); Startzeiten der Intervalle ohne Pausen.")

    iv: dict[str, Any] = {"count": len(work)}
    if work:
        paces = [w["pace_s"] for w in work if w["pace_s"]]
        hrs = [float(w["hr_avg"]) for w in work if w.get("hr_avg")]
        dists = [w["distance_m"] for w in work]
        same_dist = max(dists) - min(dists) <= 0.1 * max(dists) if dists and max(dists) > 0 else False
        rests = [w["rest_time_s"] for w in work if w["rest_time_s"]]
        iv.update({
            "distance_m": round(statistics.fmean(dists), 1) if dists else None,
            "same_distance": same_dist,
            "avg_time_s": _mean([w["time_s"] for w in work]),
            "avg_pace_s": _mean(paces), "avg_pace_str": fmt_pace(_mean(paces)),
            "avg_watts": _mean([w["watts"] for w in work if w.get("watts")]) if unit == 500 else None,
            "pace_stdev_s": statistics.pstdev(paces) if len(paces) > 1 else 0.0,
            "pace_min_s": min(paces) if paces else None, "pace_max_s": max(paces) if paces else None,
            "pace_trend_s_per_interval": _slope(paces),
            "avg_hr": round(statistics.fmean(hrs)) if hrs else None,
            "hr_max": max((w["hr_max"] for w in work if w.get("hr_max")), default=None),
            "hr_trend_bpm_per_interval": _slope(hrs),
            "hr_rise_avg": _mean([w["hr_rise"] for w in work if w.get("hr_rise") is not None]),
            "avg_spm": round(statistics.fmean([w["spm"] for w in work if w.get("spm")])) if any(w.get("spm") for w in work) else None,
            "avg_rest_s": _mean(rests),
            "first_pace_str": fmt_pace(paces[0]) if paces else "–", "last_pace_str": fmt_pace(paces[-1]) if paces else "–",
            "first_hr": work[0].get("hr_avg"), "last_hr": work[-1].get("hr_avg"),
        })
        iv["trend_text"] = _trend_text(iv["pace_trend_s_per_interval"], iv["hr_trend_bpm_per_interval"], unit)
    elif splits:
        paces = [s["pace_s"] for s in splits if s["pace_s"]]
        hrs = [float(s["hr_avg"]) for s in splits if s.get("hr_avg")]
        iv.update({
            "steady": True, "pace_stdev_s": statistics.pstdev(paces) if len(paces) > 1 else 0.0,
            "pace_trend_s_per_split": _slope(paces), "hr_trend_bpm_per_split": _slope(hrs),
            "hr_drift_bpm": (hrs[-1] - hrs[0]) if len(hrs) >= 2 else None,
            "trend_text": _trend_text(_slope(paces), _slope(hrs), unit, per="Split"),
        })

    analysis = {
        "summary": summary, "rpe": rpe, "splits": splits, "intervals": intervals, "segments": segments,
        "is_interval_session": bool(intervals), "intervals_stats": iv, "strokes_points": len(strokes), "notes": notes,
    }
    return analysis, strokes


# ----------------------------------------------------------------------------
# Bericht
# ----------------------------------------------------------------------------


def _row_hr(seg: dict[str, Any]) -> str:
    if seg.get("hr_rise") is not None:
        return f"{seg['hr_rise']:+d} ({seg['hr_start_strokes']}→{seg['hr_end_strokes']})"
    return "–"


def render_markdown(a: dict[str, Any]) -> str:
    s, iv = a["summary"], a.get("intervals_stats") or {}
    unit = s["pace_unit_m"]
    L: list[str] = []
    L.append(f"# Ergometer-Analyse {s['date']} – {s['type_de']} (Result-ID {s['result_id']})")
    L.append("")
    L.append("## 1. Überblick")
    L.append("")
    L.append(f"| Datum | Gerät | Distanz | Zeit | Ø-Pace /{unit} m | Ø-Watt | Ø-SPM | Ø-HF | Max-HF | Drag | Programm |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    L.append(
        f"| {s['start_local'][:16]} | {s['type_de']} | {fmt_num(s['distance_m'], 0, ' m')} | {s['time_str']} | {s['pace_str']} | "
        f"{fmt_num(s['watts'], 0)} | {s['spm'] or '–'} | {s['hr_avg'] or '–'} | {s['hr_max'] or '–'} | {s['drag_factor'] or '–'} | {s['workout_type'] or '–'} |"
    )
    extras = []
    if s["rest_time_s"]:
        extras.append(f"Pausen gesamt {fmt_time(s['rest_time_s'], tenths=False)}")
    if s["calories"]:
        extras.append(f"{s['calories']} kcal")
    if s["source"]:
        extras.append(f"Quelle {s['source']}")
    if a.get("rpe") is not None:
        extras.append(f"RPE {fmt_num(a['rpe'], 0)}")
    if extras:
        L.append("")
        L.append(", ".join(extras) + ".")
    L.append("")

    segs = a["segments"]
    L.append(f"## 2. {'Intervalle' if a['is_interval_session'] else 'Splits'}")
    L.append("")
    if segs:
        L.append(f"| Nr | Distanz | Zeit | Pace /{unit} m | Watt | SPM | Ø-HF | Max-HF | HF-Anstieg | Pause |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for g in segs:
            L.append(
                f"| {g['nr']} | {fmt_num(g['distance_m'], 0, ' m')} | {g['time_str']} | {g['pace_str']} | {fmt_num(g.get('watts'), 0)} | "
                f"{g.get('spm') or '–'} | {g.get('hr_avg') or '–'} | {g.get('hr_max') or '–'} | {_row_hr(g)} | "
                f"{fmt_time(g['rest_time_s'], tenths=False) if g['rest_time_s'] else '–'} |"
            )
    else:
        L.append("Keine Abschnitte vorhanden.")
    L.append("")

    L.append("## 3. Auswertung")
    L.append("")
    if a["is_interval_session"] and iv.get("count"):
        d = f"{fmt_num(iv['distance_m'], 0)} m" if iv.get("same_distance") else "verschiedene Distanzen"
        L.append(f"- Intervalle: {iv['count']} × {d}, Ø-Zeit {fmt_time(iv['avg_time_s'])}, Ø-Pause {fmt_time(iv['avg_rest_s'], tenths=False) if iv.get('avg_rest_s') else '–'}")
        L.append(f"- Ø-Pace {iv['avg_pace_str']} /{unit} m" + (f" ({fmt_num(iv['avg_watts'], 0)} W)" if iv.get("avg_watts") else "") + f", Streuung ±{fmt_num(iv['pace_stdev_s'], 1)} s, Spanne {fmt_pace(iv['pace_min_s'])}–{fmt_pace(iv['pace_max_s'])}")
        L.append(f"- Ø-HF {iv['avg_hr'] or '–'} bpm (Max {iv['hr_max'] or '–'}), erstes Intervall {iv['first_hr'] or '–'}, letztes {iv['last_hr'] or '–'}" + (f", HF-Anstieg im Intervall Ø {fmt_num(iv['hr_rise_avg'], 0)} bpm" if iv.get("hr_rise_avg") is not None else ""))
        L.append(f"- Ø-Schlagfrequenz {iv['avg_spm'] or '–'} spm")
        L.append(f"- Trend: {iv['trend_text']} (erstes {iv['first_pace_str']} → letztes {iv['last_pace_str']})")
    elif segs:
        L.append(f"- Dauerbelastung, {len(segs)} Splits. Pace-Streuung ±{fmt_num(iv.get('pace_stdev_s'), 1)} s, Trend: {iv.get('trend_text', '–')}")
        if iv.get("hr_drift_bpm") is not None:
            L.append(f"- HF-Drift erster → letzter Split: {iv['hr_drift_bpm']:+.0f} bpm")
    else:
        L.append("- Nur Gesamtwerte vorhanden.")
    L.append("")
    if a["notes"]:
        L.append("## Hinweise")
        L.append("")
        L.extend(f"- {n}" for n in a["notes"])
        L.append("")
    L.append(f"_Quelle: Concept2 Logbook API, Schlagdaten: {a['strokes_points']} Punkte._")
    return "\n".join(L) + "\n"


def coach_text(a: dict[str, Any]) -> str:
    """Kurzer Textbaustein für den Coach (z. B. TrainHeroic-Kommentar): Pace, HF, RPE."""
    s, iv = a["summary"], a.get("intervals_stats") or {}
    unit = s["pace_unit_m"]
    L = [f"{s['type_de']} {s['date']}: {fmt_num(s['distance_m'], 0)} m in {s['time_str']}, Ø {s['pace_str']} /{unit} m"
         + (f", {fmt_num(s['watts'], 0)} W" if s.get("watts") else "") + (f", {s['spm']} spm" if s.get("spm") else "")]
    if a["is_interval_session"] and iv.get("count"):
        segs = a["segments"]
        paces = " / ".join(g["pace_str"] for g in segs)
        L.append(f"{iv['count']}x{fmt_num(iv['distance_m'], 0)} m" if iv.get("same_distance") else f"{iv['count']} Intervalle")
        L.append(f"Pace: {paces} (Ø {iv['avg_pace_str']})")
        hrs = " / ".join(str(g.get("hr_avg") or "–") for g in segs)
        L.append(f"HR avg: {hrs} (Ø {iv['avg_hr'] or '–'}, max {iv['hr_max'] or '–'})" if iv.get("avg_hr") else "HR: keine Daten")
    else:
        L.append(f"HR avg {s['hr_avg']}, max {s['hr_max']}" if s.get("hr_avg") else "HR: keine Daten")
    L.append(f"RPE: {fmt_num(a['rpe'], 0)}" if a.get("rpe") is not None else "RPE: (bitte ergänzen)")
    return "\n".join(L)


# ----------------------------------------------------------------------------
# Speichern / Laden
# ----------------------------------------------------------------------------


def base_dir(out_dir: str | None) -> Path:
    return Path(out_dir or os.environ.get("CONCEPT2_DATA_DIR") or "data/concept2")


def _write_csv(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_outputs(out_dir: Path, analysis: dict[str, Any], strokes: list[dict[str, Any]], raw: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    for name, obj in raw.items():
        if obj is not None:
            _write_json(out_dir / "raw" / f"{name}.json", obj)
    _write_json(out_dir / "analysis.json", analysis)
    _write_csv(out_dir / "segments.csv", analysis["segments"], SEG_CSV_COLS)
    _write_csv(out_dir / "strokes.csv", strokes, STROKE_CSV_COLS)
    (out_dir / "summary.md").write_text(render_markdown(analysis), encoding="utf-8")
    (out_dir / "coach.txt").write_text(coach_text(analysis) + "\n", encoding="utf-8")


def list_exported(base: Path) -> list[dict[str, Any]]:
    rows = []
    if base.exists():
        for d in sorted(base.iterdir()):
            f = d / "analysis.json"
            if f.is_file():
                a = json.loads(f.read_text(encoding="utf-8"))
                s, iv = a["summary"], a.get("intervals_stats") or {}
                rows.append({
                    "dir": str(d.resolve()), "date": s.get("date"), "result_id": s.get("result_id"), "type": s.get("type"),
                    "distance_m": s.get("distance_m"), "time_str": s.get("time_str"), "pace_str": s.get("pace_str"),
                    "avg_hr": s.get("hr_avg"), "intervals": iv.get("count", 0), "interval_pace_str": iv.get("avg_pace_str"),
                    "interval_avg_hr": iv.get("avg_hr"), "rpe": a.get("rpe"),
                })
    return rows


# ----------------------------------------------------------------------------
# API-Zugriff
# ----------------------------------------------------------------------------


def compact(r: dict[str, Any]) -> dict[str, Any]:
    s = normalize_summary(r)
    return {k: s[k] for k in ("result_id", "date", "start_local", "type", "type_de", "workout_type", "distance_m", "time_str", "pace_str", "spm", "hr_avg", "hr_max", "has_stroke_data", "source", "comments")}


def list_results(client: c2.Concept2Client, *, limit: int = 10, type_: str | None = None, from_date: str | None = None, to_date: str | None = None) -> list[dict[str, Any]]:
    """Neueste zuerst. Die API liefert aufsteigend nach Datum; deshalb über die letzte Seite gehen."""
    number = max(1, min(limit, 250))
    first, meta = client.results(from_date=from_date, to_date=to_date, type_=type_, number=number, page=1)
    total_pages = int(meta.get("total_pages") or 1)
    rows = first
    if total_pages > 1:
        last, _ = client.results(from_date=from_date, to_date=to_date, type_=type_, number=number, page=total_pages)
        rows = last
        if len(rows) < number and total_pages > 2:
            prev, _ = client.results(from_date=from_date, to_date=to_date, type_=type_, number=number, page=total_pages - 1)
            rows = prev + rows
    rows = sorted(rows, key=lambda r: (str(r.get("date_utc") or r.get("date") or ""), r.get("id") or 0), reverse=True)
    return rows[:limit]


def resolve_result_id(client: c2.Concept2Client, *, result_id: int | None, date: str | None, type_: str | None) -> int:
    if result_id:
        return int(result_id)
    if date:
        rows = list_results(client, limit=20, type_=type_, from_date=date, to_date=date)
        if not rows:
            raise RuntimeError(f"Keine Einheit am {date}" + (f" ({type_})" if type_ else "") + " im Logbook.")
        if len(rows) > 1:
            opts = "; ".join(f"{r.get('id')}: {r.get('type')} {r.get('distance')} m {r.get('time_formatted')}" for r in rows)
            raise RuntimeError(f"Mehrere Einheiten am {date}: {opts}. Bitte --id angeben.")
        return int(rows[0]["id"])
    rows = list_results(client, limit=1, type_=type_)
    if not rows:
        raise RuntimeError("Keine Einheiten im Logbook" + (f" vom Typ {type_}" if type_ else "") + ".")
    return int(rows[0]["id"])


def fetch(client: c2.Concept2Client, result_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    result = client.result(result_id)
    strokes: list[dict[str, Any]] = []
    if result.get("stroke_data"):
        try:
            strokes = client.strokes(result_id)
        except c2.Concept2ApiError as exc:
            errors.append(f"Schlagdaten: {exc}")
    return result, strokes, errors


def export_and_analyze(client: c2.Concept2Client, result_id: int, *, rpe: float | None, out_dir: str | None) -> tuple[Path, dict[str, Any]]:
    result, strokes_raw, errors = fetch(client, result_id)
    analysis, strokes = analyze(result, strokes_raw, rpe=rpe)
    analysis["notes"] = [f"API-Fehler: {e}" for e in errors] + analysis["notes"]
    out = base_dir(out_dir) / f"{analysis['summary']['date']}_{result_id}"
    write_outputs(out, analysis, strokes, {"result": result, "strokes": strokes_raw})
    analysis["output_dir"] = str(out.resolve())
    return out, analysis


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", type=int, help="Result-ID aus dem Logbook")
    ap.add_argument("--date", help="Einheit an diesem Datum (YYYY-MM-DD)")
    ap.add_argument("--type", dest="type_", choices=sorted(TYPE_DE), help="Gerät, z. B. rower, skierg, bike")
    ap.add_argument("--rpe", type=float, help="RPE des Nutzers für Bericht und Coach-Text")
    ap.add_argument("--list", type=int, metavar="N", help="letzte N Einheiten anzeigen")
    ap.add_argument("--exported", action="store_true", help="bereits gesicherte Einheiten auflisten")
    ap.add_argument("--out", help="Ausgabe-Ordner (Standard $CONCEPT2_DATA_DIR oder ./data/concept2)")
    ap.add_argument("--print", action="store_true", help="Bericht ausgeben")
    a = ap.parse_args()

    if a.exported:
        for r in list_exported(base_dir(a.out)):
            print(f"{r['date']}  {r['type']:<7} {fmt_num(r['distance_m'], 0):>6} m  {r['time_str']:>8}  {r['pace_str']:>7}  HF {r['avg_hr'] or '–'}  ID {r['result_id']}")
        return 0
    try:
        client = c2.connect()
        if a.list:
            for r in list_results(client, limit=a.list, type_=a.type_):
                c = compact(r)
                print(f"{c['start_local'][:16]}  {c['type']:<7} {fmt_num(c['distance_m'], 0):>6} m  {c['time_str']:>8}  {c['pace_str']:>7}  HF {c['hr_avg'] or '–'}  ID {c['result_id']}")
            return 0
        rid = resolve_result_id(client, result_id=a.id, date=a.date, type_=a.type_)
        out, analysis = export_and_analyze(client, rid, rpe=a.rpe, out_dir=a.out)
        print(f"Gesichert unter {out}")
        if a.print:
            print(render_markdown(analysis))
            print(coach_text(analysis))
        return 0
    except (c2.Concept2AuthError, c2.Concept2ApiError, RuntimeError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
