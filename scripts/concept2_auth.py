"""Anmeldung am Concept2 Logbook (OAuth2) für die Skripte und den MCP-Server in diesem Ordner.

Das Logbook (log.concept2.com) bekommt die Einheiten von ErgData/PM5 und stellt sie über eine
offizielle REST-API bereit. Zugang: eigene App unter https://log.concept2.com/developers registrieren
(Client-ID + Client-Secret, Redirect-URI wie unten), dann einmal per Browser autorisieren
(scripts/concept2_login.py). Danach läuft alles über Access-/Refresh-Token ohne Browser.

Zugangsdaten kommen ausschließlich aus Umgebungsvariablen oder der Token-Datei außerhalb des Repos:

    CONCEPT2_CLIENT_ID       Client-ID der registrierten App
    CONCEPT2_CLIENT_SECRET   Client-Secret (nur für Autorisierung und Token-Erneuerung)
    CONCEPT2_REDIRECT_URI    Redirect-URI wie bei Concept2 eingetragen (Standard http://localhost:8765/callback)
    CONCEPT2_TOKENS          Ordner für den Token-Cache (Standard ~/.concept2)
    CONCEPT2_TOKENS_B64      Token-Datei als base64 für Umgebungen ohne dauerhaften Ordner (Cloud-Sessions).
                             Erzeugen mit: uv run scripts/concept2_login.py --show-token
    CONCEPT2_TOKENS_JSON     dasselbe als reines JSON
    CONCEPT2_DEV=1           Entwicklungs-Logbook log-dev.concept2.com statt log.concept2.com

Token-Datei <CONCEPT2_TOKENS>/concept2_tokens.json:
    {access_token, refresh_token, expires_at (Unix-Sekunden), scope, client_id, client_secret}
Client-ID/-Secret werden mit in der Datei abgelegt, damit eine Cloud-Session nur CONCEPT2_TOKENS_B64 braucht.
Umgebungsvariablen haben Vorrang vor den Werten in der Datei.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

DEFAULT_TOKEN_DIR = Path.home() / ".concept2"
TOKEN_FILE_NAME = "concept2_tokens.json"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_SCOPE = "user:read,results:read"
ACCEPT_HEADER = "application/vnd.c2logbook.v1+json"
USER_AGENT = "laufanalyse-concept2/1.0"
REFRESH_MARGIN_S = 120  # Access-Token so früh erneuern


class Concept2AuthError(RuntimeError):
    """Anmeldung nicht möglich (fehlende Zugangsdaten/Tokens)."""


class Concept2ApiError(RuntimeError):
    """Fehler der Logbook-API (HTTP-Status ungleich 2xx)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------------------
# URLs und Token-Datei
# ----------------------------------------------------------------------------


def host() -> str:
    return "log-dev.concept2.com" if os.environ.get("CONCEPT2_DEV", "").strip() in ("1", "true", "yes") else "log.concept2.com"


def api_base() -> str:
    return f"https://{host()}/api"


def authorize_endpoint() -> str:
    return f"https://{host()}/oauth/authorize"


def token_endpoint() -> str:
    return f"https://{host()}/oauth/access_token"


def token_dir() -> Path:
    raw = os.environ.get("CONCEPT2_TOKENS")
    return Path(raw).expanduser() if raw else DEFAULT_TOKEN_DIR


def token_file() -> Path:
    return token_dir() / TOKEN_FILE_NAME


def tokens_present() -> bool:
    return token_file().is_file()


