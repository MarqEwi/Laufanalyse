---
name: workout
description: Legt ein Trainings-Workout in Garmin Connect an – aus einem Text oder Screenshot des Coach-Plans (Laufen, Rad, Hyrox/Stationen, Rudern). Baut die Schrittliste, zeigt sie zur Bestätigung, lädt sie hoch und terminiert sie im Garmin-Kalender. Auch Auflisten, Anzeigen, Terminieren und Löschen vorhandener Workouts. Deutsch.
argument-hint: "[Beschreibung oder Screenshot des Trainings] [Name] [Datum, z. B. morgen]"
---

# Workout in Garmin Connect anlegen

Datenquelle und Ziel ist der MCP-Server `garmin` (Tools `mcp__garmin__*`). Die Workout-Tools sind
`list_workouts`, `get_workout`, `create_workout`, `schedule_workout`, `list_scheduled_workouts`,
`unschedule_workout`, `delete_workout`; die Logik steckt in
`scripts/garmin_workout.py` (auch als CLI am PC nutzbar). Vorlagen liegen unter `workouts/*.json`.

## Regeln

- Deutsch. Zeiten `mm:ss`, Pace `m:ss min/km`, HF in bpm.
- **Nie hochladen, ohne die Struktur gezeigt und die Bestätigung des Nutzers bekommen zu haben.** Erst
  `create_workout(spec, dry_run=true)` aufrufen und den `text` zeigen. Sagt der Nutzer „ja“/„passt“/„hochladen“,
  dann `create_workout(spec, schedule_date=…)` ohne `dry_run`.
- Nichts erfinden: Unklare Abkürzungen im Coach-Plan (z. B. BBJ, WB, SSP) ausschreiben und im Ergebnis nennen,
  damit der Nutzer sie korrigieren kann. Fehlende Angaben (Dauer, Ziel) nachfragen statt raten.
- `delete_workout` und `unschedule_workout` nur auf ausdrücklichen Wunsch. Vor dem Terminieren mit
  `list_scheduled_workouts` prüfen, ob das Workout an dem Tag schon steht (keine Doppeleinträge).
- Die Spezifikation zusätzlich als Datei `workouts/<name_in_kleinbuchstaben>.json` speichern und auf dem
  aktuellen Branch committen/pushen, damit sie am PC und in späteren Sessions wiederverwendbar ist.

## Spezifikation

```json
{
  "name": "NXT LVL Hyrox Workout",
  "sport": "other",
  "description": "Coach-Vorgabe, Datum, RPE …",
  "steps": [
    {"type": "warmup",   "duration_s": 1200, "note": "Bike easy"},
    {"type": "interval", "duration_s": 120,  "note": "Run RPE 7"},
    {"type": "interval", "distance_m": 1000, "target": {"pace_min_km": ["4:10", "4:20"]}},
    {"type": "recovery", "duration_s": 60,   "target": {"hr_bpm": [90, 130]}},
    {"repeat": 6, "steps": [ {"type": "interval", "duration_s": 90}, {"type": "recovery", "duration_s": 40} ]},
    {"type": "cooldown", "end": "lap"}
  ]
}
```

- `sport`: `running` (Laufen), `cycling` (Rad, auch indoor), `swimming`, `walking`, `hiking`, `cardio`
  (Hyrox, Stationen, Rudern, EMOM), `strength` (Kraft), `other` (benutzerdefiniert).
  **Wichtig für die Uhr (Fenix 5X Plus):** Unter Training → Meine Workouts zeigt ein Profil nur Workouts seiner
  eigenen Sportart. `other` erscheint nirgends in dieser Liste, sondern nur als Kalender-Workout des Tages.
  Deshalb Hyrox/Stationen/Rudern immer als `cardio` anlegen (Profil Cardio bzw. ein davon kopiertes eigenes
  Profil „Hyrox“), Läufe als `running`, Rad als `cycling`. Ein „An Gerät senden“ gibt es in der API nicht
  (geprüft 20.09.2026); der Sync passiert über die Garmin-Connect-App.
- Schritt-Typen: `warmup`, `interval` (Belastung), `recovery`, `rest`, `cooldown`. Ende: `duration_s`,
  `distance_m` oder `"end": "lap"` (Rundentaste).
- Ziele: `hr_bpm [low, high]`, `hr_zone 1–5`, `pace_min_km ["schnell", "langsam"]` (nur Laufen/Gehen),
  sonst kein Ziel. Garmin verlangt bei HF immer Unter- und Obergrenze („HF unter 130“ → `[90, 130]`, das sagen).
- `note` erscheint auf der Uhr beim Schrittwechsel und sagt immer, **was zu tun ist**, mit Dauer oder Distanz
  (max. ~30 Zeichen): z. B. `Laufen 3 min Race Pace`, `Sled Push 1 min hart`, `2:30 locker joggen/gehen`,
  `20 min Bike locker`. Endet ein Schritt per Rundentaste, heißt es `… bis Lap-Taste`
  (z. B. `Ski Erg 1 km bis Lap-Taste`), nie „bis Runde“ oder „dann Runde“ (Wunsch des Nutzers, 20.09.2026).
- Jeder Abschnitt, bei dem die Uhr piepen soll, ist ein eigener Schritt. Wechselnde Stationen nicht in
  `repeat` packen; `repeat` nur für identische Wiederholungen.

## Ablauf

1. Coach-Plan lesen (Text oder Screenshot). Struktur ableiten: Aufwärmen, Blöcke, Pausen, Auslaufen.
2. Name und Datum vom Nutzer übernehmen („morgen“ → heutiges Datum + 1, Format `YYYY-MM-DD`).
3. `create_workout(spec, dry_run=true)` → `text` als Codeblock zeigen, Gesamtdauer und Annahmen nennen.
4. Nach Bestätigung: `create_workout(spec, schedule_date=…)` → Workout-ID und Termin nennen, dazu:
   „In Garmin Connect unter Training → Workouts; nach dem Sync auf der Uhr.“
5. Spezifikation unter `workouts/` speichern, committen, pushen.

Fehler „Garmin-Anmeldung fehlgeschlagen“: `mcp__garmin__login_status` aufrufen und den Weg aus der Skill
`/laufanalyse` (Abschnitt 2) nennen.

## Nachträgliche Änderungen

Garmin-Workouts lassen sich über die API nicht ändern: neues Workout anlegen (`create_workout`), altes mit
`delete_workout` entfernen (nur nach Rückfrage), Termin mit `schedule_workout` neu setzen.
