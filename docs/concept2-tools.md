# Concept2 Logbook (ErgData) in Claude Code: Anbindung, Tools, Parameter

Stand: 20.09.2026. Ergänzt den Garmin-MCP-Server (`docs/garmin-tools.md`) um die Ergometer-Einheiten aus dem
Concept2 Logbook: Rudern (RowErg), Ski Erg und Bike Erg, wie ErgData bzw. der PM5 sie hochlädt. Nur Lesezugriff.

**Live geprüft am 20.09.2026 (Cloud-Session, Konto Marc Ewers):** Autorisierung über `/oauth/authorize` und
Code-Tausch über `/oauth/access_token` funktionieren; `GET /users/me` liefert u. a. `first_name`, `last_name`,
`username`, `max_heart_rate`, `weight`, `roles`; `GET /users/me/results` liefert `data[]` + `meta.pagination`.
Token-Verhalten: erstes Access-Token 1 h gültig, nach Refresh 7 Tage; **das Refresh-Token rotiert bei jedem
Refresh** (altes wird ungültig). Die Feldnamen der Results wurden zusätzlich am Beispiel des Concept2
„API Workout Validator“ und am Client `pyconcept2` 0.1.0 verifiziert; ein echtes Result mit Schlagdaten stand
beim Test noch nicht im Logbook (0 Einheiten), das ist der letzte offene Punkt.

## 1. Was die API liefert

| Daten | Endpunkt (Basis `https://log.concept2.com/api`) | Inhalt |
|---|---|---|
| Profil | `GET /users/me` | `id`, `username`, `first_name`, `last_name`, `max_heart_rate`, … |
| Einheiten | `GET /users/me/results?from=YYYY-MM-DD&to=…&type=rower|skierg|bike&updated_after=…&page=&number=` | `data[]` mit `id`, `date` (lokal), `date_utc`, `timezone`, `distance` (m), `type`, `time` (**Zehntelsekunden**), `time_formatted`, `workout_type` (JustRow, FixedDistanceSplits, FixedTimeSplits, FixedDistanceInterval, FixedTimeInterval, VariableInterval …), `source` (ErgData …), `stroke_rate`, `stroke_count`, `calories_total`, `drag_factor`, `rest_time`, `rest_distance`, `stroke_data` (bool), `heart_rate {min, average, max, ending, recovery}`, `workout {splits[], intervals[]}`; `meta.pagination {total, count, per_page, current_page, total_pages}` (Sortierung aufsteigend nach Datum, max. 250 je Seite) |
| Eine Einheit | `GET /users/me/results/{id}` (optional `include=strokes,metadata,user`) | wie oben, `workout.splits[]`/`intervals[]`: `type`, `time` (Zehntel), `distance`, `rest_time`, `rest_distance`, `calories_total`, `stroke_rate`, `heart_rate {…}`, `machine` |
| Schlagdaten | `GET /users/me/results/{id}/strokes` | `data[]` mit `t` (Zehntelsekunden), `d` (Dezimeter), `p` (Pace, Zehntelsekunden je 500 m), `spm`, `hr`. `t`/`d` beginnen je Intervall wieder bei 0. |
| Export | `GET /users/me/results/{id}/export/{csv|fit|tcx}` | Datei |

Header: `Authorization: Bearer <access_token>`, `Accept: application/vnd.c2logbook.v1+json`. HTTP 401 = Token
abgelaufen (wird automatisch erneuert), 403 = Scope fehlt, 429 = zu viele Anfragen.

Umrechnung im Skript: Zeiten /10 → Sekunden, Pace je 500 m aus Distanz/Zeit (Bike Erg je 1000 m), Watt nach
Concept2-Formel `2,8 / (Pace je Meter)³` (nur RowErg/SkiErg).

## 2. Zugang einrichten (einmalig)

1. **App registrieren:** https://log.concept2.com/developers/keys → neue Anwendung, Redirect-URI
   `http://localhost:8765/callback`. Ergebnis: Client-ID und Client-Secret.
