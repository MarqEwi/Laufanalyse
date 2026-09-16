---
name: laufanalyse
description: Analysiert einen Lauf aus Garmin Connect (Standard letzter Lauf, optional Datum oder Aktivitäts-ID) – Überblick, Lap-/Intervall-Tabelle mit HF-Anstieg, Intervall-Auswertung, HF-Zonen, Kurzfazit. Beantwortet Nachfragen zu einzelnen Intervallen und vergleicht Läufe aus den gesicherten Daten. Deutsch, Pace in min/km, Zeiten mm:ss.
argument-hint: "[leer = letzter Lauf | YYYY-MM-DD | Aktivitäts-ID | --fit datei.fit] [--recovery-hr 140]"
---

# Laufanalyse

Du wertest einen Lauf des Nutzers aus. Daten kommen aus Garmin Connect über den MCP-Server `garmin`
(Tools `mcp__garmin__*`) und über das Skript `garmin_export.py`, das Laps, Zeitreihe, HF-Zonen und
Wetter sichert und die Kennzahlen berechnet.

## Regeln

- Antworte auf Deutsch. Pace immer `m:ss min/km`, Distanzen in km (2 Nachkommastellen), Zeiten `mm:ss` (ab 1 h `h:mm:ss`).
- **Nie Werte schätzen.** Fehlt etwas (Zeitreihe, Zonen, Wetter), sag es und nenne die Alternative (FIT-Export, anderes Tool).
- Rohe Zeitreihen nicht in den Chat laden. Arbeite mit `analysis.json` / `summary.md`; die CSVs nur gezielt mit kleinen Skripten auswerten.
- Belastungs-/Erholungs-Laps: Bei strukturierten Workouts liefert Garmin `intensityType`; sonst Heuristik des Skripts (schnelle Pace-Gruppe deutlich schneller als Gesamt-Ø = Belastung; langsame Laps davor = Aufwärmen, dazwischen = Erholung, danach = Auslaufen). Wenn das Ergebnis unplausibel wirkt (z. B. Steigerungslauf), sag es und nutze `--work-factor` (Standard 0.93) neu.
- Erholungsschwelle: Standard 140 bpm (`--recovery-hr`); übernimmt der Nutzer eine andere Zahl, verwende sie.

## Pfade

- Skript: `scripts/garmin_export.py` im aktuellen Projekt, sonst `~/.claude/skills/laufanalyse/scripts/garmin_export.py` (User-Scope-Kopie). Immer mit `uv run <pfad>` starten (PEP-723-Abhängigkeiten werden automatisch installiert).
- Datenordner: `--out` bzw. `$LAUFANALYSE_DATA_DIR`, sonst `./data/garmin`. Struktur `data/garmin/<YYYY-MM-DD>_<id>/` mit `summary.md`, `analysis.json`, `laps.csv`, `timeseries.csv`, `raw/`.

## Ablauf

### 1. Lauf bestimmen

- Kein Argument → letzter Lauf. Datum `YYYY-MM-DD` → Lauf an dem Tag. Zahl → Aktivitäts-ID. `--fit pfad` → FIT-Datei ohne API.
- Prüfe zuerst, ob der Lauf schon gesichert ist: `uv run <skript> --exported` (Liste mit Datum, ID, km, Pace, Intervallen). Wenn ja und der Nutzer nicht „neu laden“ sagt: `analysis.json` aus dem Ordner lesen und direkt zu Schritt 3.
- Sonst Aktivität ermitteln – entweder das Skript lässt sie selbst suchen (`--last`, `--date`), oder du nutzt `mcp__garmin__get_activities` (`limit` 10) bzw. `mcp__garmin__get_activities_by_date` (`start_date`, `end_date`, `activity_type` = `running`) und wählst die ID (`activityType.typeKey` enthält `running`). Bei mehreren Läufen am Tag kurz nachfragen.

### 2. Daten laden und sichern

```
uv run <skript> --id <ID> --print            # oder --last / --date YYYY-MM-DD / --fit datei.fit
```

Das Skript holt Summary, Laps (`get_activity_splits`), Zeitreihe (`get_activity_details`, direkt über die Bibliothek – das MCP-Tool `get_activity_details` ist in mcp-garmin 0.3.0 defekt), HF-Zonen, Wetter; schreibt die Dateien und gibt `summary.md` aus. Danach `analysis.json` lesen. Bei Auth-Fehler: Nutzer bitten, `uv run scripts/garmin_login.py --force` auszuführen (MFA-Code nötig). Bei 429: einige Minuten warten.

