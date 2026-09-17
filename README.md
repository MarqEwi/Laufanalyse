# Laufanalyse – Garmin Connect in Claude Code (PC, Smartphone, Cloud)

Garmin-Connect-Daten (Laps, Sekunden-Zeitreihe, HF-Zonen, Wetter) in Claude Code auswerten – auf dem
Windows-PC und in Cloud-Sessions (Claude-App auf dem Smartphone, claude.ai/code) mit derselben Skill
`/laufanalyse` und demselben MCP-Server `garmin`.

Bausteine:

- `scripts/garmin_mcp_server.py` – eigener MCP-Server (Python ≥ 3.11, `uv run`), registriert über `.mcp.json` im Repo → auf jedem Gerät verfügbar
- `.claude/skills/laufanalyse/SKILL.md` – Skill `/laufanalyse` (Projekt-Skill, im Repo)
- `scripts/garmin_export.py` – Sicherung als CSV/JSON nach `data/garmin/<datum>_<id>/`, Intervall-Kennzahlen, FIT-Fallback
- `.claude/hooks/session-start.sh` – bereitet Cloud-Sessions vor (Abhängigkeiten, Token aus Umgebungsvariable)
- `docs/garmin-tools.md` – Tool-Namen, Parameter, gelieferte Felder, Einschränkungen, Serverwahl (warum kein npm-Paket / kein `mcp-garmin`)

## Wie die Anmeldung auf allen Geräten funktioniert

Garmin gibt nach dem Login (E-Mail, Passwort, MFA-Code) ein Token-Paar aus, das die Bibliothek
`python-garminconnect` automatisch erneuert. Die MFA-Anmeldung machst du **einmal auf dem PC**; der
Token-Cache liegt dann in `%USERPROFILE%\.garminconnect\garmin_tokens.json`. Für Cloud-Sessions überträgst
du den Token-Inhalt als Umgebungsvariable `GARMIN_TOKENS_B64` in deine Cloud-Umgebung. Zugangsdaten und
Tokens landen nie in Dateien des Repos (`.gitignore`).

## Einrichtung

### 1. PC (Windows)

