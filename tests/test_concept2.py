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


def test_validator_sample_variable_interval():
    """Beispiel aus dem Concept2 'API Workout Validator': Intervalle ohne rest_time, HF average=0, VariableInterval."""
    sample = {"id": 5, "type": "rower", "date": "2017-12-30 17:01:00", "distance": 369, "time": 900, "rest_distance": 6592,
              "rest_time": 17100, "weight_class": "H", "verified": True, "comments": "", "stroke_rate": 23,
              "workout_type": "VariableInterval", "heart_rate": {"ending": 138, "average": 132},
              "workout": {"intervals": [
                  {"time": 300, "distance": 132, "calories_total": 9, "stroke_rate": 24, "heart_rate": {"average": 0, "ending": 108}, "type": "time"},
                  {"type": "calorie", "time": 300, "distance": 119, "calories_total": 7, "stroke_rate": 23, "heart_rate": {"average": 0, "ending": 127}},
                  {"type": "time", "time": 300, "distance": 118, "calories_total": 7, "stroke_rate": 23, "heart_rate": {"average": 0, "ending": 135}}]}}
    a, _ = ce.analyze(sample, [{"t": 0, "d": 0, "p": 0, "spm": 0}, {"t": 10, "d": 20, "p": 100, "spm": 25}, {"t": 20, "d": 40, "p": 130, "spm": 25}])
    s = a["summary"]
    assert s["time_s"] == 90.0 and s["rest_time_s"] == 1710.0 and s["hr_avg"] == 132
    segs = a["segments"]
    assert len(segs) == 3 and all(g["hr_avg"] is None for g in segs)  # average=0 → keine HF
    assert [g["hr_end"] for g in segs] == [108, 127, 135]
    assert all(g["rest_source"].startswith("unbekannt") for g in segs)
    assert any("Pause je Intervall nicht geliefert" in n for n in a["notes"])
    assert a["intervals_stats"]["count"] == 3 and a["intervals_stats"]["avg_hr"] is None
    ce.render_markdown(a)  # darf ohne HF nicht abstürzen


def test_fixed_interval_rest_distributed():
    res = {"id": 6, "type": "skierg", "date": "2026-09-21 08:00:00", "distance": 2000, "time": 4800, "rest_time": 2400,
           "workout_type": "FixedDistanceInterval", "heart_rate": {},
           "workout": {"intervals": [{"type": "distance", "time": 2400, "distance": 1000}, {"type": "distance", "time": 2400, "distance": 1000}]}}
    a, _ = ce.analyze(res, None)
    segs = a["segments"]
    assert [g["rest_time_s"] for g in segs] == [120.0, 120.0]
    assert [g["start_s"] for g in segs] == [0.0, 360.0]
    assert a["intervals_stats"]["avg_rest_s"] == 120.0
    assert any("gleichmäßig" in n for n in a["notes"])


def test_parse_time():
    assert ce.parse_time("4:17.1") == 257.1
    assert ce.parse_time("r4:50") == 290.0
    assert ce.parse_time("1:02:05.0") == 3725.0
    assert ce.parse_time(90) == 90.0 and ce.parse_time(None) == 0.0
    with pytest.raises(ValueError):
        ce.parse_time("abc")