def redirect_uri() -> str:
    return os.environ.get("CONCEPT2_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI


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
        if isinstance(data, dict) and (data.get("refresh_token") or data.get("access_token")):
            return data
    return None


def materialize_tokens_from_env() -> bool:
    """Schreibt CONCEPT2_TOKENS_B64/CONCEPT2_TOKENS_JSON in die Token-Datei, falls diese fehlt. True = geschrieben."""
    if tokens_present():
        return False
    blob = os.environ.get("CONCEPT2_TOKENS_B64") or os.environ.get("CONCEPT2_TOKENS_JSON") or ""
    data = _decode_blob(blob)
    if not data:
        return False
    save_tokens(data)
    return True


def load_tokens() -> dict[str, Any] | None:
    materialize_tokens_from_env()
    f = token_file()
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_tokens(data: dict[str, Any]) -> None:
    token_dir().mkdir(parents=True, exist_ok=True)
    token_file().write_text(json.dumps(data), encoding="utf-8")
    try:
        token_file().chmod(0o600)
    except OSError:
        pass


def clear_tokens() -> None:
    f = token_file()
    if f.exists():
        f.unlink()


def token_blob_b64() -> str:
    """Aktuelle Token-Datei als base64 (zum Übertragen in eine andere Umgebung)."""
    return base64.b64encode(token_file().read_bytes()).decode("ascii")


# ----------------------------------------------------------------------------
# Client-Zugangsdaten
# ----------------------------------------------------------------------------


def client_credentials(tokens: dict[str, Any] | None = None) -> tuple[str, str]:
    """Client-ID und -Secret: Umgebungsvariablen vor Token-Datei."""
    tokens = tokens if tokens is not None else (load_tokens() or {})
    cid = os.environ.get("CONCEPT2_CLIENT_ID", "").strip() or str(tokens.get("client_id") or "")
    sec = os.environ.get("CONCEPT2_CLIENT_SECRET", "").strip() or str(tokens.get("client_secret") or "")
    if not cid or not sec:
        raise Concept2AuthError(
            "CONCEPT2_CLIENT_ID und CONCEPT2_CLIENT_SECRET fehlen. App unter "
            "https://log.concept2.com/developers registrieren und die Werte als Umgebungsvariablen setzen."
        )
    return cid, sec


# ----------------------------------------------------------------------------
# OAuth2: Autorisierung, Code-Tausch, Erneuerung
# ----------------------------------------------------------------------------


def new_state() -> str:
    return secrets.token_urlsafe(16)


def authorize_url(state: str, scope: str = DEFAULT_SCOPE) -> str:
    cid, _ = client_credentials()
    q = {
        "client_id": cid,
        "scope": scope,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{authorize_endpoint()}?{urlencode(q)}"


def _post_token(form: dict[str, str]) -> dict[str, Any]:
    import requests  # Import erst hier, damit --help ohne Abhängigkeit läuft

    try:
        r = requests.post(
            token_endpoint(),
            data=form,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise Concept2AuthError(f"Token-Endpunkt nicht erreichbar ({token_endpoint()}): {exc}") from exc
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or not isinstance(data, dict) or not data.get("access_token"):
        detail = data.get("error_description") or data.get("message") or data.get("error") or r.text[:200] if isinstance(data, dict) else r.text[:200]
        raise Concept2AuthError(f"Token-Anfrage abgelehnt (HTTP {r.status_code}): {detail}")
    return data


def _store_token_response(data: dict[str, Any], cid: str, sec: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    expires_in = data.get("expires_in")
    try:
        expires_at = time.time() + float(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_at = None
    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or (previous or {}).get("refresh_token"),
        "expires_at": expires_at,
        "scope": data.get("scope") or (previous or {}).get("scope") or DEFAULT_SCOPE,
        "token_type": data.get("token_type", "Bearer"),
        "client_id": cid,
        "client_secret": sec,
        "host": host(),
        "saved_at": time.time(),
    }
    save_tokens(tokens)
    return tokens


def exchange_code(code: str) -> dict[str, Any]:
    """Autorisierungscode gegen Tokens tauschen und speichern."""
    cid, sec = client_credentials()
    data = _post_token({
        "client_id": cid,
        "client_secret": sec,
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": redirect_uri(),
    })
    return _store_token_response(data, cid, sec)


def refresh_tokens(tokens: dict[str, Any] | None = None) -> dict[str, Any]:
    """Access-Token über das Refresh-Token erneuern und speichern."""
    tokens = tokens if tokens is not None else load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise Concept2AuthError("Kein Refresh-Token vorhanden – `uv run scripts/concept2_login.py` ausführen.")
    cid, sec = client_credentials(tokens)
    data = _post_token({
        "client_id": cid,
        "client_secret": sec,
        "grant_type": "refresh_token",
        "refresh_token": str(tokens["refresh_token"]),
        "scope": str(tokens.get("scope") or DEFAULT_SCOPE),
    })
    return _store_token_response(data, cid, sec, previous=tokens)


def access_token(force_refresh: bool = False) -> str:
    """Gültiges Access-Token (erneuert automatisch, wenn abgelaufen oder kurz davor)."""
    tokens = load_tokens()
    if not tokens:
        raise Concept2AuthError(
            "Keine Concept2-Tokens. Auf dem PC `uv run scripts/concept2_login.py` ausführen; in einer "
            "Cloud-Session CONCEPT2_TOKENS_B64 setzen (aus `concept2_login.py --show-token`)."
        )
    exp = tokens.get("expires_at")
    stale = force_refresh or not tokens.get("access_token") or (isinstance(exp, (int, float)) and exp - REFRESH_MARGIN_S <= time.time())
    if stale:
        tokens = refresh_tokens(tokens)
    return str(tokens["access_token"])


# ----------------------------------------------------------------------------
# API-Client
# ----------------------------------------------------------------------------


class Concept2Client:
    """Kleiner Client für die Logbook-API: GET mit Bearer-Token, erneuert das Token bei 401 einmal."""

    def __init__(self, timeout_s: float = 30.0):
        import requests

        self._s = requests.Session()
        self._s.headers.update({"Accept": ACCEPT_HEADER, "User-Agent": USER_AGENT})
        self.timeout_s = timeout_s

    def get(self, path: str, params: dict[str, Any] | None = None, *, raw: bool = False) -> Any:
        url = path if path.startswith("http") else f"{api_base()}/{path.lstrip('/')}"
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in (1, 2):
            tok = access_token(force_refresh=(attempt == 2))
            r = self._s.get(url, params=params, headers={"Authorization": f"Bearer {tok}"}, timeout=self.timeout_s)
            if r.status_code == 401 and attempt == 1:
                continue
            break
        if r.status_code == 429:
            raise Concept2ApiError("Concept2-API: zu viele Anfragen (429) – einige Minuten warten.", 429)
        if r.status_code >= 400:
            try:
                d = r.json()
                detail = d.get("error_description") or d.get("message") or d.get("error") or r.text[:200]
            except ValueError:
                detail = r.text[:200]
            hint = " (Scope fehlt? user:read,results:read)" if r.status_code == 403 else ""
            raise Concept2ApiError(f"Concept2-API-Fehler HTTP {r.status_code} bei {path}: {detail}{hint}", r.status_code)
        if raw:
            return r.content
        try:
            return r.json()
        except ValueError as exc:
            raise Concept2ApiError(f"Concept2-API: keine JSON-Antwort bei {path}") from exc

    # --- Endpunkte ---------------------------------------------------------

    def me(self) -> dict[str, Any]:
        return self.get("users/me").get("data") or {}

    def results(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        type_: str | None = None,
        updated_after: str | None = None,
        page: int | None = None,
        number: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        d = self.get("users/me/results", {
            "from": from_date, "to": to_date, "type": type_, "updated_after": updated_after,
            "page": page, "number": number,
        })
        meta = (d.get("meta") or {}).get("pagination") or {}
        return list(d.get("data") or []), meta

    def result(self, result_id: int, include: str | None = None) -> dict[str, Any]:
        return self.get(f"users/me/results/{result_id}", {"include": include}).get("data") or {}

    def strokes(self, result_id: int) -> list[dict[str, Any]]:
        d = self.get(f"users/me/results/{result_id}/strokes")
        data = d.get("data")
        return list(data) if isinstance(data, list) else []

    def export(self, result_id: int, kind: str = "csv") -> bytes:
        if kind not in ("csv", "fit", "tcx"):
            raise ValueError("kind muss csv, fit oder tcx sein")
        return self.get(f"users/me/results/{result_id}/export/{kind}", raw=True)


def connect() -> Concept2Client:
    """Client mit gültigem Token (löst Concept2AuthError aus, wenn keine Tokens vorhanden sind)."""
    access_token()
    return Concept2Client()


def whoami(client: Concept2Client) -> str:
    me = client.me()
    name = " ".join(x for x in (me.get("first_name"), me.get("last_name")) if x) or me.get("username")
    return name or "(Name unbekannt)"
