# Laufanalyse – Hinweise für Claude Code

## Ordner-Konvention auf dem PC (Windows)

- Neue Projektordner auf dem PC des Nutzers immer unter `E:\Users\Marc\Claude Projekte\<Projektname>` anlegen, nie an anderer Stelle.
- Dieses Repo liegt auf dem PC unter `E:\Users\Marc\Claude Projekte\GarminConnect`.
- Exportierte Laufdaten gehören nach `E:\Users\Marc\Claude Projekte\GarminConnect\data\garmin\<datum>_<id>\` (das ist `LAUFANALYSE_DATA_DIR`, wird vom Setup-Skript gesetzt).
- Token-Cache bleibt bewusst außerhalb des Projekts in `%USERPROFILE%\.garminconnect` (nicht versioniert).
- Ergometer-Daten aus dem Concept2 Logbook gehören nach `…\GarminConnect\data\concept2\<datum>_<id>\`
  (`CONCEPT2_DATA_DIR`), Concept2-Tokens nach `%USERPROFILE%\.concept2` (nicht versioniert).

## Regeln für dieses Projekt

- Deutsch in allen Ausgaben, Pace in min/km, Distanzen in km, Zeiten als mm:ss.
- Keine Zugangsdaten oder Tokens in Dateien des Repos; `.gitignore` beachten.
- Liefert ein Tool nicht die erwarteten Daten: klar sagen und Alternative vorschlagen, nie Werte schätzen.
- Laufanalysen laufen über die Skill `/laufanalyse` und den MCP-Server `garmin` (`scripts/garmin_mcp_server.py`, registriert in `.mcp.json`).
- Ergometer-Einheiten (Rudern, Ski Erg, Bike Erg aus ErgData/Concept2 Logbook) über die Skill `/ergoanalyse` und die
  Tools `mcp__garmin__concept2_*` desselben Servers; Workouts anlegen über `/workout`.
- Tool-Referenz: `docs/garmin-tools.md` (Garmin), `docs/concept2-tools.md` (Concept2).
- Tests ohne Netz: `uv run --with pytest --with requests pytest -q tests/`.
- Ordner und Dateien, die für den Nutzer angelegt werden (Archiv-Tage, Exporte, Projektordner), heißen
  `YYYY-MM-DD Titel`, z. B. `2026-09-20 Hyrox Training` (Wunsch des Nutzers vom 20.09.2026). Bestehende
  technische Namen wie `data/garmin/<datum>_<id>` bleiben, alles Neue folgt der Vorlage.
- Trainingsarchiv: Fotos, Exporte, Auswertung und Coach-Text eines Tages gehören ins private Repo
  `MarqEwi/training-archiv` (Skill `/archiv`, `scripts/archiv.py`, Doku `docs/nas-archiv.md`), nie in dieses
  Code-Repo. Die NAS spiegelt das Archiv nach `/volume1/Grundlagen/training/archiv` (`nas/training-sync`).
  Lokaler Klon am PC: `E:\Users\Marc\Claude Projekte\training-archiv` (`TRAINING_ARCHIV_DIR`).

## NAS-Umgebung (Projekt „training“ auf STEVENAS) – Kontext vom Nutzer, 20.09.2026

Gilt für Sessions auf den Windows-PCs des Nutzers: „Master PC“ (MASTERPC-MARC, großer PC, bevorzugt für
NAS-Arbeiten, Repo unter `E:\Users\Marc\Claude Projekte\GarminConnect`) und Surface (MARC-SURFACE).
Cloud-Sessions erreichen die NAS nicht (kein SSH-Client, kein LAN); sie bereiten nur Dateien im Repo vor,
die Ausführung auf der NAS passiert in der PC-Session. Jeder PC braucht seinen eigenen SSH-Schlüssel in
`~/.ssh/authorized_keys` von MarcEwers auf der NAS; auf Surface und Master PC ist das eingerichtet
(Master PC seit 21.09.2026). Zu Beginn prüfen: `ssh MarcEwers@STEVENAS id` → `uid=1001(MarcEwers)
gid=10(admin)`, u. a. in der Gruppe `docker`.

### Die NAS
- Modell: UGREEN NASync DH2300 (2-Bay), Betriebssystem UGOS (UGREEN-eigenes Embedded-Linux), Architektur
  aarch64/ARM64, 4 GB RAM (fest verbaut).
- Hostname: STEVENAS, feste IP im LAN: 192.168.2.101.
- Heimnetz: 192.168.2.0/24, Router ist eine AVM Fritzbox (192.168.2.1, fritz.box). Die PCs hängen im selben
  Netz: Surface (MARC-SURFACE, Windows 11/PowerShell) unter 192.168.2.117 (WLAN), Master PC (MASTERPC-MARC)
  unter 192.168.2.145.
- Hostkey der NAS (ED25519): `SHA256:CnV8JtLnFa1Pz3kuFBGlGVjhd2c8SdPUo7KE7v1SlsE`.

### Zugriff
- SSH: `ssh MarcEwers@STEVENAS` – Public-Key-Auth (Surface und Master PC eingerichtet), dann
  KEINE Passwortabfrage. Alle NAS-Arbeiten laufen über diesen SSH-Zugang.
- ACHTUNG IPv6: Die Fritzbox löst `STEVENAS` auch auf eine IPv6-Adresse auf, der SSH-Dienst der NAS lauscht
  aber nur auf IPv4. Ohne Vorkehrung läuft `ssh MarcEwers@STEVENAS` deshalb still in einen Timeout (Ping
  antwortet trotzdem – täuscht Erreichbarkeit vor). Auf dem Master PC steht dafür in `~/.ssh/config`:
  `Host STEVENAS stevenas` / `HostName 192.168.2.101` / `User MarcEwers` / `AddressFamily inet`.
  Auf einem neuen PC entweder diesen Eintrag anlegen oder durchgehend die IP 192.168.2.101 verwenden.
- Von Windows aus ist die NAS auch als SMB-Freigabe erreichbar: `\\STEVENAS\Grundlagen`.
- Die UGOS-Weboberfläche bedient der Nutzer selbst im Browser; wenn dort Klicks nötig sind, anleiten.

### Speicher / Pfade
- Datenvolume ist `/volume1`. Hauptfreigabe „Grundlagen“: Linux-Pfad `/volume1/Grundlagen`
  (= `\\STEVENAS\Grundlagen` unter Windows).
- DIESES Projekt lebt im bereits angelegten Ordner `/volume1/Grundlagen/training`
  (= `\\STEVENAS\Grundlagen\training`). Alle Dateien, Daten und – falls nötig – die docker-compose.yml
  dieses Projekts gehören dort hinein. Zu Beginn per SSH prüfen, dass der Ordner existiert und
  Schreibrechte bestehen.
- Andere Ordner unter `/volume1/Grundlagen` (insbesondere `docker/heizung`) nur lesen, niemals verändern.

### Docker (wichtige Besonderheiten)
- Docker ist auf dem DH2300 offiziell nicht vorgesehen und wurde manuell installiert (App-Paket des
  Schwestermodells DH4300 Plus). Es funktioniert zuverlässig, aber: Die App aktualisiert sich NICHT
  automatisch – niemals eigenmächtig Docker-/Firmware-Updates anstoßen.
- Binary: `/usr/bin/docker`, Compose-v2-Plugin vorhanden (`docker compose`).
- User MarcEwers ist in der docker-Gruppe: KEIN sudo für Docker nötig.
- Nur ARM64/aarch64-Images verwenden (keine amd64-only-Images).
- Kaputtes Hairpin-NAT: Container erreichen die eigene LAN-IP (192.168.2.101) nur mit
  `network_mode: host`. Dienste, die LAN-Geräte oder andere Container über die LAN-IP ansprechen müssen →
  Host-Netz nutzen und VORHER freie Ports prüfen. Reine Standalone-Dienste können Bridge-Netz mit
  Port-Mapping nutzen.

### Was bereits läuft (NICHT anfassen)
Unter `/volume1/Grundlagen/docker/heizung/` läuft das Heizungs-Projekt mit drei Containern, alle im
Host-Netz, `restart: unless-stopped`:
- homeassistant → Port 8123 (Home Assistant, produktiv genutzt!)
- mosquitto → Port 1883 (MQTT-Broker)
- brunner-bridge → eigener Python-Dienst (VNC/OCR zur Heizungssteuerung)

Dazu kommt `port80-guard` (läuft seit ca. August 2026, Herkunft vom Nutzer nicht dokumentiert) – ebenfalls
nicht anfassen. Eigener Container dieses Projekts: `training-sync` (siehe `docs/nas-archiv.md`).

Regeln: Diese Container und deren Ordner NICHT verändern, NICHT neu starten, NICHT deren Ports (8123, 1883,
evtl. 80 für emulated_hue) belegen. Vor der Portwahl für neue Dienste `docker ps` ansehen und belegte Ports
auf dem Host prüfen (netstat/ss über SSH). Der MQTT-Broker (192.168.2.101:1883, anonym) DARF mitgenutzt
werden, aber keine Topics unter `brunner/*` oder `homeassistant/*` schreiben.

### Ressourcen & Rücksicht
- Nur 4 GB RAM, geteilt mit Home Assistant & Co. – sparsame Images wählen, keine RAM-fressenden Dienste
  ohne Rücksprache.
- Keine systemweiten Änderungen an der NAS (Pakete, Firmware, Netzwerk-Konfiguration, SSH-Konfig) ohne
  ausdrückliche Freigabe des Nutzers.
- Größere Downloads/Builds sind okay, aber vorher sagen, wie viel Speicher das Projekt ungefähr belegt.

### Arbeitsweise
- Vom Windows-PC aus per SSH auf der NAS arbeiten.
- Config-Dateien mit Sonderzeichen nicht per SSH-Heredoc schreiben (der lokale Shell-Parser bricht bei
  Quotes) – stattdessen lokal mit dem Write-Tool erstellen und per
  `ssh MarcEwers@STEVENAS "cat > /ziel/pfad" < lokaledatei` übertragen.
- Vor destruktiven Aktionen (löschen, überschreiben, Container stoppen) immer erst anzeigen, was betroffen
  wäre, und den Nutzer fragen.
