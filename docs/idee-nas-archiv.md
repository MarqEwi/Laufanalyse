# Idee: Trainingsarchiv auf dem NAS (offen, Stand 20.09.2026)

Wunsch des Nutzers: Jeder Trainingstag sauber an einem Ort dokumentiert, mit PM5-Fotos, Garmin- und
Concept2-Daten und einer Auswertung als Textdatei; danach können die Fotos vom Handy gelöscht werden.
Der NAS steht im Heimnetz und ist nur vom PC erreichbar, nicht aus Cloud-Sessions.

## Vorgeschlagene Ablage

```
Training/<Jahr>/<YYYY-MM-DD>/
  fotos/          PM5-Fotos, Coach-Screenshots
  garmin/         Export wie data/garmin/<datum>_<id>/
  concept2/       Logbook- und Foto-Einheiten wie data/concept2/…
  auswertung.md   Zusammenführung des Tages (Beispiel: data/concept2/2026-09-20_long_distanz_kombiniert.md)
  coach.txt       Textbaustein mit RPE, wie an den Coach gesendet
```

## Umsetzung

1. PC: `LAUFANALYSE_DATA_DIR` und `CONCEPT2_DATA_DIR` auf den NAS zeigen (Setup-Skripte anpassen).
2. Fotos: Foto-Backup der NAS-App vom Handy in einen Eingangsordner; Skill sortiert nach Aufnahmedatum.
3. Neuer Skill `/archiv <Datum>`: Garmin + Logbook laden, Fotos transkribieren (`concept2_analyze_manual`),
   Tagesauswertung schreiben, Ordner anlegen, Eingang leeren.
4. Cloud-Sessions optional über ein privates Git-Repo „training-archive“, das der NAS nachts zieht.

## Offene Fragen an den Nutzer

- NAS-Modell (Synology/QNAP/…) und Weg der Fotos vom Handy.
- Ist der NAS am PC als Laufwerk eingebunden (Pfad)?
- Sollen Cloud-Sessions archivieren (privates Repo) oder reicht der PC?
