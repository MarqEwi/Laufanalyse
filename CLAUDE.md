# Laufanalyse – Hinweise für Claude Code

## Ordner-Konvention auf dem PC (Windows)

- Neue Projektordner auf dem PC des Nutzers immer unter `E:\Users\Marc\Claude Projekte\<Projektname>` anlegen, nie an anderer Stelle.
- Dieses Repo liegt auf dem PC unter `E:\Users\Marc\Claude Projekte\GarminConnect`.
- Exportierte Laufdaten gehören nach `E:\Users\Marc\Claude Projekte\GarminConnect\data\garmin\<datum>_<id>\` (das ist `LAUFANALYSE_DATA_DIR`, wird vom Setup-Skript gesetzt).
- Token-Cache bleibt bewusst außerhalb des Projekts in `%USERPROFILE%\.garminconnect` (nicht versioniert).

## Regeln für dieses Projekt

- Deutsch in allen Ausgaben, Pace in min/km, Distanzen in km, Zeiten als mm:ss.
- Keine Zugangsdaten oder Tokens in Dateien des Repos; `.gitignore` beachten.
- Liefert ein Tool nicht die erwarteten Daten: klar sagen und Alternative vorschlagen, nie Werte schätzen.
- Laufanalysen laufen über die Skill `/laufanalyse` und den MCP-Server `garmin` (`scripts/garmin_mcp_server.py`, registriert in `.mcp.json`).
- Tool-Referenz: `docs/garmin-tools.md`.
