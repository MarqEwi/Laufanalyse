"""Trainingsarchiv: einen Trainingstag in das private Archiv-Repo legen (Ordner pro Tag), das die NAS abholt.

Ablage im Archiv-Repo (z. B. MarqEwi/training-archiv, privat):

    <Jahr>/<YYYY-MM-DD> <Titel>/      z. B. 2026/2026-09-20 Hyrox Training
      fotos/            PM5-Fotos, Coach-Screenshots (+ index.md mit Beschreibung je Bild)
      garmin/<ordner>/  Kopie von data/garmin/<datum>_<id>/ (summary.md, analysis.json, laps.csv, timeseries.csv, raw/)
      concept2/<ordner>/ Kopie von data/concept2/<datum>_<id>/ und *_kombiniert.md
      auswertung.md     Tagesauswertung (übergeben oder aus *_kombiniert.md übernommen)
      coach.txt         Textbaustein an den Coach (übergeben oder aus concept2/coach.txt übernommen)
      index.json        Manifest: Quellen, Dateien, Zeitstempel

Beispiele:
    uv run scripts/archiv.py --date 2026-09-20 --titel "Hyrox Training" --foto ski.jpg=Ski Erg 5x1000m --push
    uv run scripts/archiv.py --date 2026-09-20 --auswertung auswertung.md --coach coach.txt --push
    uv run scripts/archiv.py --date 2026-09-20 --dry-run           # nur zeigen, was kopiert würde

Ordnername: "<YYYY-MM-DD> <Titel>" (Wunsch des Nutzers, z. B. "2026-09-20 Hyrox Training"). Gibt es zum Datum
schon einen Ordner, wird er weiterverwendet; mit --titel wird er umbenannt (git mv, sonst rename).
Ohne Titel heißt ein neuer Ordner "<YYYY-MM-DD> Training".

Archiv-Repo: --repo, sonst $TRAINING_ARCHIV_DIR, sonst ../training-archiv neben diesem Repo.
Datenquellen: $LAUFANALYSE_DATA_DIR (./data/garmin), $CONCEPT2_DATA_DIR (./data/concept2).
Auf der NAS zieht der Container nas/training-sync das Repo nach /volume1/Grundlagen/training/archiv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def archiv_dir(repo: str | None) -> Path:
    raw = repo or os.environ.get("TRAINING_ARCHIV_DIR")
    if raw:
        return Path(raw).expanduser()
    return ROOT.parent / "training-archiv"


def _data_dirs() -> tuple[Path, Path]:
    g = Path(os.environ.get("LAUFANALYSE_DATA_DIR") or ROOT / "data" / "garmin")
    c = Path(os.environ.get("CONCEPT2_DATA_DIR") or ROOT / "data" / "concept2")
    return g, c


def _sha1(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _copy_tree(src: Path, dst: Path, dry: bool, log: list[str]) -> None:
    for p in sorted(src.rglob("*")):
        if p.is_file():
            rel = p.relative_to(src)
            log.append(f"  {dst.name}/{rel}")
            if not dry:
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst / rel)


def day_dir(repo: Path, day: str) -> Path | None:
    """Vorhandener Tagesordner zum Datum ("<Jahr>/<YYYY-MM-DD>" oder "<Jahr>/<YYYY-MM-DD> <Titel>"), sonst None."""
    year = repo / day[:4]
    if not year.is_dir():
        return None
    hits = sorted(d for d in year.iterdir() if d.is_dir() and (d.name == day or d.name.startswith(day + " ")))
    return hits[0] if hits else None


def folder_name(day: str, titel: str | None) -> str:
    t = " ".join((titel or "Training").split()).replace("/", "-")
    return f"{day} {t}"


def _rename(repo: Path, src: Path, dst: Path) -> None:
    if (repo / ".git").is_dir():
        r = subprocess.run(["git", "-C", str(repo), "mv", "-k", str(src.relative_to(repo)), str(dst.relative_to(repo))], capture_output=True, text=True)
        if r.returncode == 0 and dst.exists() and not src.exists():
            return
    src.rename(dst)


def parse_foto_arg(arg: str) -> tuple[Path, str]:
    """'pfad=Beschreibung' oder nur 'pfad'."""
    path, _, desc = arg.partition("=")
    return Path(path).expanduser(), desc.strip()


def archive_day(
    day: str,
    *,
    repo: Path,
    titel: str | None = None,
    fotos: list[tuple[Path, str]] | None = None,
    auswertung: Path | str | None = None,
    coach: Path | str | None = None,
    note: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sammelt alles zum Tag und schreibt es in <repo>/<Jahr>/<Tag> <Titel>/. Liefert Manifest und Protokoll."""
    datetime.strptime(day, "%Y-%m-%d")
    gdir, cdir = _data_dirs()
    log: list[str] = []
    existing_dir = day_dir(repo, day)
    if existing_dir is not None:
        dest = existing_dir
        wanted = repo / day[:4] / folder_name(day, titel)
        if titel and wanted != existing_dir:
            log.append(f"ordner: {existing_dir.name} → {wanted.name}")
            if not dry_run:
                _rename(repo, existing_dir, wanted)
            dest = wanted
    else:
        dest = repo / day[:4] / folder_name(day, titel)
    manifest: dict[str, Any] = {"date": day, "titel": dest.name[len(day):].strip() or None, "written_at": datetime.now().isoformat(timespec="seconds"), "garmin": [], "concept2": [], "fotos": [], "files": []}

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    # Garmin- und Concept2-Ordner des Tages
    for base, key in ((gdir, "garmin"), (cdir, "concept2")):
        if base.exists():
            for d in sorted(base.glob(f"{day}_*")):
                if d.is_dir():
                    manifest[key].append(d.name)
                    log.append(f"{key}: {d.name}")
                    _copy_tree(d, dest / key / d.name, dry_run, log)
                elif d.is_file() and d.suffix == ".md":
                    manifest[key].append(d.name)
                    log.append(f"{key}: {d.name}")
                    if not dry_run:
                        (dest / key).mkdir(parents=True, exist_ok=True)
                        shutil.copy2(d, dest / key / d.name)

    # Fotos
    existing = {}
    idx = dest / "fotos" / "index.md"
    if idx.is_file():
        for line in idx.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and not line.startswith("| Datei"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 3:
                    existing[cells[2]] = cells[0]
    rows = []
    for p, desc in fotos or []:
        if not p.is_file():
            raise FileNotFoundError(f"Foto nicht gefunden: {p}")
        if p.suffix.lower() not in FOTO_EXT:
            raise ValueError(f"Kein Bildformat: {p.name}")
        digest = _sha1(p)
        if digest in existing:
            log.append(f"foto: {p.name} schon vorhanden als {existing[digest]}")
            continue
        n = len(existing) + len(rows) + 1
        name = f"{day}_foto-{n:02d}{p.suffix.lower()}"
        rows.append((name, desc or p.stem, digest))
        manifest["fotos"].append({"file": name, "description": desc, "sha1": digest, "source": p.name})
        log.append(f"foto: {p.name} → fotos/{name}" + (f" ({desc})" if desc else ""))
        if not dry_run:
            (dest / "fotos").mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / "fotos" / name)
    if rows and not dry_run:
        new = not idx.is_file()
        with idx.open("a", encoding="utf-8") as f:
            if new:
                f.write(f"# Fotos {day}\n\n| Datei | Beschreibung | sha1 |\n|---|---|---|\n")
            for name, desc, digest in rows:
                f.write(f"| {name} | {desc} | {digest} |\n")

    # Auswertung und Coach-Text: übergeben, sonst aus den Concept2-Dateien übernehmen
    def _text(v: Path | str | None) -> str | None:
        if v is None:
            return None
        p = Path(v) if not isinstance(v, Path) else v
        if isinstance(v, str) and ("\n" in v or not p.exists()):
            return v
        return p.read_text(encoding="utf-8")

    # Automatische Vorstufen (kombiniert.md, concept2/coach.txt) nur, wenn die Datei im Archiv noch fehlt –
    # ein bereits abgelegter Coach-Text (mit RPE) wird nur durch ausdrücklich übergebenen Inhalt ersetzt.
    ausw = _text(auswertung)
    if ausw is None and cdir.exists() and not (dest / "auswertung.md").is_file():
        cands = sorted(cdir.glob(f"{day}_*kombiniert*.md"))
        if cands:
            ausw = cands[0].read_text(encoding="utf-8")
    coach_txt = _text(coach)
    if coach_txt is None and cdir.exists() and not (dest / "coach.txt").is_file():
        cands = [p for p in sorted(cdir.glob(f"{day}_*/coach.txt"))]
        if cands:
            coach_txt = "\n\n".join(p.read_text(encoding="utf-8").strip() for p in cands)
    for fname, content in (("auswertung.md", ausw), ("coach.txt", coach_txt)):
        if content:
            log.append(f"{fname}: {len(content)} Zeichen" + (" (ersetzt)" if (dest / fname).is_file() else ""))
            manifest["files"].append(fname)
            if not dry_run:
                (dest / fname).write_text(content.rstrip() + "\n", encoding="utf-8")
    if note:
        manifest["note"] = note
    if not manifest["titel"]:
        manifest.pop("titel")

    if not dry_run:
        old = {}
        mf = dest / "index.json"
        if mf.is_file():
            try:
                old = json.loads(mf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                old = {}
        for k in ("garmin", "concept2", "files"):
            manifest[k] = sorted(set(old.get(k, [])) | set(manifest[k]))
        manifest["fotos"] = old.get("fotos", []) + manifest["fotos"]
        mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["dest"] = str(dest)
    manifest["log"] = log
    return manifest


def git_push(repo: Path, day: str, message: str | None = None) -> str:
    """git add/commit/push im Archiv-Repo. Liefert Kurzprotokoll."""
    if not (repo / ".git").is_dir():
        raise RuntimeError(f"{repo} ist kein Git-Repo. Archiv-Repo klonen oder TRAINING_ARCHIV_DIR setzen.")

    def run(*args: str) -> str:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout.strip()

    d = day_dir(repo, day)
    if d is None:
        return f"nichts zu committen (kein Ordner für {day})"
    run("add", "-A", day[:4])
    if not run("status", "--porcelain", day[:4]):
        return "nichts zu committen"
    run("commit", "-q", "-m", message or d.name)
    run("push", "-q")
    return f"gepusht: {run('log', '-1', '--format=%h %s')}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=_date.today().isoformat(), help="Trainingstag YYYY-MM-DD (Standard heute)")
    ap.add_argument("--repo", help="Archiv-Repo (Standard $TRAINING_ARCHIV_DIR oder ../training-archiv)")
    ap.add_argument("--titel", help='Ordnertitel, z. B. "Hyrox Training" → Ordner "2026-09-20 Hyrox Training"')
    ap.add_argument("--foto", action="append", default=[], metavar="PFAD[=Beschreibung]", help="Foto hinzufügen (mehrfach)")
    ap.add_argument("--auswertung", help="Datei mit der Tagesauswertung (Markdown)")
    ap.add_argument("--coach", help="Datei mit dem Coach-Text")
    ap.add_argument("--note", help="Notiz ins Manifest")
    ap.add_argument("--push", action="store_true", help="im Archiv-Repo committen und pushen")
    ap.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts schreiben")
    a = ap.parse_args()
    repo = archiv_dir(a.repo)
    if not a.dry_run and not repo.is_dir():
        print(f"Archiv-Repo nicht gefunden: {repo}", file=sys.stderr)
        return 1
    try:
        m = archive_day(a.date, repo=repo, titel=a.titel, fotos=[parse_foto_arg(f) for f in a.foto], auswertung=a.auswertung, coach=a.coach, note=a.note, dry_run=a.dry_run)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    print(("Würde schreiben nach " if a.dry_run else "Geschrieben nach ") + m["dest"])
    for line in m["log"]:
        print("  " + line)
    if not m["log"]:
        print("  (nichts gefunden – Datum prüfen oder Fotos/Auswertung übergeben)")
    if a.push and not a.dry_run:
        try:
            print(git_push(repo, a.date))
        except RuntimeError as exc:
            print(f"Push fehlgeschlagen: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