2. **PC:** `scripts/setup-concept2.ps1` ausführen (fragt Client-ID/-Secret ab, setzt die Benutzer-Umgebungsvariablen
   `CONCEPT2_CLIENT_ID`, `CONCEPT2_CLIENT_SECRET`, `CONCEPT2_TOKENS`, `CONCEPT2_DATA_DIR`) – oder von Hand setzen.
3. **Autorisieren:** `uv run scripts/concept2_login.py` → Browser öffnet die Concept2-Seite, „Allow“, der Code wird
   auf `localhost:8765` abgefangen, Tokens landen in `%USERPROFILE%\.concept2\concept2_tokens.json` (mit Client-ID/-Secret,
   damit Cloud-Sessions nur eine Variable brauchen). Ohne Browser: `--manual` (URL anzeigen, Adresszeile einfügen).
   Anschließend Smoke-Test: Profilname + letzte 5 Einheiten.
4. **Cloud/Smartphone:** `uv run scripts/concept2_login.py --show-token` → Wert als `CONCEPT2_TOKENS_B64` in der
   Cloud-Umgebung eintragen **und** `log.concept2.com` zu den erlaubten Domains der Umgebung hinzufügen. Der
   Session-Start-Hook schreibt die Tokens beim Start in den Token-Ordner. Live-Test: `concept2_login_status`.

**Alternative ohne PC, direkt aus einer Claude-Code-Session (auch vom Handy):** Voraussetzung sind
`CONCEPT2_CLIENT_ID` und `CONCEPT2_CLIENT_SECRET` als Umgebungsvariablen der Cloud-Umgebung und `log.concept2.com`
in der Netzwerk-Policy. Dann:

1. `concept2_authorize_url` → URL im Browser öffnen, bei Concept2 anmelden, „Allow“.
2. Concept2 leitet auf `http://localhost:8765/callback?code=…&state=…` um. Die Seite lädt auf dem Handy nicht,
   aber die Adresszeile enthält den Code: Adresse kopieren und in den Chat einfügen.
3. `concept2_exchange_code(<eingefügte Adresse>)` → Tokens werden gespeichert, Antwort zeigt `logged_in_as`.
4. `concept2_token_blob` → Wert als `CONCEPT2_TOKENS_B64` in der Cloud-Umgebung eintragen, damit spätere Sessions
   ohne neue Autorisierung starten. Der Wert enthält auch Client-ID/-Secret; nur in die Umgebungsvariablen, nie ins Repo.

Token-Erneuerung läuft automatisch über das Refresh-Token (Aufruf 2 min vor Ablauf bzw. bei 401). **Weil das
Refresh-Token dabei rotiert, ist danach der Wert in `CONCEPT2_TOKENS_B64` veraltet:** `concept2_login_status`
und `concept2_analyze_result` liefern in dem Fall `hinweis` (Flag `token_refreshed_in_session`), dann
`concept2_token_blob` aufrufen und die Variable neu setzen. Praktisch passiert das etwa alle 7 Tage (Laufzeit des
Access-Tokens). Wird das Refresh-Token ungültig (z. B. weil eine alte Kopie verwendet wurde): Autorisierung
wiederholen (Session-Weg oben oder `concept2_login.py --force` am PC), dann `CONCEPT2_TOKENS_B64` aktualisieren.

| Variable | Zweck |
|---|---|
| `CONCEPT2_CLIENT_ID`, `CONCEPT2_CLIENT_SECRET` | App-Zugang (Autorisierung, Token-Erneuerung). Haben Vorrang vor den Werten in der Token-Datei. |
| `CONCEPT2_REDIRECT_URI` | Standard `http://localhost:8765/callback`, muss zur Registrierung passen |
| `CONCEPT2_TOKENS` | Token-Ordner (Standard `~/.concept2`) |
| `CONCEPT2_TOKENS_B64` / `CONCEPT2_TOKENS_JSON` | Token-Datei als base64/JSON für Cloud-Sessions |
| `CONCEPT2_DATA_DIR` | Ausgabeordner (Standard `./data/concept2`; auf dem PC `E:\Users\Marc\Claude Projekte\GarminConnect\data\concept2`) |
| `CONCEPT2_DEV=1` | Test-Logbook `log-dev.concept2.com` |

