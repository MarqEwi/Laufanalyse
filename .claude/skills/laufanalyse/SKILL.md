---
name: laufanalyse
description: Analysiert einen Lauf aus Garmin Connect (Standard letzter Lauf, optional Datum oder Aktivitäts-ID) – Überblick, Lap-/Intervall-Tabelle mit HF-Anstieg, Intervall-Auswertung, HF-Zonen, Kurzfazit. Beantwortet Nachfragen zu einzelnen Intervallen und vergleicht Läufe aus den gesicherten Daten. Deutsch, Pace in min/km, Zeiten mm:ss.
argument-hint: "[leer = letzter Lauf | YYYY-MM-DD | Aktivitäts-ID | --fit datei.fit] [--recovery-hr 140]"
---

# Laufanalyse

Du wertest einen Lauf des Nutzers aus. Datenquelle ist der MCP-Server `garmin` (Tools `mcp__garmin__*`,
definiert in `scripts/garmin_mcp_server.py`). Er läuft auf dem PC und in Cloud-Sessions (Smartphone)
identisch. Das Tool `analyze_run` lädt Summary, Laps, Sekunden-Zeitreihe, HF-Zonen und Wetter, sichert
alles unter `data/garmin/<YYYY-MM-DD>_<id>/` und liefert den fertigen Bericht plus Kennzahlen.

## Regeln

- Antworte auf Deutsch. Pace immer `m:ss min/km`, Distanzen in km (2 Nachkommastellen), Zeiten `mm:ss` (ab 1 h `h:mm:ss`).
- **Nie Werte schätzen.** Fehlt etwas (Zeitreihe, Zonen, Wetter), sag es und nenne die Alternative (FIT-Export, anderes Tool). `analysis.notes` enthält solche Lücken.
- Rohe Zeitreihen nicht in den Chat laden. Arbeite mit `analysis` / `summary_md`; `timeseries.csv` nur gezielt mit kleinen Skripten auswerten.
- Belastungs-/Erholungs-Laps: Bei strukturierten Workouts liefert Garmin `intensityType` (Quelle `workout`); sonst Pace-Heuristik (schnelle Pace-Gruppe deutlich schneller als Gesamt-Ø = Belastung; langsame Laps davor = Aufwärmen, dazwischen = Erholung, danach = Auslaufen). Wirkt das Ergebnis unplausibel (z. B. Steigerungslauf), sag es und wiederhole mit anderem `work_factor` (Standard 0.93).
- Erholungsschwelle: Standard 140 bpm (`recovery_hr`); nennt der Nutzer eine andere Zahl, verwende sie.

## Ablauf

### 1. Lauf bestimmen

- Kein Argument → letzter Lauf. Datum `YYYY-MM-DD` → Lauf an dem Tag. Zahl → Aktivitäts-ID. `--fit pfad` → FIT-Datei ohne API.
- Erst `mcp__garmin__list_exported` aufrufen: Ist der Lauf schon gesichert und sagt der Nutzer nicht „neu laden“, lies `analysis.json` aus dem Ordner und gehe zu Schritt 3.
- Bei Datum mit mehreren Läufen: `mcp__garmin__get_activities_by_date` (`start_date`, `end_date`) zeigen und kurz nachfragen.

### 2. Daten laden und sichern

- API: `mcp__garmin__analyze_run` mit `activity_id` **oder** `date` (beides leer = letzter Lauf), optional `recovery_hr`, `work_factor`. Rückgabe: `output_dir`, `summary_md`, `analysis`.
- FIT-Datei: `mcp__garmin__analyze_fit` mit `fit_path` (auch ZIP aus Garmin Connect „Original exportieren“; Wetter fehlt dann).
- Ohne MCP (Notfall): `uv run scripts/garmin_export.py --id <ID> --print` bzw. `--last`, `--date`, `--fit`; schreibt dieselben Dateien.
- Fehler „Garmin-Anmeldung fehlgeschlagen“: `mcp__garmin__login_status` aufrufen und dem Nutzer den passenden Weg nennen:
  - PC: `uv run scripts/garmin_login.py --force` im Terminal (MFA-Code wird dort abgefragt).
  - Cloud-Session: `uv run scripts/garmin_login.py --mfa-file /tmp/mfa.txt` per Bash **im Hintergrund** starten (GARMIN_EMAIL/GARMIN_PASSWORD müssen in der Umgebung gesetzt sein), den Nutzer nach dem MFA-Code fragen, den Code mit `echo <code> > /tmp/mfa.txt` schreiben, Ausgabe des Skripts prüfen. Danach `uv run scripts/garmin_login.py --show-token` und den Nutzer bitten, `GARMIN_TOKENS_B64` in der Cloud-Umgebung zu aktualisieren, damit künftige Sessions ohne MFA starten. Den Token-Wert nie in Dateien des Repos schreiben.
  - „429“: einige Minuten warten, nicht wiederholt anmelden.

### 3. Ausgabe (immer diese fünf Abschnitte)

`summary_md` enthält Abschnitte 1–4 fertig formatiert; übernimm sie und ergänze das Fazit.