Voraussetzungen: [uv](https://docs.astral.sh/uv/) (`winget install --id astral-sh.uv -e`) und die Claude-Code-CLI.

Projektordner auf dem PC: `E:\Users\Marc\Claude Projekte\GarminConnect` (Konvention: alle Claude-Projekte
liegen unter `E:\Users\Marc\Claude Projekte\<Projektname>`, siehe `CLAUDE.md`).

```powershell
New-Item -ItemType Directory -Force "E:\Users\Marc\Claude Projekte" | Out-Null
git clone -b claude/trusting-ptolemy-osb557 https://github.com/MarqEwi/Laufanalyse "E:\Users\Marc\Claude Projekte\GarminConnect"
cd "E:\Users\Marc\Claude Projekte\GarminConnect"
powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1
```

Das Setup-Skript leitet alle Pfade (MCP-Server, Datenordner `data\garmin`, Skill-Kopie) aus dem Ordner ab,
in dem das Repo liegt.

Das Skript fragt E-Mail und Passwort ab (ohne Anzeige), legt sie als Benutzer-Umgebungsvariablen ab,
meldet sich an (MFA-Code wird abgefragt), zeigt zum Test die letzten 5 Aktivitäten samt Kennzahlen des
letzten Laufs, registriert den MCP-Server im User-Scope, kopiert die Skill nach
`%USERPROFILE%\.claude\skills\laufanalyse` und gibt am Ende den Wert für `GARMIN_TOKENS_B64` aus
(landet auch in der Zwischenablage).

Danach ein **neues Terminal** öffnen, `claude` im Repo starten, `/mcp` prüfen (`garmin` connected),
`/laufanalyse` aufrufen.

### 2. Cloud-Umgebung (für Smartphone und claude.ai/code)

Einmalig unter [claude.ai/code](https://claude.ai/code) → Cloud-Umgebung (Default oder neue) bearbeiten:

| Einstellung | Wert |
|---|---|
| Netzwerkzugriff | **Custom**, erlaubte Domain `*.garmin.com` (Paketquellen wie PyPI sind bereits erlaubt) |
| Umgebungsvariablen | `GARMIN_EMAIL=marc.ewers@gmx.de` und `GARMIN_TOKENS_B64=<Wert aus dem Setup-Skript>` |
| optional | `GARMIN_PASSWORD=…` nur, wenn du in der Cloud auch ohne gültige Tokens (mit MFA-Dialog) anmelden willst |

Der Token-Wert lässt sich jederzeit neu erzeugen: `uv run scripts\garmin_login.py --show-token`
oder `scripts\setup-garmin-mcp.ps1 -ShowTokenOnly`.

Hinweis: Wer die Umgebung benutzen kann, kann die Variablen lesen. Eine persönliche Umgebung ist dafür in
Ordnung; in eine geteilte Team-Umgebung gehören die Werte nicht.

### 3. Smartphone

Claude-App → Tab „Code“ → Repo `MarqEwi/Laufanalyse` (Branch mit diesem Setup) → Session starten →
`/laufanalyse`. Beim Start installiert der Session-Start-Hook die Abhängigkeiten und schreibt die Tokens
aus `GARMIN_TOKENS_B64` in den Token-Ordner; `.mcp.json` startet den Server `garmin`.

Sind die Tokens abgelaufen, kann Claude die MFA-Anmeldung auch in der Cloud-Session ausführen
(`garmin_login.py --mfa-file`, du nennst den Code im Chat) und dir den neuen `GARMIN_TOKENS_B64`-Wert geben.

## Benutzung

| Aufruf | Wirkung |
|---|---|
| `/laufanalyse` | letzter Lauf: Überblick, Lap-Tabelle (Belastung/Erholung markiert, HF-Anstieg je Lap), Intervall-Auswertung, HF-Zonen, Kurzfazit |
| `/laufanalyse 2026-09-14` | Lauf an diesem Datum |
| `/laufanalyse 19876543210` | Aktivitäts-ID |
| `/laufanalyse --fit export.fit` | ohne API aus einer FIT-Datei (Garmin Connect → Aktivität → „Original exportieren“) |
| Nachfragen | „Wie schnell war ich in Intervall 3 und wie hoch war die Ø-HF?“, „Vergleiche die 1000er von heute mit denen vor zwei Wochen“ – die Skill nutzt die gesicherten Daten |

Skript direkt (PC-Terminal oder Cloud-Bash):

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
| `.mcp.json` | MCP-Server `garmin` für dieses Repo (alle Geräte) |
| `.claude/settings.json` | gibt Projekt-MCP-Server frei, registriert den Session-Start-Hook |
| `.claude/hooks/session-start.sh` | Cloud-Vorbereitung (nur wenn `CLAUDE_CODE_REMOTE=true`) |
| `.claude/skills/laufanalyse/SKILL.md` | Skill `/laufanalyse` |
| `scripts/garmin_mcp_server.py` | MCP-Server (15 Tools, u. a. `analyze_run`, `analyze_fit`, `get_activity_laps`, `get_activity_timeseries`) |
| `scripts/garmin_export.py` | Export + Analyse als CLI, FIT-Fallback |
| `scripts/garmin_login.py` | Anmeldung mit MFA (Terminal oder `--mfa-file`), `--show-token` |
| `scripts/garmin_auth.py` | gemeinsame Anmeldung (Env-Variablen, Token-Ordner, Token aus `GARMIN_TOKENS_B64`) |
| `scripts/setup-garmin-mcp.ps1` | Windows-Einrichtung |
| `docs/garmin-tools.md` | Tools, Parameter, Datenfelder, Einschränkungen |
| `data/garmin/<datum>_<id>/` | `summary.md`, `analysis.json`, `laps.csv/json`, `timeseries.csv`, `raw/*.json` (nicht versioniert) |

## Bekannte Einschränkungen

- In Cloud-Sessions ist `data/garmin/` nur für die Dauer der Session vorhanden. Dauerhafte Sammlungen für Vergleiche über Wochen legst du auf dem PC an (oder du sicherst die Ordner selbst).
- Erneuert Garmin das Refresh-Token, kann eine ältere Kopie in `GARMIN_TOKENS_B64` ungültig werden: dann auf dem PC `--show-token` neu ausführen und die Variable aktualisieren.
- Wetter: Garmin liefert `temp` mutmaßlich in °F und `windSpeed` in mph; das Skript rechnet um und behält die Rohwerte. Beim ersten echten Lauf prüfen.
- Belastungs-/Erholungs-Erkennung ohne strukturiertes Workout ist eine Pace-Heuristik (`work_factor`, Standard 0.93).
- Bei „429 Too Many Requests“ einige Minuten warten; Garmin bremst wiederholte Logins.
