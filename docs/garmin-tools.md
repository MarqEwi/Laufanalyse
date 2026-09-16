# Garmin-Connect-Daten in Claude Code: Server, Tools, Parameter

Stand: September 2026. Alle Angaben wurden am Quellcode der Pakete geprüft; die
Live-Antworten der Garmin-API können je nach Uhr/Aktivität zusätzliche Felder enthalten.

## 1. Welcher MCP-Server – und warum

| Kandidat | Ergebnis |
|---|---|
| `@nicolasvegam/garmin-connect-mcp` (npm, v1.1.1 vom 15.02.2026) | **Nicht genommen.** Der Server nutzt den alten Garmin-Login (SSO-Widget → Ticket → OAuth1/OAuth2, wie `garth`). Garmin hat diesen Weg im März 2026 umgestellt; `garth` wurde deshalb am 27.03.2026 als „deprecated“ eingestellt. Außerdem kann der Server **kein MFA** (offenes Issue #11 „Not prompted for MFA code“, Login-Fehler „invalid credentials or MFA required“). |
| `mcp-garmin` (PyPI, v0.3.0, via `uvx`) | **Genommen.** Baut auf `python-garminconnect` ≥ 0.3 auf, das den aktuellen Garmin-Login (DI-OAuth2-Token, mehrere Login-Strategien inkl. Cloudflare-tauglichem `curl_cffi`) und eine **MFA-Abfrage** unterstützt. Token-Cache mit automatischer Erneuerung. Nachteil: braucht Python ≥ 3.14 (uv lädt es automatisch) und ein Tool ist fehlerhaft (siehe 4.). |

Start im Container geprüft: `uvx --python 3.14 mcp-garmin` meldet 32 Tools (mcp 1.30.0, garminconnect 0.3.15).

## 2. Anmeldung, MFA und Token-Cache

- Zugangsdaten nur als **Umgebungsvariablen**: `GARMIN_EMAIL`, `GARMIN_PASSWORD`. Sie werden vom Setup-Skript als Windows-Benutzervariablen gesetzt (Registry, keine Datei im Repo).
- `GARMINTOKENS` zeigt auf den Token-Ordner (Standard `%USERPROFILE%\.garminconnect`). **Wichtig:** `garminconnect` lädt und speichert Tokens nur, wenn dieser Pfad gesetzt ist. Ohne ihn würde `mcp-garmin` bei jedem Start ein Passwort-Login machen und an MFA scheitern. Deshalb wird `GARMINTOKENS` beim `claude mcp add` mit `-e` übergeben.
- Ablauf: Erstanmeldung mit `scripts/garmin_login.py` (fragt Passwort ohne Echo und den MFA-Code ab) → Datei `garmin_tokens.json` (DI-Access-Token + Refresh-Token + Client-ID). Danach lädt jeder Start die Tokens; das Access-Token wird bei Ablauf (JWT-`exp`, 15-Minuten-Puffer) automatisch per Refresh-Token erneuert – ohne Passwort und ohne MFA.
- Neu anmelden ist nur nötig, wenn Garmin das Refresh-Token ungültig macht (Passwortänderung, Sitzungswiderruf, längere Inaktivität). Symptom: Tool-Antwort „Authentication failed … Run mcp-garmin-login“. Lösung: `uv run scripts/garmin_login.py --force`.
- Bei „429 Too Many Requests“ einige Minuten warten; nicht wiederholt einloggen.
- `mcp-garmin` verlangt `GARMIN_EMAIL`/`GARMIN_PASSWORD` auch dann, wenn Tokens gültig sind (reine Vollständigkeitsprüfung beim Start).

## 3. MCP-Tools des Servers `garmin` (mcp-garmin 0.3.0)

Namen in Claude Code: `mcp__garmin__<tool>`. Rückgabe ist immer das rohe Garmin-JSON.

### Aktivitäten finden

| Tool | Parameter | Liefert |
|---|---|---|
| `get_activities` | `start` (int, 0), `limit` (int, 20) | Liste neuester Aktivitäten (alle Sportarten), flach: `activityId`, `activityName`, `activityType.typeKey` (z. B. `running`, `trail_running`), `startTimeLocal`, `distance` (m), `duration` (s), `averageSpeed` (m/s), `averageHR`, `maxHR`, `averageRunningCadenceInStepsPerMinute`, `elevationGain`, `calories`, `aerobicTrainingEffect` … |
| `get_activities_by_date` | `start_date`, `end_date` (YYYY-MM-DD), `activity_type` (optional, z. B. `running`) | wie oben, Zeitraum-gefiltert |
| `get_last_activity` | – | Liste mit der neuesten Aktivität (egal welche Sportart) |
| `get_activity` | `activity_id` (int) | Detail-Summary mit `summaryDTO` (`distance`, `duration`, `movingDuration`, `averageSpeed`, `averageHR`, `maxHR`, `averageRunCadence`, `elevationGain/Loss`, `startTimeLocal/GMT`, `trainingEffect`, `vO2MaxValue` …), `activityTypeDTO.typeKey`, `metadataDTO` |

### Detaildaten eines Laufs

| Daten | Tool | Parameter | Inhalt | Status |
|---|---|---|---|---|
| **Laps/Splits** (Rundentaste, strukturierte Workouts) | `get_activity_splits` | `activity_id` | `lapDTOs[]`: `lapIndex`, `startTimeGMT`, `distance` (m), `duration` (s), `movingDuration`, `averageSpeed`/`maxSpeed` (m/s → Pace = 1000/v), `averageHR`, `maxHR`, `averageRunCadence`, `maxRunCadence`, `elevationGain/Loss`, `averagePower`, bei Workouts `intensityType` (`ACTIVE`/`REST`/`WARMUP`/`COOLDOWN`) und `wktStepIndex` | ✅ funktioniert |
| **Sekunden-Zeitreihe** (HF, Geschwindigkeit, Höhe, Kadenz, Leistung) | `get_activity_details` | `activity_id` | `metricDescriptors[]` (Spaltenbeschreibung: `directTimestamp`, `sumDuration`, `sumDistance`, `directSpeed`, `directHeartRate`, `directElevation`, `directRunCadence`, `directPower`, …) + `activityDetailMetrics[].metrics[]` | ❌ **in mcp-garmin 0.3.0 defekt**: ruft die Bibliothek mit `maxchart=0` auf, `garminconnect` ≥ 0.3.2 wirft `ValueError: maxchart must be a positive integer`. → Zeitreihe über `scripts/garmin_export.py` holen (nutzt dieselbe Bibliothek direkt mit `maxchart=100000`). Auch unabhängig vom Fehler wäre eine 1-Hz-Zeitreihe (mehrere hundert KB JSON) im Chat-Kontext unbrauchbar. |
| **HF-Zonen-Verteilung** | `get_activity_hr_zones` | `activity_id` | Liste `{zoneNumber, secsInZone, zoneLowBoundary}` für Zone 1–5 | ✅ |
| **Wetter** | `get_activity_weather` | `activity_id` | `temp`, `apparentTemp`, `relativeHumidity`, `windSpeed`, `windDirectionCompassPoint`, `weatherTypeDTO.desc`, `issueDate` | ✅ – **Annahme:** `temp`/`apparentTemp` in °F, `windSpeed` in mph (das Export-Skript rechnet um und behält die Rohwerte in `weather.raw_*`; beim ersten echten Lauf gegen Garmin Connect prüfen). |
| Ausrüstung | `get_activity_gear` | `activity_id` | Schuhe etc. | ✅ |

Nicht als MCP-Tool vorhanden, aber vom Export-Skript direkt über die Bibliothek genutzt:

| Bibliotheksaufruf (`garminconnect.Garmin`) | Zweck |
|---|---|
| `get_activity_typed_splits(id)` | `/typedsplits` – Intervall-Struktur strukturierter Workouts (wird in `raw/typed_splits.json` abgelegt) |
| `get_activity_details(id, maxchart=100000, maxpoly=1)` | vollständige Zeitreihe |
| `download_activity(id, dl_fmt=ORIGINAL)` | Original-FIT als ZIP (nicht im Skript aktiv, für spätere Erweiterung) |

### Weitere nützliche Tools (Kontext für die Analyse)

`get_training_status(date)`, `get_training_readiness(date)`, `get_hrv_data(date)`, `get_sleep_data(date)`, `get_resting_heart_rate(date)`, `get_max_metrics(date)` (VO2max), `get_personal_records()`, `get_workouts()` / `get_workout(workout_id)`, `get_user_profile()`, `get_daily_summary(date)`, `get_body_battery(date)`, `get_stress_data(date)`, `get_steps_data(date)`, `get_spo2_data(date)`, `get_respiration_data(date)`, `get_intensity_minutes(date)`, `get_body_composition(start_date,end_date)`, `get_weigh_ins(start_date,end_date)`, `get_fitness_age(date)`, `get_activity_exercise_sets(activity_id)`, `get_server_version()`.

## 4. Bekannte Einschränkungen

1. `get_activity_details` (MCP) ist defekt, s. o. Workaround: Export-Skript.
2. Die Zeitreihe von Garmin ist bereits geglättet/gesampelt (meist 1 s, bei „Smart Recording“ unregelmäßig). Die Uhr-Rohdaten (FIT) haben dieselbe Auflösung.
3. `intensityType` in den Laps ist nur bei strukturierten Workouts gesetzt; bei Rundentaste greift die Pace-Heuristik des Skripts.
4. Wetter-Einheiten: Annahme °F/mph, siehe oben.
5. Rate-Limits: Garmin blockt zu viele Logins (429). Tokens deshalb immer über `GARMINTOKENS` wiederverwenden.

## 5. Datenstruktur des Exports (`data/garmin/<datum>_<id>/`)

| Datei | Inhalt |
|---|---|
| `summary.md` | Bericht (Überblick, Lap-Tabelle, Intervall-Auswertung, HF-Zonen) – deutsch, Pace min/km, Zeiten mm:ss |
| `analysis.json` | alles Berechnete: `summary`, `weather`, `laps[]` (mit `type`, `hr_start`, `hr_end`, `hr_rise`, `recovery_to_threshold_s`), `intervals` (Ø-Pace, Ø-HF, Streuung, Trend, Erholung), `hr_zones[]`, `notes[]` |
| `laps.csv` / `laps.json` | normalisierte Laps |
| `timeseries.csv` | `t_s, timestamp, distance_m, speed_m_s, pace_s_per_km, hr, elev_m, cadence_spm, power_w, gap_speed_m_s, temp_c` |
| `raw/*.json` | unveränderte API-Antworten (`activity`, `splits`, `typed_splits`, `details`, `hr_zones`, `weather`) |

FIT-Fallback (`--fit datei.fit`, auch ZIP aus dem Garmin-Connect-Export „Original“) erzeugt dieselbe Struktur; Wetter fehlt dann, HF-Zonen kommen aus `session.time_in_hr_zone` (Zonengrenzen nur, wenn `hr_zone`-Nachrichten in der Datei sind).
