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
