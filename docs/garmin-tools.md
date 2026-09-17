# Garmin-Connect-Daten in Claude Code: Server, Tools, Parameter

Stand: 17.09.2026. Geprüft am Quellcode von `python-garminconnect` 0.3.15, an den beiden Kandidaten-Servern
und an echten Aktivitäten des Kontos (Dauerlauf 16.09.2026, Intervall-Workout 14.09.2026, Cloud-Session);
die Live-Antworten der Garmin-API können je nach Uhr/Aktivität zusätzliche Felder enthalten.

## 1. Welcher MCP-Server – und warum

Anforderung: identisch nutzbar auf dem Windows-PC **und** in Claude-Code-Cloud-Sessions (Smartphone,
claude.ai/code). Cloud-Sessions laufen in einem frischen Linux-Container: kein Windows-User-Scope, kein
Token-Cache, keine interaktive MFA-Abfrage.

| Kandidat | Ergebnis |
|---|---|
| `@nicolasvegam/garmin-connect-mcp` (npm, v1.1.1 vom 15.02.2026) | **Nicht genommen.** Nutzt den alten Garmin-Login (SSO-Widget → Ticket → OAuth1/OAuth2 wie `garth`). Garmin hat diesen Weg im März 2026 umgestellt; `garth` wurde deshalb am 27.03.2026 eingestellt. Außerdem **kein MFA** (offenes Issue #11, Fehler „invalid credentials or MFA required“). |
| `mcp-garmin` (PyPI, v0.3.0, `uvx`) | **Nicht genommen, obwohl der Login funktioniert.** Braucht Python ≥ 3.14; das `uv` im Cloud-Container kennt nur Python 3.14.0rc2, mit dem der Server wegen einer pydantic-Inkompatibilität abstürzt (im Container reproduziert). Zwei weitere Fehler: `get_activity_details` ruft die Bibliothek mit `maxchart=0` auf (→ `ValueError`, Zeitreihe nicht abrufbar) und Tokens werden nur mit gesetztem `GARMINTOKENS` geladen/gespeichert. |
| **`scripts/garmin_mcp_server.py` (eigener Server im Repo)** | **Genommen.** ~250 Zeilen auf Basis derselben Bibliothek `python-garminconnect` ≥ 0.3 (aktueller Garmin-Login mit DI-OAuth2-Token, mehrere Login-Strategien inkl. Cloudflare-tauglichem `curl_cffi`, MFA-Unterstützung). Python ≥ 3.11, Start mit `uv run` (Abhängigkeiten per PEP 723 automatisch). Läuft in Cloud-Container (getestet), auf Windows und macOS gleich. Liefert kompakte, normalisierte Daten statt roher JSON-Berge und enthält `analyze_run`, das die komplette Sicherung + Auswertung in einem Aufruf macht. |

Registrierung:

- **Im Repo** (gilt auf jedem Gerät, auch in der Cloud): `.mcp.json` → `uv run scripts/garmin_mcp_server.py`; `.claude/settings.json` gibt Projekt-Server automatisch frei.
- **PC, User-Scope** (für andere Projekte): `claude mcp add garmin -s user -e GARMINTOKENS=… -- uv run <repo>\scripts\garmin_mcp_server.py` (macht das Setup-Skript).

## 2. Anmeldung, MFA und Token-Cache auf allen Geräten

Garmin verwendet seit 2026 DI-OAuth2-Tokens: ein kurzlebiges Access-Token (JWT mit `exp`) und ein
Refresh-Token. `garminconnect` erneuert das Access-Token automatisch (15-Minuten-Puffer), ohne Passwort und
ohne MFA. Ein neues Login (mit MFA) ist nur nötig, wenn das Refresh-Token ungültig wird (Passwortänderung,
Sitzungswiderruf, längere Nichtnutzung, evtl. Rotation durch Garmin).

| Variable | Zweck |
|---|---|
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | Nur für ein Passwort-Login nötig (keine Tokens). PC: Benutzer-Umgebungsvariablen (Registry), Cloud: Umgebungsvariablen der Cloud-Umgebung. |
| `GARMINTOKENS` | Token-Ordner (Standard `~/.garminconnect`). Datei `garmin_tokens.json` = `{di_token, di_refresh_token, di_client_id}`. |
| `GARMIN_TOKENS_B64` (oder `GARMIN_TOKENS_JSON`) | Token-Inhalt als base64/JSON für Umgebungen ohne dauerhaften Ordner (Cloud). Wird beim Start in den Token-Ordner geschrieben. Erzeugen: `uv run scripts/garmin_login.py --show-token`. |
| `LAUFANALYSE_DATA_DIR` | Ausgabeordner (Standard `./data/garmin`). |

Abläufe:

1. **PC (einmalig):** `uv run scripts/garmin_login.py` → Passwort ohne Echo, MFA-Code → Tokens in `%USERPROFILE%\.garminconnect`.
2. **Cloud/Smartphone:** Token vom PC übertragen: `--show-token` → Wert als `GARMIN_TOKENS_B64` in der Cloud-Umgebung (claude.ai/code → Umgebung bearbeiten → Umgebungsvariablen). Jede Session schreibt ihn beim Start in den Token-Ordner (Session-Start-Hook oder beim ersten Tool-Aufruf).
3. **MFA direkt in einer Cloud-Session** (wenn die Tokens abgelaufen sind und kein PC greifbar ist): `uv run scripts/garmin_login.py --mfa-file /tmp/mfa.txt` im Hintergrund starten; das Skript wartet bis zu 5 Minuten auf die Datei; Claude schreibt den vom Nutzer genannten Code mit `echo 123456 > /tmp/mfa.txt`. Danach `--show-token` und `GARMIN_TOKENS_B64` in der Umgebung aktualisieren. Voraussetzung: `GARMIN_EMAIL`/`GARMIN_PASSWORD` in der Umgebung, Netzwerk auf `*.garmin.com` **und** `pypi.org`, `files.pythonhosted.org` freigegeben (sonst installiert `uv` keine Abhängigkeiten; Symptom im Session-Start-Hook: „Abhängigkeiten konnten nicht vorinstalliert werden“, bei `uv run`: „index URL … 403 Forbidden“, MCP-Server `garmin`: „Connection closed“).

Garmin bremst wiederholte Logins mit „429 Too Many Requests“ – deshalb Tokens immer wiederverwenden und
nach 429 einige Minuten warten. Login aus Rechenzentrums-IPs (Cloud) kann von Cloudflare blockiert werden;
die Bibliothek probiert fünf Strategien, sicherer ist aber immer der Token-Transfer vom PC.

Beobachtung 17.09.2026 (Cloud-Session, Konto mit aktivem MFA): Das Passwort-Login aus dem Container lief
ohne MFA-Abfrage und ohne Cloudflare-Block durch – bereits der erste Aufruf von `login_status` hat sich
angemeldet und `garmin_tokens.json` angelegt. Ob Garmin den MFA-Code verlangt, entscheidet Garmin pro Login;
der `--mfa-file`-Weg bleibt der Fallback, wenn die Abfrage kommt.

## 3. Tools des MCP-Servers `garmin`

Namen in Claude Code: `mcp__garmin__<tool>`. Rückgabe: normalisiertes JSON (Distanzen m, Zeiten s, Pace
s/km + `pace_str` „m:ss“, `duration_str`).

### Aktivitäten finden

| Tool | Parameter | Liefert | Garmin-Endpunkt |
|---|---|---|---|
| `get_activities` | `start`=0, `limit`=10, `activity_type`? (z. B. `running`) | kompakte Liste: `activity_id`, `name`, `type`, `start_local`, `date`, `distance_km`, `duration_str`, `pace_str`, `avg_hr`, `max_hr`, `elev_gain_m`, `avg_cadence_spm` | `/activitylist-service/activities/search/activities` |
| `get_activities_by_date` | `start_date`, `end_date` (YYYY-MM-DD), `activity_type`=`running` | wie oben | dito mit Datumsfilter |
| `get_last_run` | – | neuester Lauf (`type` enthält `running`), kompakt | dito |
| `get_activity` | `activity_id` | normalisierte Zusammenfassung (`distance_m`, `duration_s`, `pace_s_per_km`, `avg_hr`, `max_hr`, `avg_cadence_spm`, `elev_gain_m`, `elev_loss_m`, `calories`, `avg_power_w`, `aerobic_te`, `anaerobic_te`, `vo2max`, `start_local`, `start_gmt`) | `/activity-service/activity/{id}` (`summaryDTO`) |

### Detaildaten eines Laufs

| Daten | Tool | Parameter | Inhalt | Garmin-Endpunkt / Bibliothek |
|---|---|---|---|---|
| **Laps/Splits** (Rundentaste, strukturierte Workouts) | `get_activity_laps` | `activity_id` | je Lap: `nr`, `start_s`, `end_s`, `distance_m`, `duration_s`, `pace_s_per_km`/`pace_str`, `avg_hr`, `max_hr`, `avg_cadence_spm`, `elev_gain_m`, `avg_power_w`, `intensity`, `workout_step`. **Geprüft:** Auto-Laps (1 km) haben `intensity`/`workout_step` = null; ein Garmin-Workout liefert `warmup`/`active`/`recovery`/`cooldown` plus `workout_step` (Nummer des Workout-Schritts, gleiche Nummer = gleicher Block, z. B. 10×90 s = Schritt 4, 10×60 s = Schritt 7). Am Workout-Ende folgt meist ein Stummel-Lap (wenige Meter, `intensity=active`, `workout_step=null`) – `analyze_run` wertet Laps unter `min_lap_km` nicht als Belastung. `avg_power_w` ist null ohne Leistungsquelle. | `/activity-service/activity/{id}/splits` → `lapDTOs[]` (`get_activity_splits`) |
| Workout-Struktur | `get_activity_typed_splits` | `activity_id` | Rohdaten | `/typedsplits` (`get_activity_typed_splits`) |
| **Sekunden-Zeitreihe** (HF, Geschwindigkeit/Pace, Höhe, Kadenz, Leistung) | `get_activity_timeseries` | `activity_id`, `step_s`=10, `max_chart`=100000 | ausgedünnte Zeilen `t_s`, `distance_m`, `hr`, `pace_s_per_km`, `elev_m`, `cadence_spm`, `power_w` + `points_total`; Felder mit null werden weggelassen. Vollauflösung schreibt `analyze_run` nach `timeseries.csv`. **Geprüft (Forerunner-Lauf, 1-s-Aufzeichnung, 705 Punkte auf 44 min):** geliefert werden HF, Geschwindigkeit/Pace, Höhe, Kadenz, Distanz, Dauer, GPS, `directAirTemperature`, `directVerticalOscillation`, `directGroundContactTime`, `directStrideLength`, `directVerticalRatio`, `directGroundContactBalanceLeft`, `directPerformanceCondition`. **Nicht geliefert:** `directPower` (keine Leistungsquelle) → `power_w` fehlt. `temp_c` ist der Uhrensensor (29 °C bei 17 °C Wetter), nicht die Lufttemperatur. Laufdynamik-Spalten (`gct_ms`, `stride_cm`, `vert_osc_mm`) erscheinen in `timeseries.csv`, wenn die Uhr/der Gurt sie liefert (16.09. ja, 14.09. nein). | `/activity-service/activity/{id}/details?maxChartSize=…` → `metricDescriptors` (`directTimestamp`, `sumDuration`, `sumDistance`, `directSpeed`, `directHeartRate`, `directElevation`, `directRunCadence`, `directPower`, …) + `activityDetailMetrics[].metrics[]` (`get_activity_details(id, maxchart, maxpoly)`) |
| **HF-Zonen-Verteilung** | `get_activity_hr_zones` | `activity_id` | `zone`, `low_bpm`, `seconds`, `minutes`, `percent` (Zonen 1–5) | `/hrTimeInZones` (`get_activity_hr_in_timezones`) |
| **Wetter** | `get_activity_weather` | `activity_id` | `temp_c`, `feels_like_c`, `humidity_pct`, `wind_kmh`, `wind_dir`, `condition` + `raw` (u. a. `dewPoint`, `windDirection` in Grad, `weatherStationDTO` = nächste Wetterstation, z. B. EDLP Paderborn/Lippstadt) | `/weather` (`get_activity_weather`). **Bestätigt 16.09.2026:** `temp`/`apparentTemp`/`dewPoint` kommen in °F, `windSpeed` in mph. Rohwert `temp=63` → 17,2 °C, `dewPoint=55` → 12,8 °C, was zu 77 % Luftfeuchte bei 17,2 °C passt (Taupunkt rechnerisch ≈ 13 °C); `windSpeed=4` → 6,4 km/h. Die Umrechnung stimmt, Rohwerte bleiben unter `raw`. |

### Komplettanalyse und Sicherung

| Tool | Parameter | Wirkung |
|---|---|---|
| `analyze_run` | `activity_id`? , `date`? (beides leer = letzter Lauf), `recovery_hr`=140, `work_factor`=0.93, `min_lap_km`=0.2, `out_dir`? | holt Summary, Laps, Zeitreihe, Zonen, Wetter; schreibt `<out>/<datum>_<id>/` (siehe 5.); liefert `output_dir`, `summary_md` (Bericht Abschnitte 1–4), `analysis` (Laps mit `type`, `hr_start`, `hr_end`, `hr_rise`, `recovery_to_threshold_s`; `intervals` inkl. `blocks` je `workout_step` und `recovery_to_threshold_reached`; `hr_zones`; `notes`). `min_lap_km` gilt auch im Workout-Pfad (Stummel-Laps werden nicht als Belastung gewertet, Hinweis in `notes`). |
| `analyze_fit` | `fit_path`, sonst wie oben | dasselbe aus einer FIT-/ZIP-Datei (Fallback ohne API, ohne Wetter) |
| `list_exported` | `out_dir`? | gesicherte Läufe mit Kennzahlen (für Vergleiche ohne API) |

### Kontext und Status

| Tool | Parameter | Inhalt |
|---|---|---|
| `get_training_context` | `date` | Trainingsstatus, Trainingsbereitschaft, HRV (ohne 5-Minuten-Rohwerte), Schlaf (`dailySleepDTO`), Ruhepuls |
| `get_user_profile` | – | Profil/Einheiten |
| `login_status` | – | Token-Ordner, gesetzte Variablen, Anmeldung ok/Fehlertext |

## 3a. Workouts anlegen (`scripts/garmin_workout.py`)

`python-garminconnect` kann Workouts hochladen (`upload_workout`, JSON wie Garmin Connect es liefert), im
Kalender terminieren (`schedule_workout(id, "YYYY-MM-DD")`) und löschen (`delete_workout`). Das Skript baut das
JSON aus einer kurzen Spezifikation (siehe Docstring, Beispiele in `workouts/`). Geprüft am 17.09.2026 an den
vorhandenen Workouts des Kontos:

| Element | Garmin-JSON |
|---|---|
| Sportart | `sportType` `{sportTypeId, sportTypeKey}`: running=1, cycling=2, other=3 (Rudern), swimming=4, walking=9 |
| Schritt | `ExecutableStepDTO` mit `stepType` (warmup=1, cooldown=2, interval=3, recovery=4, rest=5), `endCondition` (lap.button=1, time=2 in s, distance=3 in m), `targetType` |
| Ziel HF-Bereich | `heart.rate.zone` (id 4) mit `targetValueOne`/`targetValueTwo` in bpm, `zoneNumber` null |
| Ziel HF-Zone | `heart.rate.zone` mit `zoneNumber` 1–5, Werte null |
| Ziel Pace | `pace.zone` (id 6) mit `targetValueOne` = schnellere, `targetValueTwo` = langsamere Geschwindigkeit in m/s (4:32 min/km = 3,676 m/s) |
| Wiederholung | `RepeatGroupDTO` mit `numberOfIterations`, `endCondition` iterations=7, `workoutSteps` |

Hinweis: In Claude-Code-Cloud-Sessions kann der Upload von der Berechtigungsprüfung als externer Schreibzugriff
blockiert werden; dann `--dry-run` zur Kontrolle und den Upload am PC ausführen oder eine Bash-Regel für
`uv run scripts/garmin_workout.py` in den Einstellungen freigeben.

## 4. Bekannte Einschränkungen

1. Die Zeitreihe von Garmin ist bereits gesampelt (meist 1 s, bei „Smart Recording“ unregelmäßig).
2. `intensity` in den Laps ist nur bei strukturierten Workouts gesetzt; bei Rundentaste greift die Pace-Heuristik.
3. Wetter-Einheiten: °F/mph bestätigt (16.09.2026), Umrechnung im Skript korrekt.
4. Rate-Limits und Cloudflare: Logins sparsam, Tokens wiederverwenden.
5. In Cloud-Sessions ist `data/garmin/` nur für die Session vorhanden (Container wird verworfen, Ordner ist nicht versioniert). Langfristige Vergleiche: auf dem PC sichern oder Ordner selbst archivieren.
6. Refresh-Token-Rotation: Erneuert Garmin das Refresh-Token, kann eine ältere Kopie in `GARMIN_TOKENS_B64` ungültig werden. Symptom: „Authentication failed“ in der Cloud, obwohl der PC funktioniert → auf dem PC `--show-token` neu ausführen und die Variable aktualisieren.
7. Erholungszeit bis `recovery_hr`: Bei kurzen Pausen (40–50 s) fällt die HF meist nicht unter 140, bevor das nächste Intervall beginnt; `recovery_to_threshold_s` ist dann null und `recovery_to_threshold_reached` zeigt, wie oft die Schwelle erreicht wurde. Der Ø gilt nur für diese Fälle – bei Bedarf höhere Schwelle (`recovery_hr`) wählen oder `hr_end` der Erholungs-Laps vergleichen.
8. Leistung (`power_w`, `avg_power_w`) und VO2max (`vo2max` in `get_activity`) kamen bei den geprüften Läufen leer zurück; Leistung nur mit Leistungsquelle, VO2max liegt in Garmin Connect nicht in `summaryDTO`.

## 5. Datenstruktur des Exports (`data/garmin/<datum>_<id>/`)

| Datei | Inhalt |
|---|---|
| `summary.md` | Bericht (Überblick, Lap-Tabelle, Intervall-Auswertung, HF-Zonen) – deutsch, Pace min/km, Zeiten mm:ss |
| `analysis.json` | alles Berechnete: `summary`, `weather`, `laps[]` (mit `type`, `hr_start`, `hr_end`, `hr_rise`, `recovery_to_threshold_s`), `intervals` (Ø-Pace, Ø-HF, Streuung, Trend, Erholung), `hr_zones[]`, `notes[]` |
| `laps.csv` / `laps.json` | normalisierte Laps |
| `timeseries.csv` | `t_s, timestamp, distance_m, speed_m_s, pace_s_per_km, hr, elev_m, cadence_spm, power_w, gap_speed_m_s, temp_c` |
| `raw/*.json` | unveränderte API-Antworten (`activity`, `splits`, `typed_splits`, `details`, `hr_zones`, `weather`) |

FIT-Fallback (`analyze_fit` bzw. `garmin_export.py --fit`, auch ZIP aus Garmin Connect „Original exportieren“)
erzeugt dieselbe Struktur; HF-Zonen kommen aus `session.time_in_hr_zone` (Zonengrenzen nur, wenn `hr_zone`-Nachrichten
in der Datei sind).
