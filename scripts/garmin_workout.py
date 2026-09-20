# /// script
# requires-python = ">=3.11"
# dependencies = ["garminconnect>=0.3.2"]
# ///
"""Workouts in Garmin Connect anlegen, anzeigen, terminieren und löschen.

    uv run scripts/garmin_workout.py list [--limit 20]
    uv run scripts/garmin_workout.py show <workout_id>
    uv run scripts/garmin_workout.py create spec.json [--schedule YYYY-MM-DD] [--dry-run]
    uv run scripts/garmin_workout.py schedule <workout_id> YYYY-MM-DD
    uv run scripts/garmin_workout.py delete <workout_id>
    uv run scripts/garmin_workout.py calendar [YYYY-MM]          # terminierte Workouts im Monat
    uv run scripts/garmin_workout.py unschedule <termin_id>      # Termin entfernen (Workout bleibt)

Spezifikation (JSON):

    {
      "name": "Indoor Cycling NXT LVL",
      "sport": "cycling",                       # running | cycling | swimming | walking | hiking | cardio | strength | other
      "description": "optional",
      "steps": [
        {"type": "warmup",   "duration_s": 600},                              # ohne Ziel
        {"type": "interval", "duration_s": 5400, "target": {"hr_bpm": [90, 130]}},
        {"type": "interval", "distance_m": 1000, "target": {"pace_min_km": ["4:10", "4:20"]}},
        {"type": "recovery", "duration_s": 120,  "target": {"hr_zone": 2}},
        {"repeat": 6, "steps": [ {...}, {...} ]},                             # Wiederholungsblock
        {"type": "cooldown", "end": "lap"}                                    # Ende per Rundentaste
      ]
    }

Schritt-Typen: warmup, interval, recovery, rest, cooldown. Ende: duration_s, distance_m oder "end": "lap".
Ziele: hr_bpm [low, high], hr_zone 1–5, pace_min_km ["schnell", "langsam"] (nur Laufen/Gehen), sonst keins.
Der Upload ist ein Schreibzugriff auf das Garmin-Konto – vorher mit --dry-run prüfen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import garmin_auth  # noqa: E402

SPORTS = {
    "running": (1, "running", 1),
    "cycling": (2, "cycling", 2),
    "swimming": (4, "swimming", 3),
    "walking": (9, "walking", 4),
    "hiking": (3, "hiking", 5),
    "other": (3, "other", 13),
    # Geprüft am 20.09.2026 an vorhandenen Workouts des Kontos: EMOM (Cardio) = 6, NXT LVL 2.0 (Kraft) = 5.
    # Auf der Uhr erscheinen Workouts nur im Profil ihrer Sportart unter Training → Meine Workouts;
    # "other" taucht dort nicht auf, nur über den Kalender. Hyrox/Stationen deshalb als "cardio" anlegen.
    "cardio": (6, "cardio_training", 6),
    "strength": (5, "strength_training", 4),
}
STEP_TYPES = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "rest": 5, "repeat": 6}

# Übungen aus dem Garmin-Katalog (category, exerciseName). Werte abgelesen am 20.09.2026 an einem Cardio-Workout,
# das der Nutzer in der Connect-App manuell mit Übungen versehen hat (Workout 1703599385). Andere Kürzel:
# {"category": "...", "name": "..."} direkt angeben (Garmin-Katalognamen in Großbuchstaben, z. B. aus get_workout raw).
EXERCISES = {
    "run": ("RUN", "JOG"),                       # Laufen (Belastung)
    "run_walk": ("RUN", "RUN_OR_WALK"),          # Laufen/Gehen (Aufwärmen, Erholung)
    "sled_push": ("SLED", "PUSH"),
    "sled_pull": ("SLED", "BACKWARD_DRAG"),
    "burpee": ("TOTAL_BODY", "BURPEE"),
    "lunge": ("LUNGE", "WEIGHTED_WALKING_LUNGE"),
    "wall_ball": ("SQUAT", "WALL_BALL"),
    "indoor_bike": ("INDOOR_BIKE", ""),
}
STEP_LABEL = {
    "warmup": "Aufwärmen", "cooldown": "Auslaufen", "interval": "Belastung",
    "recovery": "Erholung", "rest": "Pause", "repeat": "Wiederholen",
}


def pace_to_mps(pace: str) -> float:
    m, s = pace.split(":")
    return 1000.0 / (int(m) * 60 + int(s))


def mps_to_pace(mps: float) -> str:
    sec = int(round(1000.0 / mps))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _target(t: dict[str, Any] | None) -> dict[str, Any]:
    if not t:
        return {"targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}}
    if "hr_bpm" in t:
        lo, hi = t["hr_bpm"]
        return {
            "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
            "targetValueOne": float(lo), "targetValueTwo": float(hi), "zoneNumber": None,
        }
    if "hr_zone" in t:
        return {
            "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
            "targetValueOne": None, "targetValueTwo": None, "zoneNumber": int(t["hr_zone"]),
        }
    if "pace_min_km" in t:
        fast, slow = t["pace_min_km"]
        return {
            "targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6},
            "targetValueOne": pace_to_mps(fast), "targetValueTwo": pace_to_mps(slow), "zoneNumber": None,
        }
    raise ValueError(f"Unbekanntes Ziel: {t}")


def _end(step: dict[str, Any]) -> dict[str, Any]:
    if step.get("duration_s") is not None:
        return {
            "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
            "endConditionValue": float(step["duration_s"]),
        }
    if step.get("distance_m") is not None:
        return {
            "endCondition": {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True},
            "endConditionValue": float(step["distance_m"]),
        }
    return {
        "endCondition": {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True},
        "endConditionValue": 0.0,
    }


def build_steps(steps: list[dict[str, Any]], counter: list[int]) -> list[dict[str, Any]]:
    out = []
    for st in steps:
        counter[0] += 1
        order = counter[0]
        if "repeat" in st:
            children = build_steps(st["steps"], counter)
            out.append({
                "type": "RepeatGroupDTO", "stepOrder": order,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                "numberOfIterations": int(st["repeat"]),
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
                "endConditionValue": float(st["repeat"]),
                "workoutSteps": children,
                "smartRepeat": False,
            })
            continue
        kind = st["type"]
        d: dict[str, Any] = {
            "type": "ExecutableStepDTO", "stepOrder": order,
            "stepType": {"stepTypeId": STEP_TYPES[kind], "stepTypeKey": kind, "displayOrder": STEP_TYPES[kind]},
        }
        d.update(_end(st))
        d.update(_target(st.get("target")))
        if st.get("note"):
            d["description"] = st["note"]
        ex = st.get("exercise")
        if ex:
            if isinstance(ex, str):
                if ex not in EXERCISES:
                    raise ValueError(f"Unbekannte Übung '{ex}'. Bekannt: {', '.join(sorted(EXERCISES))} oder {{'category','name'}}.")
                cat, name = EXERCISES[ex]
            else:
                cat, name = str(ex["category"]).upper(), str(ex.get("name", "")).upper()
            d["category"], d["exerciseName"] = cat, name
            d["weightValue"] = float(st["weight_kg"]) if st.get("weight_kg") is not None else 0.0
            d["weightUnit"] = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
        out.append(d)
    return out


def _has_exercise(steps: list[dict[str, Any]]) -> bool:
    return any(("exercise" in s) or ("repeat" in s and _has_exercise(s["steps"])) for s in steps)


def estimated_seconds(steps: list[dict[str, Any]]) -> int:
    total = 0
    for st in steps:
        if "repeat" in st:
            total += int(st["repeat"]) * estimated_seconds(st["steps"])
        else:
            total += int(st.get("duration_s") or 0)
    return total


def build_workout(spec: dict[str, Any]) -> dict[str, Any]:
    sid, skey, disp = SPORTS[spec.get("sport", "running")]
    sport = {"sportTypeId": sid, "sportTypeKey": skey, "displayOrder": disp}
    w = {
        "workoutName": spec["name"],
        "description": spec.get("description"),
        "sportType": sport,
        "estimatedDurationInSecs": estimated_seconds(spec["steps"]),
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": build_steps(spec["steps"], [0])}],
    }
    if skey in ("cardio_training", "strength_training") and _has_exercise(spec["steps"]):
        w["subSportType"] = "GENERIC"  # so speichert es die Connect-App bei Workouts mit Übungen
    return w


def describe(w: dict[str, Any]) -> str:
    """Workout (eigene Spezifikation oder Antwort von Garmin) als lesbare Liste."""
    lines = [
        f"{w.get('workoutName')}  [{(w.get('sportType') or {}).get('sportTypeKey')}]  ID {w.get('workoutId', '–')}"
        f"  geschätzt {fmt_dur(w.get('estimatedDurationInSecs') or 0)}"
    ]
    if w.get("description"):
        lines.append(f"  {w['description']}")

    def walk(steps, indent=2):
        for s in steps:
            key = (s.get("stepType") or {}).get("stepTypeKey")
            if s.get("type") == "RepeatGroupDTO":
                lines.append(" " * indent + f"{int(s.get('numberOfIterations') or 0)} × wiederholen:")
                walk(s.get("workoutSteps") or [], indent + 4)
                continue
            cond = (s.get("endCondition") or {}).get("conditionTypeKey")
            val = s.get("endConditionValue") or 0
            end = {
                "time": fmt_dur(val),
                "distance": f"{val / 1000:.2f} km".replace(".", ","),
                "lap.button": "Rundentaste",
            }.get(cond, f"{cond}={val}")
            tkey = (s.get("targetType") or {}).get("workoutTargetTypeKey")
            v1, v2, zone = s.get("targetValueOne"), s.get("targetValueTwo"), s.get("zoneNumber")
            if tkey == "heart.rate.zone":
                target = f"HF-Zone {zone}" if zone else f"HF {v1:.0f}–{v2:.0f} bpm"
            elif tkey == "pace.zone" and v1 and v2:
                target = f"Pace {mps_to_pace(v1)}–{mps_to_pace(v2)} min/km"
            elif tkey in (None, "no.target"):
                target = "kein Ziel"
            else:
                target = f"{tkey} {v1}–{v2}"
            note = f"  ({s['description']})" if s.get("description") else ""
            ex = ""
            if s.get("category"):
                ex = f"  [{s['category']}" + (f"/{s['exerciseName']}" if s.get("exerciseName") else "") + "]"
            lines.append(" " * indent + f"{STEP_LABEL.get(key, key):<10} {end:<12} {target}{note}{ex}")

    for seg in w.get("workoutSegments") or []:
        walk(seg.get("workoutSteps") or [])
    return "\n".join(lines)


def scheduled_workouts(client, year: int, month: int) -> list[dict[str, Any]]:
    """Terminierte Workouts eines Monats (Garmin-Kalender)."""
    cal = client.get_scheduled_workouts(year, month) or {}
    out = []
    for it in cal.get("calendarItems", []):
        if it.get("itemType") == "workout" or it.get("workoutId"):
            out.append({"date": it.get("date"), "name": it.get("title"), "workout_id": it.get("workoutId"),
                        "schedule_id": it.get("id"), "sport": it.get("sportTypeKey")})
    return sorted(out, key=lambda x: (x["date"] or "", x["schedule_id"] or 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="Workouts der Bibliothek auflisten")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("show", help="ein Workout anzeigen")
    p.add_argument("workout_id", type=int)
    p = sub.add_parser("create", help="Workout aus JSON-Spezifikation hochladen")
    p.add_argument("spec", type=Path)
    p.add_argument("--schedule", metavar="YYYY-MM-DD", help="zusätzlich im Kalender terminieren")
    p.add_argument("--dry-run", action="store_true", help="nur anzeigen, nicht hochladen")
    p = sub.add_parser("schedule", help="vorhandenes Workout terminieren")
    p.add_argument("workout_id", type=int)
    p.add_argument("date")
    p = sub.add_parser("delete", help="Workout aus der Bibliothek löschen")
    p.add_argument("workout_id", type=int)
    p = sub.add_parser("calendar", help="terminierte Workouts eines Monats anzeigen")
    p.add_argument("month", nargs="?", help="YYYY-MM (Standard: aktueller Monat)")
    p = sub.add_parser("unschedule", help="Termin aus dem Kalender entfernen (Workout bleibt in der Bibliothek)")
    p.add_argument("schedule_id", type=int, help="Termin-ID aus `calendar`")
    a = ap.parse_args()

    payload: dict[str, Any] | None = None
    if a.cmd == "create":
        spec = json.loads(a.spec.read_text(encoding="utf-8"))
        payload = build_workout(spec)
        print("Geplantes Workout:")
        print(describe(payload))
        if a.dry_run:
            print("\n--dry-run: nichts hochgeladen.")
            return 0

    client = garmin_auth.connect(interactive=False)

    if a.cmd == "list":
        for w in client.get_workouts(0, a.limit) or []:
            print(f"{w.get('workoutId')}  {(w.get('sportType') or {}).get('sportTypeKey') or '':<18} {w.get('workoutName')}")
    elif a.cmd == "show":
        print(describe(client.get_workout_by_id(a.workout_id)))
    elif a.cmd == "create":
        res = client.upload_workout(payload)
        wid = res.get("workoutId")
        print(f"\nHochgeladen, Workout-ID {wid}. Kontrolle (von Garmin zurückgelesen):")
        print(describe(client.get_workout_by_id(wid)))
        if a.schedule:
            r = client.schedule_workout(wid, a.schedule)
            print(f"Im Kalender terminiert für {a.schedule} (Termin-ID {r.get('workoutScheduleId', r)}).")
    elif a.cmd == "schedule":
        r = client.schedule_workout(a.workout_id, a.date)
        print(f"Terminiert für {a.date}: {r}")
    elif a.cmd == "delete":
        client.delete_workout(a.workout_id)
        print(f"Workout {a.workout_id} gelöscht.")
    elif a.cmd == "calendar":
        from datetime import date as _date
        ym = a.month or _date.today().strftime("%Y-%m")
        y, m = (int(x) for x in ym.split("-"))
        for it in scheduled_workouts(client, y, m):
            print(f"{it['date']}  {it['name']:<45} Workout {it['workout_id']}  Termin-ID {it['schedule_id']}")
    elif a.cmd == "unschedule":
        client.unschedule_workout(a.schedule_id)
        print(f"Termin {a.schedule_id} entfernt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
