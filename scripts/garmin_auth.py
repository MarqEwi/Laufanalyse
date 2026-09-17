"""Gemeinsame Anmeldung an Garmin Connect für die Skripte und den MCP-Server in diesem Ordner.

Zugangsdaten kommen ausschließlich aus Umgebungsvariablen (nie aus Dateien im Repo):

    GARMIN_EMAIL        E-Mail des Garmin-Connect-Kontos
    GARMIN_PASSWORD     Passwort (nur für die erste Anmeldung bzw. nach Token-Ablauf nötig)
    GARMINTOKENS        Ordner für den Token-Cache (Standard: ~/.garminconnect)
    GARMIN_TOKENS_B64   Token-Inhalt (base64) für Umgebungen ohne dauerhaften Ordner, z. B. Claude-Code-
                        Cloud-Sessions vom Smartphone. Erzeugen mit: uv run scripts/garmin_login.py --show-token
    GARMIN_TOKENS_JSON  dasselbe als reines JSON

Nach der ersten Anmeldung (inkl. MFA) liegen die Tokens in <GARMINTOKENS>/garmin_tokens.json.
Solange sie gültig sind, wird weder Passwort noch MFA-Code gebraucht; das Access-Token wird
automatisch über das Refresh-Token erneuert.
"""

from __future__ import annotations

import base64
import binascii
import getpass
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_TOKEN_DIR = Path.home() / ".garminconnect"
TOKEN_FILE_NAME = "garmin_tokens.json"


class GarminAuthError(RuntimeError):
    """Anmeldung nicht möglich (fehlende Zugangsdaten/Tokens)."""


def token_dir() -> Path:
    raw = os.environ.get("GARMINTOKENS")
    return Path(raw).expanduser() if raw else DEFAULT_TOKEN_DIR


def token_file() -> Path:
    return token_dir() / TOKEN_FILE_NAME


def tokens_present() -> bool:
    return token_file().is_file()


def _decode_blob(blob: str) -> dict | None:
    blob = blob.strip()
    if not blob:
        return None
    candidates = [blob]
    try:
        candidates.append(base64.b64decode(blob, validate=True).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        pass
    for c in reversed(candidates):  # base64-dekodiert zuerst probieren
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("di_token"):
            return data
    return None


def materialize_tokens_from_env() -> bool:
    """Schreibt GARMIN_TOKENS_B64/GARMIN_TOKENS_JSON in die Token-Datei, falls diese fehlt. True = geschrieben."""
    if tokens_present():
        return False
    blob = os.environ.get("GARMIN_TOKENS_B64") or os.environ.get("GARMIN_TOKENS_JSON") or ""
    data = _decode_blob(blob)
    if not data:
        return False
    token_dir().mkdir(parents=True, exist_ok=True)
    token_file().write_text(json.dumps(data), encoding="utf-8")
    try:
        token_file().chmod(0o600)
    except OSError:
        pass
    return True


def token_blob_b64() -> str:
    """Aktuelle Token-Datei als base64 (zum Übertragen in eine andere Umgebung)."""
    return base64.b64encode(token_file().read_bytes()).decode("ascii")


def _prompt_mfa_stdin() -> str:
    print("Garmin verlangt eine Zwei-Faktor-Bestätigung (MFA).", file=sys.stderr)
    return input("MFA-Code (aus E-Mail/SMS/Authenticator): ").strip()


def _prompt_mfa_file(path: Path, timeout_s: int):
    def _wait() -> str:
        print(
            f"Garmin verlangt einen MFA-Code. Schreibe ihn in die Datei {path} "
            f"(z. B.  echo 123456 > {path}). Warte bis zu {timeout_s} s ...",
            file=sys.stderr,
            flush=True,
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if path.is_file():
                code = path.read_text(encoding="utf-8").strip()
                if code:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    return code
            time.sleep(2)
        raise TimeoutError(f"Kein MFA-Code in {path} innerhalb von {timeout_s} s.")

    return _wait


def connect(*, interactive: bool = True, force_login: bool = False, mfa_file: Path | None = None, mfa_timeout_s: int = 300):
    """Liefert einen angemeldeten garminconnect.Garmin-Client.

    - Sind gültige Tokens vorhanden (Datei oder GARMIN_TOKENS_B64/_JSON), wird ohne Passwort angemeldet.
    - Sonst werden GARMIN_EMAIL/GARMIN_PASSWORD benutzt; fehlen sie und ist ``interactive`` gesetzt,
      wird nachgefragt (Passwort ohne Echo).
    - MFA: Code per Terminal (``interactive``) oder per Datei (``mfa_file``, für Cloud-Sessions).
    """
    from garminconnect import Garmin  # Import erst hier, damit --help ohne Abhängigkeit läuft

    tdir = token_dir()
    tdir.mkdir(parents=True, exist_ok=True)
    tfile = token_file()
    if force_login and tfile.exists():
        tfile.unlink()
    if not force_login:
        materialize_tokens_from_env()

    email = os.environ.get("GARMIN_EMAIL", "").strip()
    password = os.environ.get("GARMIN_PASSWORD", "")

    if not tfile.exists():
        if not email and interactive:
            email = input("Garmin-E-Mail: ").strip()
        if not password and interactive:
            password = getpass.getpass("Garmin-Passwort (keine Anzeige): ")
        if not email or not password:
            raise GarminAuthError(
                "Keine gültigen Tokens und keine Zugangsdaten. "
                "Setze GARMIN_EMAIL und GARMIN_PASSWORD (oder GARMIN_TOKENS_B64) "
                "oder führe scripts/garmin_login.py aus."
            )

    if mfa_file is not None:
        prompt = _prompt_mfa_file(mfa_file, mfa_timeout_s)
    elif interactive:
        prompt = _prompt_mfa_stdin
    else:
        prompt = None

    client = Garmin(email or None, password or None, prompt_mfa=prompt)
    # login(tokenstore): lädt vorhandene Tokens, sonst Passwort-Login und Token-Ablage im Ordner
    client.login(str(tdir))
    return client


def whoami(client) -> str:
    name = getattr(client, "full_name", None) or getattr(client, "display_name", None)
    return name or "(Name unbekannt)"
