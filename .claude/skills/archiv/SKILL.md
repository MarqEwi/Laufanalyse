---
name: archiv
description: Legt einen Trainingstag im privaten Trainingsarchiv ab (Repo MarqEwi/training-archiv, von der NAS STEVENAS gespiegelt) – Fotos vom PM5 oder Coach-Plan mit Beschreibung, Garmin- und Concept2-Exporte des Tages, Tagesauswertung und Coach-Text. Nutzen, wenn der Nutzer Bilder oder Auswertungen „auf die NAS“, „ins Archiv“ oder „ablegen“ will, oder nach einer Auswertung zum Abschluss des Tages. Deutsch.
argument-hint: "[YYYY-MM-DD, Standard heute] [Titel, z. B. Hyrox Training] [Beschreibung der Bilder]"
---

# Trainingsarchiv (NAS)

Ziel: Jeder Trainingstag liegt als Ordner `<Jahr>/<YYYY-MM-DD> <Titel>/` (z. B. `2026/2026-09-20 Hyrox Training`)
im privaten Repo `MarqEwi/training-archiv`.
Die NAS STEVENAS zieht das Repo alle 10 Minuten nach `/volume1/Grundlagen/training/archiv` (Container
`nas/training-sync`). Skript: `scripts/archiv.py`. Referenz: `docs/nas-archiv.md`.

## Regeln

- Ordnername immer `YYYY-MM-DD Titel` (Wunsch des Nutzers). Titel kurz und sprechend, aus dem Workout-Namen
  oder der Einheit ableiten (`Hyrox Training`, `Hyrox RP Workout`, `Long Distanz`, `10 km Lauf`); im Zweifel
  den Nutzer fragen. Ohne `--titel` heißt ein neuer Ordner `YYYY-MM-DD Training`; ein vorhandener Ordner zum
  Datum wird weiterverwendet und mit `--titel` umbenannt.
- Gesundheitsdaten und Fotos gehören nur ins Archiv-Repo, nie ins Code-Repo `laufanalyse`.
- Jedes Foto bekommt eine Beschreibung (`pfad=Beschreibung`): Gerät, Einheit, Besonderheit. Ohne Beschreibung
  ist ein PM5-Foto später wertlos.
- Ein Tag kann mehrfach ergänzt werden (neue Fotos, Coach-Text nach RPE): das Skript hängt an, dedupliziert
  Fotos per Hash und aktualisiert `index.json`. Nichts wird gelöscht; `auswertung.md` und `coach.txt` werden
  nur durch ausdrücklich übergebene Dateien ersetzt (die automatischen Vorstufen füllen nur leere Tage).
- Der Coach-Text im Archiv ist der Text, der tatsächlich an den Coach ging (mit RPE); die automatischen
  `coach.txt` aus den Concept2-Ordnern enthalten „RPE: (bitte ergänzen)“ und sind nur Vorstufe.

## Ablauf in einer Cloud-Session

1. Archiv-Repo einbinden, falls noch nicht geschehen: `add_repo(owner="MarqEwi", repo="training-archiv", access="push")`,
   dann `git clone --depth 1 https://github.com/MarqEwi/training-archiv /home/user/training-archiv` und
   `register_repo_root`. Vor dem ersten Push in dieser Session `git -C /home/user/training-archiv pull --ff-only`.
2. Daten des Tages erzeugen, falls noch nicht da: `/laufanalyse` (Garmin) bzw. `/ergoanalyse` (Concept2,
   auch Foto-Einheiten mit `concept2_analyze_manual`). Sie landen unter `data/garmin/<datum>_*` und
   `data/concept2/<datum>_*`, von dort sammelt das Skript.
3. Fotos aus dem Chat liegen unter `/root/.claude/uploads/<session>/…jpg`; Beschreibung je Bild festlegen
   (vom Nutzer erfragen, wenn unklar). Tagesauswertung als Markdown-Datei und Coach-Text als Textdatei in
   den Scratchpad-Ordner schreiben.
4. Ablegen und pushen:
   ```
   TRAINING_ARCHIV_DIR=/home/user/training-archiv uv run scripts/archiv.py --date YYYY-MM-DD --titel "Hyrox Training" \
     --foto /pfad/bild.jpg="PM5 SkiErg 5x1000m" --auswertung auswertung.md --coach coach.txt --push
   ```
   Erst `--dry-run`, wenn unklar ist, was gefunden wird. Ausgabe (Protokoll, Commit) dem Nutzer nennen.
5. Nutzer sagen, dass die NAS den Stand innerhalb von 10 Minuten unter
   `\\STEVENAS\Grundlagen\training\archiv\<Jahr>\<Datum> <Titel>\` hat und die Fotos vom Handy gelöscht werden können.

## Ablauf am PC (Surface)

Gleiches Skript; `TRAINING_ARCHIV_DIR` zeigt auf den lokalen Klon (`E:\Users\Marc\Claude Projekte\training-archiv`).
Fotos können direkt aus dem Handy-Backup-Ordner der NAS-App genommen werden. Push wie oben, die NAS
zieht sich den Stand. Alternativ ohne Git direkt per SMB nach `\\STEVENAS\Grundlagen\training\archiv\…`
schreiben, dann aber ohne Versionierung (nur im Notfall).