## 3. Tools des MCP-Servers (`mcp__garmin__concept2_*`)

| Tool | Parameter | Liefert |
|---|---|---|
| `concept2_login_status` | – | Token-Ordner, gesetzte Variablen, Host, Datenordner, `logged_in_as` / Fehlertext |
| `concept2_authorize_url` | – | Schritt 1 der Autorisierung aus der Session: `url`, `state`, `redirect_uri` |
| `concept2_exchange_code` | `code_or_redirect_url` | Schritt 2: Code (oder eingefügte Redirect-URL) gegen Tokens tauschen, speichern, `logged_in_as` |
| `concept2_token_blob` | – | Token-Datei als base64 für `CONCEPT2_TOKENS_B64` |
| `concept2_list_results` | `limit`=10, `type`? (`rower`, `skierg`, `bike` …), `from_date`?, `to_date`? | neueste zuerst: `result_id`, `date`, `start_local`, `type`, `type_de`, `workout_type`, `distance_m`, `time_str`, `pace_str`, `spm`, `hr_avg`, `hr_max`, `has_stroke_data`, `source`, `comments` |
| `concept2_get_result` | `result_id` | `summary` (normalisiert), `splits[]`, `intervals[]` (je: `nr`, `start_s`, `time_s`, `distance_m`, `pace_s`/`pace_str`, `watts`, `spm`, `hr_avg`, `hr_max`, `hr_end`, `rest_time_s`), `raw` |
| `concept2_analyze_result` | `result_id`?, `date`?, `type`?, `rpe`?, `out_dir`? (nichts = letzte Einheit) | `output_dir`, `summary_md` (Bericht), `coach_text` (Pace/HF/RPE als Textbaustein), `analysis` (`summary`, `segments` mit `hr_start_strokes`/`hr_end_strokes`/`hr_rise`, `intervals_stats`: Anzahl, Ø-Pace, Streuung, Spanne, Trend, Ø-HF, HF-Anstieg, `notes`) |
| `concept2_list_exported` | `out_dir`? | gesicherte Einheiten mit Kennzahlen (Vergleiche ohne API) |

CLI am PC (gleiche Logik): `uv run scripts/concept2_export.py [--id … | --date … | --type skierg] [--rpe 7] [--print]`,
`--list 10`, `--exported`.

## 4. Datenstruktur (`data/concept2/<datum>_<result_id>/`)

| Datei | Inhalt |
|---|---|
| `summary.md` | Bericht: Überblick, Intervall-/Split-Tabelle (Pace, Watt, SPM, HF, HF-Anstieg, Pause), Auswertung, Hinweise |
| `coach.txt` | Textbaustein für den Coach (Pace je Intervall, HR avg, RPE) |
| `analysis.json` | alles Berechnete (`summary`, `splits`, `intervals`, `segments`, `intervals_stats`, `notes`, `rpe`) |
| `segments.csv` | Abschnitte normalisiert |
| `strokes.csv` | Schlagdaten: `t_s` (kumuliert inkl. Pausen), `distance_m`, `pace_s`, `spm`, `hr`, `segment` |
| `raw/result.json`, `raw/strokes.json` | unveränderte API-Antworten |

## 5. Bekannte Einschränkungen

1. HF-Werte gibt es nur, wenn ein Gurt mit dem PM5 oder ErgData verbunden war; sonst `notes` und „HR: keine Daten“.
2. Schlagdaten nur bei `stroke_data=true` (ErgData-Aufzeichnung). Ohne sie fehlt der HF-Anstieg innerhalb der Abschnitte.
3. Bike Erg: Pace je 1000 m, keine Watt-Berechnung aus der Pace.
4. `list_results` blättert bei vielen Einheiten auf die letzte Seite (API sortiert aufsteigend); bei Datumsfiltern reicht meist eine Seite.
5. Tests ohne Netz: `uv run --with pytest --with requests pytest -q tests/test_concept2.py` (Fixtures im API-Format unter `tests/fixtures/`).
