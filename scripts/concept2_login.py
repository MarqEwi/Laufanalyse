# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""Einmalige Autorisierung beim Concept2 Logbook (OAuth2) und Smoke-Test.

Voraussetzung: App unter https://log.concept2.com/developers/keys registriert, Redirect-URI dort
= http://localhost:8765/callback (oder CONCEPT2_REDIRECT_URI), und CONCEPT2_CLIENT_ID /
CONCEPT2_CLIENT_SECRET als Umgebungsvariablen gesetzt.

PC (Terminal):        uv run scripts/concept2_login.py
                      -> öffnet die Autorisierungsseite im Browser, fängt den Code auf localhost:8765 ab
Ohne Browser/Cloud:   uv run scripts/concept2_login.py --manual
                      -> zeigt die URL; nach dem Bestätigen die Adresszeile der Zielseite (…?code=…) einfügen
Tokens exportieren:   uv run scripts/concept2_login.py --show-token
                      -> Wert für CONCEPT2_TOKENS_B64 (Cloud-Umgebung von Claude Code)
Token erneuern:       uv run scripts/concept2_login.py --refresh

- Speichert Access-/Refresh-Token (und Client-ID/-Secret) unter $CONCEPT2_TOKENS bzw. ~/.concept2.
- Testet danach: Profilname und die letzten 5 Einheiten.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import concept2_auth as c2  # noqa: E402


def _catch_code_locally(expected_state: str, timeout_s: int) -> str:
    """Kleiner HTTP-Server auf der Redirect-URI, der den Autorisierungscode entgegennimmt."""
    u = urlparse(c2.redirect_uri())
    if u.hostname not in ("localhost", "127.0.0.1"):
        raise c2.Concept2AuthError(f"Redirect-URI {c2.redirect_uri()} zeigt nicht auf localhost – bitte --manual verwenden.")
    port = u.port or 80
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            code, state, err = q.get("code", [""])[0], q.get("state", [""])[0], q.get("error", [""])[0]
            if err:
                result["error"] = err
            elif state != expected_state:
                result["error"] = "state stimmt nicht überein"
            else:
                result["code"] = code
            body = "Concept2-Autorisierung erhalten. Dieses Fenster kann geschlossen werden." if "code" in result else f"Fehler: {result.get('error')}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            done.set()

        def log_message(self, *args):  # ruhig bleiben
            pass

    srv = HTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        if not done.wait(timeout_s):
            raise TimeoutError(f"Keine Antwort auf {c2.redirect_uri()} innerhalb von {timeout_s} s.")
    finally:
        srv.shutdown()
    if "code" not in result:
        raise c2.Concept2AuthError(f"Autorisierung fehlgeschlagen: {result.get('error')}")
    return result["code"]


def smoke_test() -> None:
    client = c2.connect()
    print(f"Angemeldet als: {c2.whoami(client)}")
    results, _ = client.results(number=5)
    if not results:
        print("Keine Einheiten im Logbook.")
        return
    print("Letzte Einheiten:")
    for r in results:
        dist = r.get("distance") or 0
        print(f"  {r.get('date','')[:16]}  {str(r.get('type','')):<7} {dist:>6} m  {r.get('time_formatted','')}  ID {r.get('id')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manual", action="store_true", help="URL anzeigen und Code/Redirect-URL einfügen (ohne lokalen Server)")
    ap.add_argument("--force", action="store_true", help="vorhandene Tokens verwerfen und neu autorisieren")
    ap.add_argument("--refresh", action="store_true", help="Access-Token über das Refresh-Token erneuern")
    ap.add_argument("--no-test", action="store_true", help="nach der Anmeldung keinen Test ausführen")
    ap.add_argument("--timeout", type=int, default=300, help="Sekunden auf die Browser-Bestätigung warten (Standard 300)")
    ap.add_argument("--show-token", action="store_true", help="Token-Datei als base64 ausgeben (für CONCEPT2_TOKENS_B64)")
    args = ap.parse_args()

    try:
        if args.show_token:
            if not c2.tokens_present() and not c2.materialize_tokens_from_env():
                print("Keine Token-Datei vorhanden – erst autorisieren.", file=sys.stderr)
                return 2
            print(c2.token_blob_b64())
            return 0

        if args.refresh:
            c2.refresh_tokens()
            print(f"Token erneuert und gespeichert in {c2.token_file()}.")
            if not args.no_test:
                smoke_test()
            return 0

        if args.force:
            c2.clear_tokens()

        if c2.load_tokens() and not args.force:
            print(f"Tokens vorhanden in {c2.token_file()} (mit --force neu autorisieren).")
        else:
            state = c2.new_state()
            url = c2.authorize_url(state)
            print("Autorisierung beim Concept2 Logbook.\nURL:\n  " + url)
            if args.manual:
                pasted = input("\nNach dem Bestätigen die Adresszeile der Zielseite (…?code=…&state=…) oder nur den Code einfügen: ")
                code = c2.parse_code(pasted, state)
            else:
                print(f"\nBrowser öffnet sich; warte auf {c2.redirect_uri()} …")
                webbrowser.open(url)
                code = _catch_code_locally(state, args.timeout)
            c2.exchange_code(code)
            print(f"Tokens gespeichert in {c2.token_file()}.")

        if not args.no_test:
            smoke_test()
        print("\nFür Cloud-Sessions: `uv run scripts/concept2_login.py --show-token` → CONCEPT2_TOKENS_B64 setzen.")
        return 0
    except (c2.Concept2AuthError, c2.Concept2ApiError, TimeoutError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
