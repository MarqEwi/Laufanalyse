"""Gemeinsame Anmeldung an Garmin Connect für die Skripte in diesem Ordner.

Zugangsdaten kommen ausschließlich aus Umgebungsvariablen (nie aus Dateien im Repo):

    GARMIN_EMAIL     E-Mail des Garmin-Connect-Kontos
    GARMIN_PASSWORD  Passwort (nur für die erste Anmeldung bzw. nach Token-Ablauf nötig)
    GARMINTOKENS     Ordner für den Token-Cache (Standard: ~/.garminconnect)

Nach der ersten Anmeldung (inkl. MFA) liegen die Tokens in <GARMINTOKENS>/garmin_tokens.json.
Solange sie gültig sind, wird weder Passwort noch MFA-Code gebraucht.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

DEFAULT_TOKEN_DIR = Path.home() / ".garminconnect"


def token_dir() -> Path:
    raw = os.environ.get("GARMINTOKENS")
    return Path(raw).expanduser() if raw else DEFAULT_TOKEN_DIR


def tokens_present() -> bool:
    return (token_dir() / "garmin_tokens.json").is_file()


def _prompt_mfa() -> str:
    print("Garmin verlangt eine Zwei-Faktor-Bestätigung (MFA).", file=sys.stderr)
    return input("MFA-Code (aus E-Mail/SMS/Authenticator): ").strip()


def connect(*, interactive: bool = True, force_login: bool = False):
    """Liefert einen angemeldeten garminconnect.Garmin-Client.

    - Sind gültige Tokens vorhanden, wird ohne Passwort angemeldet.
    - Sonst werden GARMIN_EMAIL/GARMIN_PASSWORD benutzt; fehlen sie und ist
      ``interactive`` gesetzt, wird nachgefragt (Passwort ohne Echo).
    - Bei MFA wird der Code interaktiv abgefragt (nur mit ``interactive``).
    """
    from garminconnect import Garmin  # Import erst hier, damit --help ohne Abhängigkeit läuft

    tdir = token_dir()
    tdir.mkdir(parents=True, exist_ok=True)
    token_file = tdir / "garmin_tokens.json"
    if force_login and token_file.exists():
        token_file.unlink()

    email = os.environ.get("GARMIN_EMAIL", "").strip()
    password = os.environ.get("GARMIN_PASSWORD", "")

    if not token_file.exists():
        if not email and interactive:
            email = input("Garmin-E-Mail: ").strip()
        if not password and interactive:
            password = getpass.getpass("Garmin-Passwort (keine Anzeige): ")
        if not email or not password:
            raise SystemExit(
                "Keine gültigen Tokens und keine Zugangsdaten. "
                "Setze GARMIN_EMAIL und GARMIN_PASSWORD oder führe scripts/garmin_login.py aus."
            )

    client = Garmin(
        email or None,
        password or None,
        prompt_mfa=_prompt_mfa if interactive else None,
    )
    # login(tokenstore): lädt vorhandene Tokens, sonst Passwort-Login und Token-Ablage
    client.login(str(tdir))
    return client


def whoami(client) -> str:
    name = getattr(client, "full_name", None) or getattr(client, "display_name", None)
    return name or "(Name unbekannt)"