def test_manual_skierg_from_photo(tmp_path: Path):
    """Ski-Erg-Foto vom 20.09.2026: 5×1000 m, PM5 zeigt 21:37.5 / 2:09.7 / 39 spm, Laufzeit 50:20.5."""
    spec = {"type": "skierg", "date": "2026-09-20 16:09", "drag_factor": 110, "comments": "PM5-Foto",
            "intervals": [
                {"time": "4:17.1", "distance": 1000, "spm": 43, "rest": "4:50", "rest_distance": 13},
                {"time": "4:12.7", "distance": 1000, "spm": 39, "rest": "5:03", "rest_distance": 17},
                {"time": "4:19.1", "distance": 1000, "spm": 38, "rest": "4:23", "rest_distance": 8},
                {"time": "4:21.7", "distance": 1000, "spm": 38, "rest": "4:27", "rest_distance": 15},
                {"time": "4:26.9", "distance": 1000, "spm": 38, "rest": "10:00", "rest_distance": 13}]}
    r = ce.manual_to_result(spec)
    assert r["distance"] == 5000 and r["time"] == 12975 and r["time_formatted"] == "21:37.5"
    assert r["time"] + r["rest_time"] == _tenths_total(50 * 60 + 20.5)
    assert r["workout_type"] == "VariableInterval" and r["stroke_rate"] == 39 and r["id"] == "foto-20260920-1609"
    out, a = ce.analyze_manual(spec, rpe=5, out_dir=str(tmp_path))
    s, iv = a["summary"], a["intervals_stats"]
    assert s["pace_str"] == "2:09.8" and iv["count"] == 5 and iv["avg_pace_str"] == "2:09.8"
    assert iv["pace_trend_s_per_interval"] > 0 and "langsamer" in iv["trend_text"]
    assert a["notes"][0].startswith("Quelle: PM5-Foto")
    assert (out / "summary.md").is_file() and (out / "raw" / "manual_spec.json").is_file()
    assert out.name == "2026-09-20_foto-20260920-1609"
    txt = ce.coach_text(a)
    assert "Ski Erg 2026-09-20: 5000 m in 21:37.5" in txt and "RPE: 5" in txt
    assert ce.list_exported(tmp_path)[0]["result_id"] == "foto-20260920-1609"


def _tenths_total(sec: float) -> int:
    return int(round(sec * 10))


def test_manual_bike_splits_and_errors():
    spec = {"type": "bike", "date": "2026-09-20 15:28", "splits": [
        {"time": "4:32.2", "distance": 2000, "spm": 66}, {"time": "4:07.6", "distance": 2000, "spm": 72},
        {"time": "4:08.8", "distance": 2000, "spm": 72}, {"time": "4:09.2", "distance": 2000, "spm": 72},
        {"time": "4:12.3", "distance": 2000, "spm": 71}]}
    r = ce.manual_to_result(spec)
    assert r["distance"] == 10000 and r["time_formatted"] == "21:10.1" and r["workout_type"] == "FixedDistanceSplits"
    a, _ = ce.analyze(r, None)
    assert a["summary"]["pace_unit_m"] == 1000 and a["splits"][0]["pace_str"] == "2:16.1" and not a["is_interval_session"]
    with pytest.raises(ValueError, match="type"):
        ce.manual_to_result({"type": "treadmill", "date": "2026-09-20 10:00", "splits": [{"time": "1:00", "distance": 100}]})
    with pytest.raises(ValueError, match="date"):
        ce.manual_to_result({"type": "rower", "date": "gestern", "splits": [{"time": "1:00", "distance": 100}]})
    with pytest.raises(ValueError, match="intervals oder splits"):
        ce.manual_to_result({"type": "rower", "date": "2026-09-20 10:00"})


def test_upload_body_matches_validator_format():
    spec = {"type": "skierg", "date": "2026-09-20 16:09", "intervals": [
        {"time": "4:17.1", "distance": 1000, "spm": 43, "rest": "4:50", "rest_distance": 13},
        {"time": "4:12.7", "distance": 1000, "spm": 39, "rest": "5:03", "rest_distance": 17}], "comments": "x"}
    body = ce.upload_body(ce.manual_to_result(spec))
    assert body["type"] == "skierg" and body["date"] == "2026-09-20 16:09:00" and body["timezone"] == "Europe/Berlin"
    assert body["distance"] == 2000 and body["time"] == 5098 and body["rest_time"] == 5930 and body["rest_distance"] == 30
    assert body["workout_type"] == "VariableInterval" and body["weight_class"] == "H" and body["verified"] is False
    assert "id" not in body and "time_formatted" not in body and "source" not in body and "heart_rate" not in body
    iv = body["workout"]["intervals"]
    assert iv[0] == {"type": "distance", "time": 2571, "distance": 1000, "stroke_rate": 43, "rest_time": 2900, "rest_distance": 13}
    assert "heart_rate" not in iv[0] and "calories_total" not in iv[0]


