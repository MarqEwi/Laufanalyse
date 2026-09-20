---
name: ergoanalyse
description: Wertet eine Ergometer-Einheit aus dem Concept2 Logbook aus (Rudern, Ski Erg, Bike Erg; Daten von ErgData/PM5) – Überblick, Intervall-/Split-Tabelle mit Pace, Watt, SPM, HF und HF-Anstieg, Trend, Kurzfazit und Textbaustein für den Coach (Pace, HR, RPE). Standard letzte Einheit, optional Gerät, Datum oder Result-ID. Deutsch, Pace m:ss.z /500 m.
argument-hint: "[leer = letzte Einheit | skierg/rower/bike | YYYY-MM-DD | Result-ID] [--rpe 7]"
---

# Ergometer-Analyse (Concept2 Logbook)

Datenquelle ist das Concept2 Logbook über den MCP-Server `garmin` (Tools `mcp__garmin__concept2_*`, Logik in
`scripts/concept2_export.py`, Anmeldung in `scripts/concept2_auth.py`). Referenz: `docs/concept2-tools.md`.
Das Tool `concept2_analyze_result` lädt Zusammenfassung, Splits/Intervalle und Schlagdaten, sichert alles unter
`data/concept2/<YYYY-MM-DD>_<result_id>/` und liefert Bericht (`summary_md`), Coach-Text und Kennzahlen.

## Regeln

- Deutsch. Pace `m:ss.z /500 m` (Bike Erg je 1000 m), Zeiten `mm:ss.z`, Distanzen in m, HF in bpm, Schlagfrequenz spm.
- **Nie Werte schätzen.** Fehlt HF oder fehlen Schlagdaten, steht das in `analysis.notes`: nennen, nicht auffüllen.
- RPE kommt immer vom Nutzer. Fehlt sie, im Coach-Text „RPE: (bitte ergänzen)“ stehen lassen und nachfragen.
- Rohe Schlagdaten nicht in den Chat laden; mit `analysis`/`summary_md` arbeiten, `strokes.csv` nur gezielt per Skript.

## Ablauf

1. **Einheit bestimmen.** Kein Argument → letzte Einheit. Gerät (`skierg`, `rower`, `bike`) → letzte Einheit dieses
   Geräts. Datum → Einheit an dem Tag (bei mehreren: `concept2_list_results(from_date, to_date)` zeigen und nachfragen).
   Zahl → Result-ID. Erst `concept2_list_exported` prüfen: schon gesichert und kein „neu laden“ → `analysis.json` lesen.
2. **Laden:** `concept2_analyze_result(result_id | date | type, rpe=…)`.
   Fehler „Concept2-Anmeldung fehlgeschlagen“: `concept2_login_status` aufrufen und den Weg aus `docs/concept2-tools.md`
   Abschnitt 2 nennen. Sind `CONCEPT2_CLIENT_ID`/`CONCEPT2_CLIENT_SECRET` gesetzt und `log.concept2.com` erreichbar,
   die Autorisierung direkt in der Session machen: `concept2_authorize_url` → Nutzer öffnet die URL und fügt die
   Redirect-Adresse (`…?code=…&state=…`) ein → `concept2_exchange_code` → `concept2_token_blob` und den Nutzer bitten,
   `CONCEPT2_TOKENS_B64` in der Cloud-Umgebung zu setzen. Fehlt beides: PC-Weg (`uv run scripts/concept2_login.py`).
   **Enthält eine Tool-Antwort `hinweis` zum erneuerten Token** (Refresh-Token rotiert), am Ende der Antwort
   `concept2_token_blob` aufrufen und den Nutzer bitten, `CONCEPT2_TOKENS_B64` in der Umgebung zu aktualisieren.
