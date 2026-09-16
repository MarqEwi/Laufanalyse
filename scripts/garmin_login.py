# /// script
# requires-python = ">=3.11"
# dependencies = ["garminconnect>=0.3.2"]
# ///
"""Einmalige Anmeldung an Garmin Connect (inkl. MFA) und Smoke-Test.

Aufruf:   uv run scripts/garmin_login.py [--force] [--no-test]

- Fragt fehlende Zugangsdaten interaktiv ab (Passwort ohne Echo), speichert sie NICHT.
- Legt den Token-Cache unter $GARMINTOKENS bzw. ~/.garminconnect ab.
- Testet danach: letzte 5 Aktivitäten + Kennzahlen des letzten Laufs (Schritt 1.5).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import garmin_auth  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="vorhandene Tokens verwerfen und neu anmelden")
    ap.add_argument("--no-test", action="store_true", help="nach der Anmeldung keinen Aktivitäten-Test ausführen")
    args = ap.parse_args()

    print(f"Token-Ordner: {garmin_auth.token_dir()}")
    try:
        client = garmin_auth.connect(interactive=True, force_login=args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"\nAnmeldung fehlgeschlagen: {exc}", file=sys.stderr)
        print(
            "Hinweise: Passwort prüfen, bei '429' einige Minuten warten, "
            "bei MFA den aktuellen Code eingeben.",
            file=sys.stderr,
        )
        return 1

    print(f"Angemeldet als: {garmin_auth.whoami(client)}")
    print(f"Tokens gespeichert in: {garmin_auth.token_dir() / 'garmin_tokens.json'}")

    if args.no_test:
        return 0

    # Smoke-Test: nutzt die Tabellen-Funktionen aus garmin_export.py
    import garmin_export  # noqa: E402

    print()
    garmin_export.print_activity_list(client, limit=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