def test_dev_mode_separates_tokens_and_credentials(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONCEPT2_CLIENT_ID", "live-id")
    monkeypatch.setenv("CONCEPT2_CLIENT_SECRET", "live-sec")
    assert c2.client_credentials() == ("live-id", "live-sec")
    monkeypatch.setenv("CONCEPT2_DEV", "1")
    for k in ("CONCEPT2_DEV_TOKENS", "CONCEPT2_DEV_CLIENT_ID", "CONCEPT2_DEV_CLIENT_SECRET", "CONCEPT2_DEV_TOKENS_B64"):
        monkeypatch.delenv(k, raising=False)  # echte Dev-Zugangsdaten der Umgebung ausblenden
    assert c2.is_dev() and c2.token_dir() != token_env and c2.token_dir().name.endswith("-dev")
    monkeypatch.setenv("CONCEPT2_DEV_TOKENS", str(token_env / "devtok"))  # leerer Ordner, keine echten Dev-Tokens
    assert c2.token_dir() == token_env / "devtok"
    with pytest.raises(c2.Concept2AuthError, match="CONCEPT2_DEV_CLIENT_ID"):
        c2.client_credentials()  # Live-Variablen werden im Dev-Modus ignoriert
    monkeypatch.setenv("CONCEPT2_DEV_CLIENT_ID", "dev-id")
    monkeypatch.setenv("CONCEPT2_DEV_CLIENT_SECRET", "dev-sec")
    assert c2.client_credentials() == ("dev-id", "dev-sec")
    import base64
    monkeypatch.setenv("CONCEPT2_TOKENS_B64", base64.b64encode(b'{"access_token": "LIVE", "refresh_token": "r"}').decode())
    assert c2.materialize_tokens_from_env() is False  # Live-Blob wird im Dev-Modus nicht in den Dev-Ordner geschrieben
    monkeypatch.setenv("CONCEPT2_DEV_TOKENS_B64", base64.b64encode(b'{"access_token": "DEV", "refresh_token": "r"}').decode())
    assert c2.materialize_tokens_from_env() is True and c2.load_tokens()["access_token"] == "DEV"


def test_client_post_and_delete(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    c2.save_tokens({"access_token": "t1", "refresh_token": "r", "expires_at": time.time() + 3600, "client_id": "cid", "client_secret": "sec"})
    calls: list[tuple] = []

    class Resp:
        def __init__(self, status, payload=None):
            self.status_code, self._p = status, payload
            self.content = b"" if payload is None else b"x"
            self.text = json.dumps(payload or {})

        def json(self):
            return self._p

    class FakeSession:
        def request(self, method, url, params=None, json=None, headers=None, timeout=None):
            calls.append((method, url, json))
            return Resp(201, {"data": {"id": 86969, **json}}) if method == "POST" else Resp(204)

    client = c2.Concept2Client.__new__(c2.Concept2Client)
    client._s, client.timeout_s = FakeSession(), 5
    created = client.create_result({"type": "rower", "distance": 500})
    assert created["id"] == 86969 and calls[0][0] == "POST" and calls[0][1].endswith("/users/me/results")
    assert client.delete_result(86969) is None and calls[1][0] == "DELETE" and calls[1][1].endswith("/users/me/results/86969")


def test_compact_and_bike_pace():
    res = _load("result_steady.json")["data"]
    c = ce.compact(res)
    assert set(c) >= {"result_id", "date", "type", "distance_m", "time_str", "pace_str", "hr_avg"}
    bike = {"id": 1, "date": "2026-09-01 10:00:00", "type": "bike", "distance": 10000, "time": 12000, "heart_rate": {}}
    s = ce.normalize_summary(bike)
    assert s["pace_unit_m"] == 1000 and s["pace_str"] == "2:00.0" and round(s["watts"]) == 203


def test_bike_watts_match_concept2_validator():
    """API Workout Validator (log-dev, 20.09.2026): Bike 1 → 171 W gesamt, Splits 139/184/182/181/174 W."""
    spec = {"type": "bike", "date": "2026-09-20 15:28", "splits": [
        {"time": "4:32.2", "distance": 2000, "spm": 66}, {"time": "4:07.6", "distance": 2000, "spm": 72},
        {"time": "4:08.8", "distance": 2000, "spm": 72}, {"time": "4:09.2", "distance": 2000, "spm": 72}, {"time": "4:12.3", "distance": 2000, "spm": 71}]}
    a, _ = ce.analyze(ce.manual_to_result(spec), None)
    assert round(a["summary"]["watts"]) == 171
    assert [round(s["watts"]) for s in a["splits"]] == [139, 184, 182, 181, 174]
    body = ce.upload_body(ce.manual_to_result({**spec, "stroke_count": 1494, "drag_factor": 102}))
    assert body["stroke_count"] == 1494 and body["drag_factor"] == 102


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
    monkeypatch.setattr(c2, "REFRESHED_IN_SESSION", False)
    assert c2.refresh_hint() is None
    assert c2.access_token() == "new"
    assert calls[0]["grant_type"] == "refresh_token" and calls[0]["refresh_token"] == "r1"
    saved = c2.load_tokens()
    assert saved["refresh_token"] == "r2" and saved["expires_at"] > time.time() + 3000
    assert c2.access_token() == "new" and len(calls) == 1  # noch gültig → kein zweiter Aufruf
    assert c2.REFRESHED_IN_SESSION and "CONCEPT2_TOKENS_B64" in c2.refresh_hint()


def test_parse_code():
    url = "http://localhost:8765/callback?code=abc123&state=s1"
    assert c2.parse_code(url, "s1") == "abc123"
    assert c2.parse_code(url, None) == "abc123"
    assert c2.parse_code("  rawcode ", "s1") == "rawcode"
    with pytest.raises(c2.Concept2AuthError):
        c2.parse_code(url, "other")
    with pytest.raises(c2.Concept2AuthError):
        c2.parse_code("http://localhost:8765/callback?error=access_denied&code=", "s1")
    with pytest.raises(c2.Concept2AuthError):
        c2.parse_code("", "s1")


def test_exchange_code_stores_tokens(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONCEPT2_CLIENT_ID", "cid")
    monkeypatch.setenv("CONCEPT2_CLIENT_SECRET", "sec")
    seen: list[dict] = []

    def fake_post(form):
        seen.append(form)
        return {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600, "scope": "user:read,results:read"}

    monkeypatch.setattr(c2, "_post_token", fake_post)
    tokens = c2.exchange_code("thecode")
    assert seen[0]["grant_type"] == "authorization_code" and seen[0]["code"] == "thecode"
    assert seen[0]["redirect_uri"] == "http://localhost:8765/callback"
    assert tokens["client_id"] == "cid" and tokens["client_secret"] == "sec"
    assert c2.load_tokens()["access_token"] == "a1"
    assert c2.token_blob_b64()


def test_access_token_missing(token_env: Path):
    with pytest.raises(c2.Concept2AuthError):
        c2.access_token()


def test_client_retries_once_on_401(token_env: Path, monkeypatch: pytest.MonkeyPatch):
    c2.save_tokens({"access_token": "t1", "refresh_token": "r", "expires_at": time.time() + 3600, "client_id": "cid", "client_secret": "sec"})
    monkeypatch.setattr(c2, "_post_token", lambda form: {"access_token": "t2", "refresh_token": "r", "expires_in": 3600})

    class Resp:
        def __init__(self, status, payload):
            self.status_code, self._p, self.text, self.content = status, payload, json.dumps(payload), b"x"

        def json(self):
            return self._p

    seen: list[str] = []

    class FakeSession:
        headers: dict = {}

        def request(self, method, url, params=None, json=None, headers=None, timeout=None):
            seen.append(headers["Authorization"])
            return Resp(401, {"message": "expired"}) if headers["Authorization"].endswith("t1") else Resp(200, {"data": {"username": "marq", "first_name": "Marq"}})

    client = c2.Concept2Client.__new__(c2.Concept2Client)
    client._s, client.timeout_s = FakeSession(), 5
    assert client.me()["username"] == "marq"
    assert seen == ["Bearer t1", "Bearer t2"]
    assert c2.whoami(client) == "Marq"
