"""Tests für die Concept2-Anbindung ohne Netz: Normalisierung, Analyse, Bericht, Token-Logik.

Ausführen:  uv run --with pytest --with requests pytest -q tests/test_concept2.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import concept2_auth as c2  # noqa: E402
import concept2_export as ce  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------
# Formatierung / Einheiten
# ----------------------------------------------------------------------------


def test_fmt_time_and_pace():
    assert ce.fmt_time(125.3) == "2:05.3"
    assert ce.fmt_time(3725.0) == "1:02:05.0"
    assert ce.fmt_time(3725.0, tenths=False) == "1:02:05"
    assert ce.fmt_pace(None) == "–"
    assert ce.tenths_to_s(12000) == 1200.0


def test_pace_and_watts():
    p = ce.pace_from(2000, 480.0)  # 8:00 auf 2000 m → 2:00 /500 m
    assert p == 120.0
    assert round(ce.watts_from_pace(120.0)) == 203  # Concept2-Tabelle: 2:00 /500 m ≈ 203 W
    assert ce.pace_from(10000, 1200.0, 1000) == 120.0  # Bike Erg: je 1000 m


# ----------------------------------------------------------------------------
# Intervall-Einheit (Ski Erg) mit Schlagdaten
# ----------------------------------------------------------------------------


def test_interval_analysis():
    res = _load("result_intervals.json")["data"]
    strokes = _load("strokes_intervals.json")["data"]
    a, st = ce.analyze(res, strokes, rpe=7)

    s = a["summary"]
    assert s["type"] == "skierg" and s["type_de"] == "Ski Erg"
    assert s["distance_m"] == 5000 and s["time_s"] == 1230.0
    assert s["pace_str"] == "2:03.0"
    assert s["hr_avg"] == 152 and s["hr_max"] == 171
    assert a["is_interval_session"] and a["intervals_stats"]["count"] == 5

    iv = a["intervals_stats"]
    assert iv["same_distance"] and iv["distance_m"] == 1000
    assert iv["avg_pace_str"] == "2:03.0"
    assert iv["pace_min_s"] == 120.0 and iv["pace_max_s"] == 126.0
    assert iv["pace_trend_s_per_interval"] > 0  # wird langsamer
    assert iv["hr_trend_bpm_per_interval"] > 0
    assert "langsamer" in iv["trend_text"]
    assert iv["avg_rest_s"] == 60.0

    # Startzeiten kumulieren inkl. Pausen; HF-Anstieg aus den Schlagdaten
    segs = a["segments"]
    assert [g["start_s"] for g in segs] == [0.0, 300.0, 603.0, 909.0, 1218.0]
    assert st[0]["t_s"] == 0.0 and st[-1]["t_s"] == 1470.0  # letzte Schlagzeit = Ende Intervall 5 (inkl. Pausen)
    assert segs[0]["hr_start_strokes"] == 120 and segs[0]["hr_end_strokes"] == 160 and segs[0]["hr_rise"] == 40
    assert all(g["hr_rise"] is not None for g in segs)
    assert len(st) == len(strokes)
    assert st[-1]["segment"] == 5  # t/d setzen sich je Intervall zurück → 5 Segmente
    assert a["notes"] == []


def test_markdown_and_coach_text():
    res = _load("result_intervals.json")["data"]
    strokes = _load("strokes_intervals.json")["data"]
    a, _ = ce.analyze(res, strokes, rpe=7)
    md = ce.render_markdown(a)
    assert "# Ergometer-Analyse 2026-09-19 – Ski Erg" in md
    assert "## 2. Intervalle" in md
    assert "| 1 | 1000 m | 4:00.0 | 2:00.0 |" in md
    assert "RPE 7" in md
    txt = ce.coach_text(a)
    assert txt.splitlines()[0].startswith("Ski Erg 2026-09-19: 5000 m in 20:30.0")
    assert "5x1000 m" in txt
    assert "Pace: 2:00.0 / 2:01.5 / 2:03.0 / 2:04.5 / 2:06.0 (Ø 2:03.0)" in txt
    assert "RPE: 7" in txt


def test_write_outputs(tmp_path: Path):
    res = _load("result_intervals.json")["data"]
    strokes = _load("strokes_intervals.json")["data"]
    a, st = ce.analyze(res, strokes, rpe=None)
    out = tmp_path / "2026-09-19_777"
    ce.write_outputs(out, a, st, {"result": res, "strokes": strokes})
    for f in ("summary.md", "analysis.json", "segments.csv", "strokes.csv", "coach.txt", "raw/result.json", "raw/strokes.json"):
        assert (out / f).is_file(), f
    assert "RPE: (bitte ergänzen)" in (out / "coach.txt").read_text(encoding="utf-8")
    rows = ce.list_exported(tmp_path)
    assert rows[0]["result_id"] == 777 and rows[0]["intervals"] == 5


# ----------------------------------------------------------------------------
# Dauerbelastung (Rudern) mit Splits, ohne Schlagdaten und ohne HF
# ----------------------------------------------------------------------------


def test_steady_state_without_hr():
    res = _load("result_steady.json")["data"]
    a, st = ce.analyze(res, None)
    s = a["summary"]
    assert s["type_de"] == "Rudern (RowErg)" and s["hr_avg"] is None
    assert not a["is_interval_session"] and len(a["splits"]) == 4
    assert a["intervals_stats"]["steady"] is True
    assert st == []
    assert any("Schlagdaten" in n for n in a["notes"]) and any("Herzfrequenz" in n for n in a["notes"])
    md = ce.render_markdown(a)
    assert "## 2. Splits" in md and "Dauerbelastung, 4 Splits" in md
    assert "HR: keine Daten" in ce.coach_text(a)


def test_compact_and_bike_pace():
    res = _load("result_steady.json")["data"]
    c = ce.compact(res)
    assert set(c) >= {"result_id", "date", "type", "distance_m", "time_str", "pace_str", "hr_avg"}
    bike = {"id": 1, "date": "2026-09-01 10:00:00", "type": "bike", "distance": 10000, "time": 12000, "heart_rate": {}}
    s = ce.normalize_summary(bike)
    assert s["pace_unit_m"] == 1000 and s["pace_str"] == "2:00.0" and s["watts"] is None


# ----------------------------------------------------------------------------
# Token-Logik (ohne Netz)
# ----------------------------------------------------------------------------


@pytest.fixture
def token_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONCEPT2_TOKENS", str(tmp_path))
    for k in ("CONCEPT2_TOKENS_B64", "CONCEPT2_TOKENS_JSON", "CONCEPT2_CLIENT_ID", "CONCEPT2_CLIENT_SECRET", "CONCEPT2_DEV", "CONCEPT2_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_materialize_from_env(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    import base64

    blob = base64.b64encode(json.dumps({"access_token": "a", "refresh_token": "r", "client_id": "cid", "client_secret": "sec"}).encode()).decode()
    monkeypatch.setenv("CONCEPT2_TOKENS_B64", blob)
    assert not c2.tokens_present()
    assert c2.materialize_tokens_from_env() is True
    assert c2.tokens_present() and c2.load_tokens()["refresh_token"] == "r"
    assert c2.client_credentials() == ("cid", "sec")
    assert c2.token_blob_b64() and c2.materialize_tokens_from_env() is False


def test_authorize_url_and_hosts(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONCEPT2_CLIENT_ID", "abc")
    monkeypatch.setenv("CONCEPT2_CLIENT_SECRET", "xyz")
    url = c2.authorize_url("state123")
    assert url.startswith("https://log.concept2.com/oauth/authorize?")
    assert "client_id=abc" in url and "scope=user%3Aread%2Cresults%3Aread" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback" in url and "state=state123" in url
    monkeypatch.setenv("CONCEPT2_DEV", "1")
    assert c2.api_base() == "https://log-dev.concept2.com/api"


def test_access_token_refreshes_when_stale(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    c2.save_tokens({"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 10, "client_id": "cid", "client_secret": "sec"})
    calls: list[dict] = []

    def fake_post(form):
        calls.append(form)
        return {"access_token": "new", "refresh_token": "r2", "expires_in": 3600, "token_type": "Bearer"}

    monkeypatch.setattr(c2, "_post_token", fake_post)
    assert c2.access_token() == "new"
    assert calls[0]["grant_type"] == "refresh_token" and calls[0]["refresh_token"] == "r1"
    saved = c2.load_tokens()
    assert saved["refresh_token"] == "r2" and saved["expires_at"] > time.time() + 3000
    assert c2.access_token() == "new" and len(calls) == 1  # noch gültig → kein zweiter Aufruf


def test_access_token_missing(token_env: Path):
    with pytest.raises(c2.Concept2AuthError):
        c2.access_token()


def test_client_retries_once_on_401(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    c2.save_tokens({"access_token": "t1", "refresh_token": "r", "expires_at": time.time() + 3600, "client_id": "cid", "client_secret": "sec"})
    monkeypatch.setattr(c2, "_post_token", lambda form: {"access_token": "t2", "refresh_token": "r", "expires_in": 3600})

    class Resp:
        def __init__(self, status, payload):
            self.status_code, self._p, self.text, self.content = status, payload, json.dumps(payload), b""

        def json(self):
            return self._p

    seen: list[str] = []

    class FakeSession:
        headers: dict = {}

        def get(self, url, params=None, headers=None, timeout=None):
            seen.append(headers["Authorization"])
            return Resp(401, {"message": "expired"}) if headers["Authorization"].endswith("t1") else Resp(200, {"data": {"username": "marq", "first_name": "Marq"}})

    client = c2.Concept2Client.__new__(c2.Concept2Client)
    client._s, client.timeout_s = FakeSession(), 5
    assert client.me()["username"] == "marq"
    assert seen == ["Bearer t1", "Bearer t2"]
    assert c2.whoami(client) == "Marq"
