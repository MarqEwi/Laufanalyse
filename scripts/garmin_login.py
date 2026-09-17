# /// script
# requires-python = ">=3.11"
# dependencies = ["garminconnect>=0.3.2"]
# ///
"""Einmalige Anmeldung an Garmin Connect (inkl. MFA) und Smoke-Test.

PC (Terminal):        uv run scripts/garmin_login.py [--force] [--no-test]
Cloud-Session:        uv run scripts/garmin_login.py --mfa-file /tmp/mfa.txt   (im Hintergrund starten,
                      dann den MFA-Code in die Datei schreiben:  echo 123456 > /tmp/mfa.txt)
Tokens exportieren:   uv run scripts/garmin_login.py --show-token
                      -> Wert für die Umgebungsvariable GARMIN_TOKENS_B64 (Cloud-Umgebung von Claude Code)

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
    ap.add_argument("--mfa-file", type=Path, help="MFA-Code aus dieser Datei lesen statt vom Terminal (Cloud-Session)")
    ap.add_argument("--mfa-timeout", type=int, default=300, help="Sekunden auf den MFA-Code warten (Standard 300)")
    ap.add_argument("--show-token", action="store_true", help="Token-Datei als base64 ausgeben (für GARMIN_TOKENS_B64)")
    args = ap.parse_args()

    if args.show_token:
        if not garmin_auth.tokens_present() and not garmin_auth.materialize_tokens_from_env():
            print("Keine Token-Datei vorhanden – erst anmelden.", file=sys.stderr)
            return 1
        print(garmin_auth.token_blob_b64())
        return 0

    print(f"Token-Ordner: {garmin_auth.token_dir()}")
    try:
        client = garmin_auth.connect(
            interactive=args.mfa_file is None,
            force_login=args.force,
            mfa_file=args.mfa_file,
            mfa_timeout_s=args.mfa_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\nAnmeldung fehlgeschlagen: {exc}", file=sys.stderr)
        print(
            "Hinweise: Passwort prüfen, bei '429' einige Minuten warten, "
            "bei MFA den aktuellen Code eingeben.",
            file=sys.stderr,
        )
        return 1

    print(f"Angemeldet als: {garmin_auth.whoami(client)}")
    print(f"Tokens gespeichert in: {garmin_auth.token_file()}")
    print("Für Cloud-Sessions (Smartphone): `uv run scripts/garmin_login.py --show-token` → GARMIN_TOKENS_B64")

    if args.no_test:
        return 0

    import garmin_export  # noqa: E402

    print()
    garmin_export.print_activity_list(client, limit=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
