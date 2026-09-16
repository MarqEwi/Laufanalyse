# Laufanalyse – Garmin Connect in Claude Code

Garmin-Connect-Daten (Laps, Sekunden-Zeitreihe, HF-Zonen, Wetter) in Claude Code auswerten:
MCP-Server `garmin` (Paket `mcp-garmin` über `uvx`), Skill `/laufanalyse` und ein Export-Skript,
das Läufe als CSV/JSON in `data/garmin/<datum>_<id>/` sichert.

## Warum `mcp-garmin` und nicht das npm-Paket

Das bevorzugte `@nicolasvegam/garmin-connect-mcp` (npm) nutzt den alten Garmin-Login-Weg, den Garmin
im März 2026 umgestellt hat, und unterstützt kein MFA. `mcp-garmin` setzt auf `python-garminconnect`
≥ 0.3 mit dem aktuellen Login (inkl. MFA-Abfrage) und Token-Cache. Details, Tool-Namen und
Parameter: [docs/garmin-tools.md](docs/garmin-tools.md).

## Einrichtung (Windows)

Voraussetzungen: [uv](https://docs.astral.sh/uv/) (`winget install --id astral-sh.uv -e`) und die Claude-Code-CLI.
Python wird von uv selbst verwaltet (3.14 für den MCP-Server, ≥ 3.11 für die Skripte).

```powershell
git clone https://github.com/MarqEwi/Laufanalyse
cd Laufanalyse
powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1
```

Das Skript fragt E-Mail und Passwort ab (Passwort ohne Anzeige), meldet sich einmalig an (MFA-Code
wird abgefragt), legt den Token-Cache in `%USERPROFILE%\.garminconnect` ab, listet zum Test die letzten
5 Aktivitäten samt Kennzahlen des letzten Laufs, registriert den MCP-Server im User-Scope
(`claude mcp add garmin -s user -e GARMINTOKENS=… -- uvx --python 3.14 mcp-garmin`) und kopiert die
Skill nach `%USERPROFILE%\.claude\skills\laufanalyse`.

Danach ein **neues Terminal** öffnen (Umgebungsvariablen), `claude` starten, mit `/mcp` prüfen, dass
`garmin` verbunden ist, und `/laufanalyse` aufrufen.

Manuell statt Skript:

```powershell
setx GARMIN_EMAIL "marc.ewers@gmx.de"
setx GARMIN_PASSWORD "<passwort>"          # oder Systemsteuerung > Umgebungsvariablen
setx GARMINTOKENS "%USERPROFILE%\.garminconnect"
uv run scripts\garmin_login.py             # MFA-Code eingeben, Test der letzten 5 Aktivitäten
claude mcp add garmin -s user -e "GARMINTOKENS=%USERPROFILE%\.garminconnect" -- uvx --python 3.14 mcp-garmin
```

Linux/macOS: gleiche Befehle mit `export` statt `setx`; Skill nach `~/.claude/skills/laufanalyse/` kopieren (inkl. `scripts/`).

## Zugangsdaten und Sicherheit

- E-Mail/Passwort nur in Benutzer-Umgebungsvariablen, nie in Dateien des Repos. `.gitignore` schließt Token-Dateien, `.env`, `data/` und FIT-Exporte aus.
- Tokens: `%USERPROFILE%\.garminconnect\garmin_tokens.json`. Access-Token wird automatisch erneuert; nur wenn Garmin die Sitzung widerruft, erneut `uv run scripts\garmin_login.py --force`.
- Bei „429 Too Many Requests“ einige Minuten warten (Garmin bremst wiederholte Logins).

## Benutzung

| Aufruf | Wirkung |
|---|---|
| `/laufanalyse` | letzter Lauf: Überblick, Lap-Tabelle (Belastung/Erholung markiert, HF-Anstieg je Lap), Intervall-Auswertung, HF-Zonen, Kurzfazit |
| `/laufanalyse 2026-09-14` | Lauf an diesem Datum |
| `/laufanalyse 19876543210` | Aktivitäts-ID |
| `/laufanalyse --fit export.fit` | ohne API aus einer FIT-Datei (Garmin Connect → Aktivität → „Original exportieren“) |
| Nachfragen | „Wie schnell war ich in Intervall 3 und wie hoch war die Ø-HF?“, „Vergleiche die 1000er von heute mit denen vor zwei Wochen“ – die Skill nutzt die gesicherten Daten |

Skript direkt:

```powershell
uv run scripts\garmin_export.py                    # letzter Lauf sichern + Bericht
uv run scripts\garmin_export.py --date 2026-09-14
uv run scripts\garmin_export.py --id 19876543210 --recovery-hr 135
uv run scripts\garmin_export.py --fit lauf.fit
uv run scripts\garmin_export.py --list 5           # letzte 5 Aktivitäten
uv run scripts\garmin_export.py --exported         # gesicherte Läufe auflisten
```

## Dateien

| Pfad | Zweck |
|---|---|
| `scripts/setup-garmin-mcp.ps1` | Windows-Einrichtung (Env-Variablen, Login, MCP, Skill) |
| `scripts/garmin_login.py` | Erstanmeldung mit MFA, Token-Cache, Smoke-Test |
| `scripts/garmin_export.py` | Laps + Zeitreihe + Zonen + Wetter sichern, Intervall-Kennzahlen berechnen, FIT-Fallback |
| `scripts/garmin_auth.py` | gemeinsame Anmeldung (Env-Variablen, Token-Ordner) |
| `.claude/skills/laufanalyse/SKILL.md` | Skill (Projekt-Kopie; Setup kopiert sie in den User-Scope) |
| `docs/garmin-tools.md` | MCP-Tools, Parameter, gelieferte Felder, bekannte Einschränkungen |
| `data/garmin/<datum>_<id>/` | `summary.md`, `analysis.json`, `laps.csv/json`, `timeseries.csv`, `raw/*.json` (nicht versioniert) |

## Bekannte Einschränkungen

- MCP-Tool `get_activity_details` (Zeitreihe) ist in `mcp-garmin` 0.3.0 defekt (`maxchart=0`). Die Skill holt die Zeitreihe deshalb über `garmin_export.py`.
- Wetter: Garmin liefert `temp` mutmaßlich in °F und `windSpeed` in mph; das Skript rechnet um und behält die Rohwerte. Beim ersten echten Lauf gegen Garmin Connect prüfen.
- Belastungs-/Erholungs-Erkennung ohne strukturiertes Workout ist eine Pace-Heuristik (`--work-factor`, Standard 0.93).
