"""Tests für scripts/archiv.py (ohne Netz, mit temporärem Git-Repo)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import archiv  # noqa: E402


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    g, c = tmp_path / "garmin", tmp_path / "concept2"
    (g / "2026-09-20_111").mkdir(parents=True)
    (g / "2026-09-20_111" / "summary.md").write_text("# Lauf\n", encoding="utf-8")
    (g / "2026-09-20_111" / "raw").mkdir()
    (g / "2026-09-20_111" / "raw" / "activity.json").write_text("{}", encoding="utf-8")
    (c / "2026-09-20_222").mkdir(parents=True)
    (c / "2026-09-20_222" / "coach.txt").write_text("Rudern 5000 m\nRPE: (bitte ergänzen)\n", encoding="utf-8")
    (c / "2026-09-20_long_distanz_kombiniert.md").write_text("# Kombiniert\n", encoding="utf-8")
    (c / "2026-09-19_333").mkdir()  # anderer Tag, darf nicht mitkommen
    monkeypatch.setenv("LAUFANALYSE_DATA_DIR", str(g))
    monkeypatch.setenv("CONCEPT2_DATA_DIR", str(c))
    foto = tmp_path / "pm5.jpg"
    foto.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
    repo = tmp_path / "archiv"
    repo.mkdir()
    return repo, foto


def test_archive_day_collects_and_writes(env):
    repo, foto = env
    m = archiv.archive_day("2026-09-20", repo=repo, titel="Hyrox Training", fotos=[(foto, "PM5 SkiErg")], note="Test")
    d = repo / "2026" / "2026-09-20 Hyrox Training"
    assert (d / "garmin" / "2026-09-20_111" / "raw" / "activity.json").is_file()
    assert (d / "concept2" / "2026-09-20_222" / "coach.txt").is_file()
    assert (d / "concept2" / "2026-09-20_long_distanz_kombiniert.md").is_file()
    assert not (d / "concept2" / "2026-09-19_333").exists()
    assert (d / "fotos" / "2026-09-20_foto-01.jpg").is_file()
    assert "| 2026-09-20_foto-01.jpg | PM5 SkiErg |" in (d / "fotos" / "index.md").read_text(encoding="utf-8")
    assert (d / "auswertung.md").read_text(encoding="utf-8").startswith("# Kombiniert")
    assert "RPE: (bitte ergänzen)" in (d / "coach.txt").read_text(encoding="utf-8")
    idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
    assert idx["garmin"] == ["2026-09-20_111"] and idx["note"] == "Test" and len(idx["fotos"]) == 1
    assert idx["titel"] == "Hyrox Training"
    assert m["dest"] == str(d) and any("foto:" in line for line in m["log"])


def test_archive_day_is_idempotent_and_dedupes_fotos(env):
    repo, foto = env
    archiv.archive_day("2026-09-20", repo=repo, fotos=[(foto, "PM5")])
    m = archiv.archive_day("2026-09-20", repo=repo, fotos=[(foto, "nochmal")], coach="Text an Coach\nRPE: 5")
    d = repo / "2026" / "2026-09-20 Training"  # ohne Titel: Standard "Training", zweiter Aufruf nutzt den Ordner weiter
    assert len(list((d / "fotos").glob("*.jpg"))) == 1
    assert any("schon vorhanden" in line for line in m["log"])
    assert (d / "coach.txt").read_text(encoding="utf-8") == "Text an Coach\nRPE: 5\n"
    # dritter Aufruf ohne Coach-Text: der echte Text bleibt, die automatische Vorstufe ersetzt ihn nicht
    m3 = archiv.archive_day("2026-09-20", repo=repo, titel="Hyrox Training")
    assert (d.parent / "2026-09-20 Hyrox Training" / "coach.txt").read_text(encoding="utf-8") == "Text an Coach\nRPE: 5\n"
    assert not any(line.startswith("coach.txt") for line in m3["log"])
    idx = json.loads((d.parent / "2026-09-20 Hyrox Training" / "index.json").read_text(encoding="utf-8"))
    assert len(idx["fotos"]) == 1 and idx["files"] == ["auswertung.md", "coach.txt"]


def test_titel_renames_existing_folder(env):
    repo, foto = env
    (repo / "2026" / "2026-09-20").mkdir(parents=True)  # alter Ordner ohne Titel
    (repo / "2026" / "2026-09-20" / "coach.txt").write_text("alt\n", encoding="utf-8")
    m = archiv.archive_day("2026-09-20", repo=repo, titel="Hyrox  Training", fotos=[(foto, "x")])
    d = repo / "2026" / "2026-09-20 Hyrox Training"
    assert d.is_dir() and not (repo / "2026" / "2026-09-20").exists()
    assert (d / "coach.txt").read_text(encoding="utf-8").startswith("Text") or (d / "coach.txt").read_text(encoding="utf-8")
    assert any(line.startswith("ordner: 2026-09-20 → 2026-09-20 Hyrox Training") for line in m["log"])
    # ohne neuen Titel bleibt der Name; Ordner wird gefunden
    m2 = archiv.archive_day("2026-09-20", repo=repo)
    assert m2["dest"] == str(d) and m2["titel"] == "Hyrox Training"
    assert archiv.day_dir(repo, "2026-09-20") == d and archiv.day_dir(repo, "2026-09-19") is None
    assert archiv.folder_name("2026-09-20", "A/B") == "2026-09-20 A-B"


def test_dry_run_writes_nothing(env):
    repo, foto = env
    m = archiv.archive_day("2026-09-20", repo=repo, fotos=[(foto, "x")], dry_run=True)
    assert not (repo / "2026").exists() and m["log"]


def test_errors(env):
    repo, foto = env
    with pytest.raises(ValueError):
        archiv.archive_day("20.09.2026", repo=repo)
    with pytest.raises(FileNotFoundError):
        archiv.archive_day("2026-09-20", repo=repo, fotos=[(repo / "fehlt.jpg", "")])
    bad = repo / "x.txt"
    bad.write_text("x")
    with pytest.raises(ValueError, match="Bildformat"):
        archiv.archive_day("2026-09-20", repo=repo, fotos=[(bad, "")])


def test_git_push_local(env, tmp_path: Path):
    repo, foto = env
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "-u", "origin", "main"], check=True)
    archiv.archive_day("2026-09-20", repo=repo, titel="Hyrox Training", fotos=[(foto, "PM5")])
    out = archiv.git_push(repo, "2026-09-20")
    assert out.startswith("gepusht:") and "2026-09-20 Hyrox Training" in out
    assert archiv.git_push(repo, "2026-09-20") == "nichts zu committen"
    # Umbenennung per git mv wird mitgepusht
    archiv.archive_day("2026-09-20", repo=repo, titel="Long Distanz")
    assert "2026-09-20 Long Distanz" in archiv.git_push(repo, "2026-09-20")
    log = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline"], capture_output=True, text=True).stdout
    assert "2026-09-20 Hyrox Training" in log and "2026-09-20 Long Distanz" in log
    assert archiv.git_push(repo, "2026-09-19").startswith("nichts zu committen")


def test_parse_foto_arg():
    p, d = archiv.parse_foto_arg("/tmp/a.jpg=PM5 Ski Erg=5x1000")
    assert p == Path("/tmp/a.jpg") and d == "PM5 Ski Erg=5x1000"
    assert archiv.parse_foto_arg("b.jpg")[1] == ""
