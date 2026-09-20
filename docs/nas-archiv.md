# Trainingsarchiv auf der NAS (STEVENAS)

Stand: 20.09.2026. Architektur „A“: Cloud- und PC-Sessions schreiben in das private Repo
`MarqEwi/training-archiv`, die NAS holt es sich ab. Kein offener Port, keine Fritzbox-Änderung, das
Heizungsprojekt bleibt unberührt. Erster Ende-zu-Ende-Test 20.09.2026: zwei Tage (20./21.09.) mit 11 Fotos,
Garmin- und Concept2-Exporten, Auswertung und Coach-Text gepusht (54 MB).

## Ablage im Archiv-Repo

```
<Jahr>/<YYYY-MM-DD> <Titel>/     z. B. 2026/2026-09-20 Hyrox Training
  fotos/            Bilder als <Datum>_foto-NN.jpg + index.md (Beschreibung, sha1)
  garmin/<ordner>/  Kopie von data/garmin/<datum>_<id>/
  concept2/<ordner>/ Kopie von data/concept2/<datum>_<id>/ und *_kombiniert.md
  auswertung.md     Tagesauswertung
  coach.txt         Text, der an den Coach ging (mit RPE)
  index.json        Manifest (Quellen, Fotos, Zeitstempel, Notiz)
```

Ordnernamen folgen der Vorgabe des Nutzers „YYYY-MM-DD Titel“ (`--titel`, ohne Angabe „Training“); ein
vorhandener Ordner zum Datum wird weiterverwendet und mit `--titel` per `git mv` umbenannt. Bereits abgelegte
`auswertung.md`/`coach.txt` werden nur durch ausdrücklich übergebene Dateien ersetzt, nie durch die
automatischen Vorstufen. Befüllen: `scripts/archiv.py` (Skill `/archiv`), siehe Docstring. Umgebungsvariable `TRAINING_ARCHIV_DIR`
= lokaler Klon des Archiv-Repos (Cloud: `/home/user/training-archiv`, PC: `E:\Users\Marc\Claude Projekte\training-archiv`).

## Einrichtung auf der NAS (einmalig, in der PC-Session per SSH)

Dateien liegen im Code-Repo unter `nas/training-sync/` und werden nach `/volume1/Grundlagen/training/sync/`
übertragen (lokal schreiben, dann `ssh MarcEwers@STEVENAS "cat > /ziel" < datei`, keine Heredocs über SSH).

1. **Prüfen:** `ssh MarcEwers@STEVENAS "ls -ld /volume1/Grundlagen/training && touch /volume1/Grundlagen/training/.w && rm /volume1/Grundlagen/training/.w && id && docker ps --format '{{.Names}} {{.Ports}}'"`
   → Ordner vorhanden, Schreibrecht, UID/GID von MarcEwers notieren, laufende Container sehen (heizung nicht anfassen).
2. **Ordner:** `ssh MarcEwers@STEVENAS "mkdir -p /volume1/Grundlagen/training/sync /volume1/Grundlagen/training/keys /volume1/Grundlagen/training/archiv"`
3. **Deploy-Key (nur lesend):** auf der NAS erzeugen, damit der private Schlüssel die NAS nie verlässt:
   `ssh MarcEwers@STEVENAS "ssh-keygen -t ed25519 -N '' -C training-sync@STEVENAS -f /volume1/Grundlagen/training/keys/training-archiv_deploy && chmod 600 /volume1/Grundlagen/training/keys/training-archiv_deploy && cat /volume1/Grundlagen/training/keys/training-archiv_deploy.pub"`
   Den öffentlichen Schlüssel bei GitHub eintragen: Repo `training-archiv` → Settings → Deploy keys → Add,
   **ohne** „Allow write access“.
4. **GitHub-Hostkey** (optional, sonst Trust on first use): `ssh MarcEwers@STEVENAS "ssh-keyscan -t ed25519 github.com > /volume1/Grundlagen/training/keys/github_known_hosts"`
   und Fingerabdruck mit https://docs.github.com/en/authentication/keychain vergleichen.
5. **Dateien übertragen:** `docker-compose.yml`, `sync.sh`, `.env` (aus `.env.example`, PUID/PGID aus Schritt 1)
   nach `/volume1/Grundlagen/training/sync/`. Dann `chmod +x sync.sh`.
6. **Start:** `ssh MarcEwers@STEVENAS "cd /volume1/Grundlagen/training/sync && docker compose up -d && sleep 20 && docker logs training-sync"`
   Erwartet: `geklont: git@github.com:MarqEwi/training-archiv.git`, danach alle 10 Minuten `pull ok`.
7. **Kontrolle:** `\\STEVENAS\Grundlagen\training\archiv\2026\2026-09-20 Hyrox Training\` im Explorer öffnen.

Ressourcen: Image `alpine/git` ~30 MB, Container < 20 MB RAM, `mem_limit 64m`. Speicher wächst mit den Fotos,
etwa 3 MB je Bild, bei fünf Bildern pro Trainingstag rund 5 GB pro Jahr. Bridge-Netz, kein Port.

## Betrieb

- Cloud-Session: Archiv-Repo mit `add_repo` einbinden und klonen (siehe Skill), dann `/archiv <Datum>`.
- PC-Session: Klon unter `E:\Users\Marc\Claude Projekte\training-archiv`, `/archiv <Datum>`; Fotos aus dem
  Backup-Ordner der UGREEN-App.
- Sync stoppen/aktualisieren: nur `training-sync` (`docker compose down` im Ordner `sync/`), nie die Heizungs-Container.
- Logs: `docker logs --tail 50 training-sync`. Häufigste Fehler: Deploy-Key nicht bei GitHub eingetragen
  (`Permission denied (publickey)`), `/archiv` nicht leer und kein Repo (Ordner leeren), Hostkey unbekannt
  (Schritt 4).

## Offen

- UGREEN-App-Fotobackup in einen Eingangsordner (z. B. `/volume1/Grundlagen/training/eingang/`) einrichten,
  damit PC-Sessions Fotos ohne Chat-Upload einsortieren können.
- Tages-Übersicht (`README.md` je Jahr mit Liste der Tage) automatisch erzeugen.