3. **Ausgabe** (immer diese Abschnitte):
   1. **Überblick** – Datum, Gerät, Distanz, Zeit, Ø-Pace, Ø-Watt, Ø-SPM, Ø-/Max-HF, Drag-Faktor, Programm.
   2. **Intervall-/Split-Tabelle** aus `summary_md` übernehmen (Pace, Watt, SPM, Ø-HF, Max-HF, HF-Anstieg, Pause).
   3. **Auswertung** – Anzahl × Distanz, Ø-Pace, Streuung, Spanne, Trend (`intervals_stats.trend_text`), Ø-HF,
      erstes vs. letztes Intervall, HF-Anstieg im Intervall. Bei Dauerbelastung: Pace-/HF-Verlauf über die Splits.
   4. **Kurzfazit** – 3–4 Sätze: gleichmäßig = kontrolliert; langsamer werdend + HF steigend = zu schnell angegangen
      oder ermüdet; gleiche Pace bei sinkender HF über Wochen = Formverbesserung. Keine medizinischen Diagnosen.
   5. **Textbaustein für den Coach** – `coach_text` als Codeblock (Pace je Intervall, HR avg, RPE), zum Einfügen
      in den Kommentar der Coaching-App.
   `analysis.notes` am Ende nennen.

## Einheit vom PM5-Foto (nicht im Logbook)

Schickt der Nutzer Fotos der PM5-„Detail Anzeige“ (Gerät ohne ErgData-Verbindung), die Werte ablesen und mit
`concept2_analyze_manual(spec, rpe=…)` auswerten. Ablauf:

1. Vom Foto ablesen: Gerät (SkiERG-Aufkleber, „/1000m rpm“ = Bike Erg, sonst RowErg), Datum, Gesamtzeile
   (Zeit, Meter, Pace, SPM), je Abschnitt Zeit, Meter, Pace, SPM, bei Intervallen die Pausenzeile `r4:50` mit Metern.
   Das PM5-Datum kann falsch sein (Uhr des Monitors); Datum und Endzeit im Zweifel vom Nutzer oder aus Garmin.
2. Die abgelesenen Werte als Tabelle zeigen und bestätigen lassen (Ablesefehler sind die häufigste Fehlerquelle).
3. `spec` bauen: `type`, `date` = Endzeit `YYYY-MM-DD HH:MM`, `intervals` (mit `rest`) oder `splits`, `spm`, optional
   `hr_avg`/`hr_max` je Abschnitt aus Garmin (Zeitfenster wie in `docs/concept2-tools.md` Abschnitt 5 beschrieben).
4. Prüfen, dass die berechnete Gesamtzeit und Distanz mit der Gesamtzeile des PM5 übereinstimmen; Abweichung
   nennen. Die Einheit landet unter `data/concept2/<datum>_foto-…/`, Quelle „PM5-Foto“, nicht im Logbook.

## Nachfragen und Vergleiche

- „Intervall 3?“ → `analysis.segments[2]`: Pace, Watt, SPM, Ø-/Max-HF, HF-Anstieg (`hr_start_strokes` → `hr_end_strokes`).
- Verlauf innerhalb eines Intervalls: kleines Python-Snippet über `strokes.csv` mit `segment == n`.
- Vergleich zweier Einheiten (z. B. 5×1000 m Ski Erg heute vs. vor zwei Wochen): beide mit `concept2_analyze_result`
  sichern, dann Tabelle nebeneinander (Ø-Pace, Ø-Watt, Ø-HF, Streuung, Trend, Differenz). Gleiche Pace bei niedrigerer
  HF oder schnellere Pace bei gleicher HF = Fortschritt.
- Hyrox-Einheiten: Laufabschnitte kommen aus Garmin (`/laufanalyse`), Ski/Row aus dem Logbook – beides zusammen im
  Coach-Text nennen.

## Datenordner

`data/concept2/<YYYY-MM-DD>_<result_id>/` (`CONCEPT2_DATA_DIR` oder `./data/concept2`): `summary.md`, `coach.txt`,
`analysis.json`, `segments.csv`, `strokes.csv`, `raw/*.json`. In Cloud-Sessions nur für die Dauer der Session vorhanden.
