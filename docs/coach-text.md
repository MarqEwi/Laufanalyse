# Coach-Text: Format

Der Textbaustein, den der Nutzer nach einer Einheit in den Kommentar bei TrainHeroic (Coach Engelhardt) einfügt.
Vorlage vom Nutzer, 21.09.2026 – so und nicht anders aufbauen:

```
NXT LVL Hyrox RP 21.09.2026, gesamt 1:14,

HR avg 134, max 170,

RPE: 7

Warm-up 20 min locker Z1 (HR 120)

5x (3 min Lauf Curved Runner 4:22/km + 1 min Station + 2:30 Jog):

Lauf HR max 160 / 168 / 165 / 169 / 165, Ø 154 / 158 / 152 / 155 / 152

Stationen: Sled Push Sled+100 kg (HR 151), Sled Pull Sled+100 kg (165), Burpees (165), Lunges 30 kg Sandsack (168), Wall Balls 9 kg unbroken (167)

Erholung: HR vor jedem Lauf wieder bei 111-125

Cooldown Bike Erg 20 min, 8842 m, 2:16/km, 140 W, HR Ø 129

Anmerkung: alle Läufe volle 3 min in 4:22 min/km Pace durchgezogen, Curved Runner fühlte sich härter an als normaler Run
```

## Regeln

1. **Kopf in drei Zeilen**, jeweils durch Leerzeile getrennt: Einheit + Datum + Gesamtdauer / `HR avg …, max …` /
   `RPE: n`. Die RPE kommt immer vom Nutzer.
2. **Jeder Block eine eigene Zeile, Leerzeile dazwischen**, keine Einrückungen, keine Aufzählungszeichen. Die
   Coaching-App zeigt Einrückungen nicht an, Leerzeilen schon.
3. Reihenfolge wie die Einheit: Warm-up, Hauptteil (Struktur als Überschrift „5x (…):“), Werte je Wiederholung
   mit ` / ` getrennt, Stationen mit Gewicht und HF in Klammern, Erholung, Cooldown, Anmerkung.
4. **Gewichte präzise**: Schlitten als `Sled+100 kg` (Schlitten plus Zusatzgewicht), Sandsack/Wall Ball mit kg,
   `unbroken` wenn ohne Absetzen. Pace immer mit Einheit, in Fließtext als `4:22 min/km Pace`.
5. Ergometer: `Ski Erg 2026-09-20: 5000 m in 21:37.5, Ø 2:09.8 /500 m, 160 W, 39 spm` als erste Zeile, dann
   HR-Zeile, RPE-Zeile, dann Intervallblock (`5x1000 m` / `Pace: … (Ø …)` / `HR avg: … (Ø …, max …)`), jeweils
   mit Leerzeile. `scripts/concept2_export.py` `coach_text()` erzeugt genau das.
6. **Distanz-Intervalle (z. B. 800 m) als Gesamtsekunden je Wiederholung** mit Apostroph, nicht nur als Pace:
   `800 m: 197' / 198' / 202' / 208' / 200' / 206'` (240' = 4 min), dahinter in Klammern die Ø-Pace
   (`Ø 4:12 min/km`). Wunsch des Nutzers vom 22.09.2026. Zeit-Intervalle (3 min) bleiben bei Pace.
7. Nur Messwerte und Angaben des Nutzers, keine Interpretation außer in der Zeile „Anmerkung“.