### 3. Ausgabe (immer diese fünf Abschnitte)

1. **Überblick** – Datum, Distanz, Dauer, Ø-Pace, Ø-HF, Max-HF, Höhenmeter, Wetter (aus `summary` und `weather`).
2. **Intervall-/Lap-Tabelle** – pro Lap: Nr, Distanz, Zeit, Pace, Ø-HF, Max-HF, HF-Anstieg (`hr_end − hr_start`, mit beiden Werten), Kadenz. Belastung fett/markiert, Erholung/Aufwärmen/Auslaufen benannt (`laps[].type`).
3. **Intervall-Auswertung** (nur `type == belastung`, aus `intervals`): Anzahl × Distanz, Ø-Pace, Ø-HF, Streuung (`pace_stdev_s_per_km`, Spanne), Trend (`trend_text`, `pace_trend_s_per_km_per_interval`, `hr_trend_bpm_per_interval`, erstes vs. letztes Intervall), Erholungszeit bis HF < Schwelle (`recovery_to_threshold_s_list`, Ø). Kein Intervall erkannt → sagen (Dauerlauf) und stattdessen Pace-/HF-Verlauf über die km-Laps beschreiben.
4. **HF-Zonen** – Tabelle Zone / ab bpm / Minuten / Prozent (`hr_zones`).
5. **Kurzfazit** – 3–4 Sätze Klartext: Was sagt die Einheit über Form und Ermüdung? Stütze dich auf: Pace-Streuung (gleichmäßig = kontrolliert), Pace-Trend (langsamer werdend = zu schnell angegangen/ermüdet), HF-Drift bei gleicher Pace, HF-Anstieg innerhalb der Intervalle, Erholungszeit (kurz = gute Erholungsfähigkeit), Zonenverteilung, Wetter (Hitze erklärt höhere HF). Keine medizinischen Diagnosen.

Notes aus `analysis.notes` (fehlende Daten, API-Fehler) am Ende nennen.

## Nachfragen mit bereits geladenen Daten

Die Daten liegen nach Schritt 2 im Ordner des Laufs; nichts neu ziehen.

- „Wie schnell war ich in Intervall 3, welche Ø-HF?“ → das 3. Lap mit `type == belastung` aus `analysis.json` (`laps`), Pace/Ø-HF/Max-HF/HF-Anstieg nennen. „Intervall n“ zählt nur Belastungs-Laps; „Lap n“/„Runde n“ zählt alle Laps.
- Verlauf innerhalb eines Intervalls (HF-Kurve, Pace-Schwankung): kleines Python-Snippet über `timeseries.csv`, Fenster `start_s ≤ t_s < end_s` des Laps.
- „Wie lange bis HF unter 130?“ → Skript mit `--recovery-hr 130 --no-write --json` erneut laufen lassen (nutzt die API erneut) **oder** direkt aus `timeseries.csv` berechnen (bevorzugt, offline).

## Vergleiche zwischen Läufen

- „Vergleiche die 1000er von heute mit denen vor zwei Wochen“: mit `--exported` nachsehen, welche Läufe gesichert sind; fehlende Läufe per `--date` bzw. `--id` sichern (Datum über `mcp__garmin__get_activities_by_date` finden).
- Vergleiche pro Lauf die Belastungs-Laps mit ähnlicher Distanz (±10 %): Anzahl, Ø-Pace, Ø-HF, Streuung, Trend, Erholungszeit; dann Interpretation: gleiche Pace bei niedrigerer HF = Formverbesserung; schnellere Pace bei gleicher HF ebenso; höhere HF bei gleicher Pace → Ermüdung/Hitze/Schlaf prüfen (`mcp__garmin__get_training_status`, `get_hrv_data`, `get_sleep_data` für das Datum, falls der Nutzer Kontext will).
- Tabelle nebeneinander (Lauf A | Lauf B | Differenz).

## Fallback ohne API

Wenn die Garmin-API nicht erreichbar ist: Nutzer bittet in Garmin Connect (Web) beim Lauf auf „Original exportieren“; die ZIP/FIT-Datei dann mit `uv run <skript> --fit <datei> --print` verarbeiten. Struktur und Ausgabe sind identisch (ohne Wetter).
