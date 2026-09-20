"""Tests für den Workout-Builder (ohne Netz).

Ausführen:  uv run --with pytest --with requests pytest -q tests/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import garmin_workout as gw  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _steps(w):
    return w["workoutSegments"][0]["workoutSteps"]


def test_sports_cardio_strength():
    assert gw.SPORTS["cardio"][:2] == (6, "cardio_training")
    assert gw.SPORTS["strength"][:2] == (5, "strength_training")


def test_exercise_codes_match_connect_app():
    """Codes wie von der Connect-App gespeichert (Workout 1703599385, 20.09.2026)."""
    spec = {"name": "t", "sport": "cardio", "steps": [
        {"type": "warmup", "duration_s": 600, "exercise": "run_walk", "note": "w"},
        {"type": "interval", "duration_s": 180, "exercise": "run"},
        {"type": "interval", "duration_s": 60, "exercise": "sled_push"},
        {"type": "interval", "duration_s": 60, "exercise": "sled_pull"},
        {"type": "interval", "duration_s": 60, "exercise": "burpee"},
        {"type": "interval", "duration_s": 60, "exercise": "lunge"},
        {"type": "interval", "duration_s": 60, "exercise": "wall_ball", "weight_kg": 9},
        {"type": "cooldown", "duration_s": 600, "exercise": "indoor_bike"},
        {"type": "interval", "duration_s": 60, "exercise": {"category": "row", "name": "indoor_row"}},
        {"type": "interval", "duration_s": 60},
    ]}
    w = gw.build_workout(spec)
    assert w["subSportType"] == "GENERIC"
    got = [(s.get("category"), s.get("exerciseName")) for s in _steps(w)]
    assert got == [("RUN", "RUN_OR_WALK"), ("RUN", "JOG"), ("SLED", "PUSH"), ("SLED", "BACKWARD_DRAG"), ("TOTAL_BODY", "BURPEE"),
                   ("LUNGE", "WEIGHTED_WALKING_LUNGE"), ("SQUAT", "WALL_BALL"), ("INDOOR_BIKE", ""), ("ROW", "INDOOR_ROW"), (None, None)]
    assert _steps(w)[6]["weightValue"] == 9.0 and _steps(w)[6]["weightUnit"]["unitKey"] == "kilogram"
    assert _steps(w)[0]["weightValue"] == 0.0
    text = gw.describe(w)
    assert "[SLED/PUSH]" in text and "[INDOOR_BIKE]" in text


def test_unknown_exercise_raises():
    with pytest.raises(ValueError, match="Unbekannte Übung"):
        gw.build_workout({"name": "t", "sport": "cardio", "steps": [{"type": "interval", "duration_s": 60, "exercise": "kettlebell"}]})


def test_no_exercise_no_subsport():
    w = gw.build_workout({"name": "t", "sport": "running", "steps": [{"type": "interval", "distance_m": 1000, "exercise": "run"}]})
    assert "subSportType" not in w  # nur cardio/strength
    w2 = gw.build_workout({"name": "t", "sport": "cardio", "steps": [{"type": "interval", "duration_s": 60}]})
    assert "subSportType" not in w2


def test_templates_build():
    for f in sorted((ROOT / "workouts").glob("*.json")):
        spec = json.loads(f.read_text(encoding="utf-8"))
        w = gw.build_workout(spec)
        assert w["workoutName"] == spec["name"], f.name
        assert gw.describe(w)


def test_rp_template_has_exercises():
    spec = json.loads((ROOT / "workouts" / "nxt_lvl_hyrox_rp_workout.json").read_text(encoding="utf-8"))
    assert all("exercise" in s for s in spec["steps"])
    stations = [s["exercise"] for s in spec["steps"] if s["type"] == "interval" and s["duration_s"] == 60]
    assert stations == ["sled_push", "sled_pull", "burpee", "lunge", "wall_ball"]
