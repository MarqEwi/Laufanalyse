#!/bin/bash
# SessionStart-Hook: bereitet Cloud-Sessions (Claude Code im Browser / in der Claude-App) vor.
# - stellt uv bereit, installiert die Python-Abhängigkeiten des Garmin-MCP-Servers und der Skripte
# - legt den Token-Cache aus GARMIN_TOKENS_B64 an (Umgebungsvariable der Cloud-Umgebung)
# Lokal (PC) macht der Hook nichts.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"

# uv sicherstellen (im Cloud-Container normalerweise vorhanden)
if ! command -v uv >/dev/null 2>&1; then
  echo "uv fehlt – installiere nach ~/.local/bin ..."
  curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:$PATH"
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
  fi
fi

# Datenordner der Laufanalyse (falls nicht über die Umgebung gesetzt)
if [ -z "${LAUFANALYSE_DATA_DIR:-}" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export LAUFANALYSE_DATA_DIR=\"$ROOT/data/garmin\"" >> "$CLAUDE_ENV_FILE"
fi

# Abhängigkeiten vorinstallieren (wird im Container-Cache gehalten)
if ! uv run scripts/garmin_mcp_server.py --warmup; then
  echo "Warnung: Abhängigkeiten konnten nicht vorinstalliert werden."
  if [ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 https://pypi.org/simple/ 2>/dev/null)" = "403" ]; then
    echo "Ursache: pypi.org ist in der Netzwerk-Policy der Cloud-Umgebung nicht freigegeben. Bitte pypi.org und files.pythonhosted.org zu den erlaubten Domains hinzufügen."
  fi
fi
uv run scripts/garmin_export.py --help >/dev/null 2>&1 || true

# Tokens aus der Umgebungsvariable in den Token-Ordner schreiben
uv run --no-project python - <<'PY' || true
import sys
sys.path.insert(0, "scripts")
import garmin_auth
if garmin_auth.materialize_tokens_from_env():
    print(f"Garmin-Tokens aus GARMIN_TOKENS_B64 nach {garmin_auth.token_file()} geschrieben.")
elif garmin_auth.tokens_present():
    print("Garmin-Tokens vorhanden.")
else:
    print("Hinweis: keine Garmin-Tokens (GARMIN_TOKENS_B64 in der Cloud-Umgebung setzen).")
import os
os.environ.pop("CONCEPT2_DEV", None)  # Hook schreibt immer die Live-Tokens
import concept2_auth
if concept2_auth.materialize_tokens_from_env():
    print(f"Concept2-Tokens aus CONCEPT2_TOKENS_B64 nach {concept2_auth.token_file()} geschrieben.")
elif concept2_auth.tokens_present():
    print("Concept2-Tokens vorhanden.")
else:
    print("Hinweis: keine Concept2-Tokens (optional: CONCEPT2_TOKENS_B64 in der Cloud-Umgebung setzen).")
PY

# Datenordner für Concept2-Einheiten
if [ -z "${CONCEPT2_DATA_DIR:-}" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export CONCEPT2_DATA_DIR=\"$ROOT/data/concept2\"" >> "$CLAUDE_ENV_FILE"
fi

echo "Garmin-MCP: Vorbereitung abgeschlossen."
