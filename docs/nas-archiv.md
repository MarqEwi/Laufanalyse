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
   **Zeilenenden:** Die Dateien müssen LF behalten – mit CRLF startet `sync.sh` im Container nicht
   (kaputter Shebang). Dafür sorgt seit 21.09.2026 die `.gitattributes` im Wurzelverzeichnis des Repos
   (`nas/** text eol=lf`). Nach dem Übertragen trotzdem `md5sum` auf beiden Seiten
   vergleichen; in einem älteren Klon einmal `git add --renormalize .` ausführen.
6. **Start:** `ssh MarcEwers@STEVENAS "cd /volume1/Grundlagen/training/sync && docker compose up -d && sleep 20 && docker logs training-sync"`
   Erwartet: `geklont: git@github.com:MarqEwi/training-archiv.git`, danach alle 10 Minuten `pull ok`.
7. **Kontrolle:** `\\STEVENAS\Grundlagen\training\archiv\2026\2026-09-20 Hyrox Training\` im Explorer öffnen.

**Eingerichtet am 21.09.2026** vom Master PC (MASTERPC-MARC): PUID/PGID = 1001/10 (MarcEwers:admin),
Deploy-Key `SHA256:BWv08TWzO44E09hss8PrkHZ5reCcVqCl6u31qgLCzf4` bei GitHub ohne Schreibrecht eingetragen,
GitHub-Hostkey geprüft (`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`). Erster Klon 53 MB,
Container belegt 11 MB RAM von 64 MB Limit und keinen Port.

Ressourcen: Image `alpine/git` ~30 MB plus `mosquitto-clients` ~1 MB, Container < 20 MB RAM,
`mem_limit 64m`. Speicher wächst mit den Fotos, etwa 3 MB je Bild, bei fünf Bildern pro Trainingstag
rund 5 GB pro Jahr. Bridge-Netz, kein Port.

## Überwachung

Seit 21.09.2026 meldet `sync.sh` nach jedem Durchlauf per MQTT (retained) auf `training/sync/status`:

```json
{"status":"ok","zeitpunkt":"2026-09-21 09:42:36","commit":"4090cf2","meldung":"4090cf2 2026-06-01 Grundlagen"}
```

Bei `"status":"fehler"` steht der Grund in `meldung` (z. B. `Repository not found`, `Permission denied
(publickey)`, `Zeitüberschreitung nach 300s`). `MQTT_HOST` in der `.env` leer lassen schaltet die Meldung ab.

Der Broker ist der `mosquitto` des Heizungsprojekts, dessen Mitbenutzung die Projektregeln erlauben –
`training/sync/*` liegt außerhalb von `brunner/*` und `homeassistant/*`. **Deshalb bewusst keine
MQTT-Discovery**, die würde nach `homeassistant/*` schreiben. Sensor in Home Assistant von Hand anlegen:

```yaml
mqtt:
  sensor:
    - name: Trainingsarchiv-Sync
      state_topic: training/sync/status
      value_template: "{{ value_json.status }}"
      json_attributes_topic: training/sync/status
```

Aus dem Bridge-Netz ist der Broker **nicht** über die LAN-IP erreichbar (kaputtes Hairpin-NAT der NAS),
deshalb `MQTT_HOST=nas-host` über `extra_hosts: nas-host:host-gateway`. Das erspart `network_mode: host`.

Zusätzlich begrenzt `GIT_TIMEOUT` (Vorgabe 300 s) jeden `git clone`/`pull`. Ohne das konnte eine hängende
Verbindung zu GitHub die Schleife dauerhaft blockieren – der Container lief dann weiter als „Up", ohne noch
zu synchronisieren.

## Betrieb

- Cloud-Session: Archiv-Repo mit `add_repo` einbinden und klonen (siehe Skill), dann `/archiv <Datum>`.
- PC-Session: Klon unter `E:\Users\Marc\Claude Projekte\training-archiv`, `/archiv <Datum>`; Fotos aus dem
  Backup-Ordner der UGREEN-App.
- Sync stoppen/aktualisieren: nur `training-sync` (`docker compose down` im Ordner `sync/`), nie die Heizungs-Container.
- Nach Änderungen an `sync.sh` genügt `docker compose restart` (die Datei ist als Volume eingebunden);
  nach Änderungen am `Dockerfile` `docker compose up -d --build`.
- Logs: `docker logs --tail 50 training-sync`, mit `-t` für Docker-Zeitstempel (hilfreich, um Meldungen
  einem Durchlauf vor oder nach einem Neustart zuzuordnen – stderr erscheint sonst außer der Reihe).
  Häufigste Fehler: Deploy-Key nicht bei GitHub eingetragen (`Permission denied (publickey)`),
  `/archiv` nicht leer und kein Repo (Ordner leeren), Hostkey unbekannt (Schritt 4).

## Offen

- UGREEN-App-Fotobackup in einen Eingangsordner (z. B. `/volume1/Grundlagen/training/eingang/`) einrichten,
  damit PC-Sessions Fotos ohne Chat-Upload einsortieren können.
- Tages-Übersicht (`README.md` je Jahr mit Liste der Tage) automatisch erzeugen.