1. **Überblick** – Datum, Distanz, Dauer, Ø-Pace, Ø-HF, Max-HF, Höhenmeter, Wetter (`analysis.summary`, `analysis.weather`).
2. **Intervall-/Lap-Tabelle** – pro Lap: Nr, Distanz, Zeit, Pace, Ø-HF, Max-HF, HF-Anstieg (`hr_end − hr_start`, mit beiden Werten), Kadenz. Belastung fett/markiert, Erholung/Aufwärmen/Auslaufen benannt (`laps[].type`).
3. **Intervall-Auswertung** (nur `type == belastung`, aus `analysis.intervals`): Anzahl × Distanz, Ø-Pace, Ø-HF, Streuung (`pace_stdev_s_per_km`, Spanne), Trend (`trend_text`, `pace_trend_s_per_km_per_interval`, `hr_trend_bpm_per_interval`, erstes vs. letztes Intervall), Erholungszeit bis HF < Schwelle (`recovery_to_threshold_s_list`, Ø). Kein Intervall erkannt → sagen (Dauerlauf) und stattdessen Pace-/HF-Verlauf über die km-Laps beschreiben.
4. **HF-Zonen** – Tabelle Zone / ab bpm / Minuten / Prozent (`analysis.hr_zones`). Zusätzlich die Einheit gegen die
   Coach-Zonen einordnen (Pace und HF, LTHR 174, Schwelle 4:17): Tabelle im Archiv unter
   `$TRAINING_ARCHIV_DIR/2026/2026-06-01 Grundlagen/auswertung.md` (Stand 01.06.2026, bis zum nächsten Test).
5. **Kurzfazit** – 3–4 Sätze Klartext: Was sagt die Einheit über Form und Ermüdung? Stütze dich auf Pace-Streuung (gleichmäßig = kontrolliert), Pace-Trend (langsamer werdend = zu schnell angegangen/ermüdet), HF-Drift bei gleicher Pace, HF-Anstieg innerhalb der Intervalle, Erholungszeit (kurz = gute Erholungsfähigkeit), Zonenverteilung, Wetter (Hitze erklärt höhere HF). Keine medizinischen Diagnosen. Optional Kontext über `mcp__garmin__get_training_context(date)` (Trainingsstatus, HRV, Schlaf), wenn der Nutzer nach Ursachen fragt.

6. **Coach-Text** – zum Schluss als Codeblock, exakt im Format aus `docs/coach-text.md` (Kopf in drei Zeilen,
   Leerzeile zwischen allen Blöcken, Gewichte als „Sled+100 kg“, Pace mit Einheit). RPE und Stationsgewichte
   vom Nutzer erfragen, wenn er sie nicht genannt hat. Der Text, der wirklich an den Coach ging, kommt per
   `/archiv` als `coach.txt` ins Archiv.

`analysis.notes` (fehlende Daten, API-Fehler) am Ende nennen.

## Nachfragen mit bereits geladenen Daten

Nach Schritt 2 liegen alle Daten in `output_dir`; nichts neu ziehen.

- „Wie schnell war ich in Intervall 3, welche Ø-HF?“ → das 3. Lap mit `type == belastung` aus `analysis.laps` (bzw. `analysis.json` im Ordner), Pace/Ø-HF/Max-HF/HF-Anstieg nennen. „Intervall n“ zählt nur Belastungs-Laps; „Lap n“/„Runde n“ zählt alle Laps.
- Verlauf innerhalb eines Intervalls (HF-Kurve, Pace-Schwankung): kleines Python-Snippet über `timeseries.csv`, Fenster `start_s ≤ t_s < end_s` des Laps.
- „Wie lange bis HF unter 130?“ → direkt aus `timeseries.csv` berechnen (offline, bevorzugt) oder `analyze_run` mit `recovery_hr=130` wiederholen.
- Ausgedünnter Verlauf ohne Dateizugriff: `mcp__garmin__get_activity_timeseries(activity_id, step_s=10)`.

## Vergleiche zwischen Läufen

- „Vergleiche die 1000er von heute mit denen vor zwei Wochen“: `mcp__garmin__list_exported` zeigt gesicherte Läufe; fehlende Läufe per `analyze_run` mit `date` bzw. `activity_id` sichern (Datum über `get_activities_by_date` finden).
- Vergleiche pro Lauf die Belastungs-Laps mit ähnlicher Distanz (±10 %): Anzahl, Ø-Pace, Ø-HF, Streuung, Trend, Erholungszeit; dann Interpretation: gleiche Pace bei niedrigerer HF = Formverbesserung; schnellere Pace bei gleicher HF ebenso; höhere HF bei gleicher Pace → Ermüdung/Hitze/Schlaf prüfen (`get_training_context`).
- Tabelle nebeneinander (Lauf A | Lauf B | Differenz).

## Datenordner

`data/garmin/<YYYY-MM-DD>_<id>/` (`LAUFANALYSE_DATA_DIR` oder `./data/garmin`): `summary.md`, `analysis.json`, `laps.csv`, `laps.json`, `timeseries.csv`, `raw/*.json`. In Cloud-Sessions ist der Ordner nur für die Dauer der Session vorhanden (nicht versioniert); dauerhafte Vergleiche über längere Zeiträume laufen am besten auf dem PC oder indem der Nutzer die Ordner selbst sichert.
