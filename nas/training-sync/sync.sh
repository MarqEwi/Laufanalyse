#!/bin/sh
# Holt das Archiv-Repo in einer Schleife (alle $INTERVAL Sekunden) nach /archiv.
# Läuft im Container training-sync (alpine/git + mosquitto-clients, siehe Dockerfile).
# Deploy-Key: /keys/training-archiv_deploy (nur lesend).
set -u
REPO="${ARCHIV_REPO:?ARCHIV_REPO fehlt}"
BRANCH="${ARCHIV_BRANCH:-main}"
INTERVAL="${INTERVAL:-600}"
KEY=/keys/training-archiv_deploy
# Netz-Zeitlimits: ohne sie kann eine hängende Verbindung zu GitHub die Schleife dauerhaft blockieren.
# Der Container liefe dann weiter als "Up", ohne noch etwas zu synchronisieren.
GIT_TIMEOUT="${GIT_TIMEOUT:-300}"
# MQTT-Statusmeldung (optional). MQTT_HOST leer lassen schaltet sie ab.
# Wegen des kaputten Hairpin-NAT der NAS ist der Broker aus dem Bridge-Netz NICHT über die LAN-IP
# erreichbar, wohl aber über das Docker-Gateway – dafür sorgt extra_hosts in der docker-compose.yml.
MQTT_HOST="${MQTT_HOST:-}"
MQTT_PORT="${MQTT_PORT:-1883}"
MQTT_TOPIC="${MQTT_TOPIC:-training/sync/status}"

export HOME=/tmp
mkdir -p /tmp/.ssh
chmod 700 /tmp/.ssh
# Deploy-Key mit sicheren Rechten in ein beschreibbares Verzeichnis kopieren (Volume ist read-only)
cp "$KEY" /tmp/.ssh/key && chmod 600 /tmp/.ssh/key
# GitHub-Hostkeys: bevorzugt die geprüfte Datei /keys/github_known_hosts (in der PC-Session anlegen:
#   ssh-keyscan -t ed25519 github.com > /volume1/Grundlagen/training/keys/github_known_hosts
# und den Fingerabdruck mit https://docs.github.com/en/authentication/keychain vergleichen);
# fehlt sie, wird beim Start einmal per ssh-keyscan geholt (Trust on first use).
if [ -s /keys/github_known_hosts ]; then
  cp /keys/github_known_hosts /tmp/.ssh/known_hosts
else
  ssh-keyscan -t ed25519 github.com > /tmp/.ssh/known_hosts 2>/dev/null || echo "$(date '+%F %T') WARNUNG: ssh-keyscan github.com fehlgeschlagen"
fi
export GIT_SSH_COMMAND="ssh -i /tmp/.ssh/key -o UserKnownHostsFile=/tmp/.ssh/known_hosts -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o ServerAliveInterval=20 -o ServerAliveCountMax=3"
# Falls /archiv einem anderen Nutzer gehört (z. B. nach Anlegen per SMB), git nicht mit "dubious ownership" abbrechen lassen
git config --global --add safe.directory /archiv

# Meldet den Zustand des letzten Durchlaufs an den MQTT-Broker (retained, damit Home Assistant
# nach einem Neustart sofort den letzten Stand sieht). Kein Topic unter brunner/* oder homeassistant/*.
# Macht einen Text für die JSON-Nutzlast unschädlich: Anführungszeichen (\042) und Backslashes (\134)
# werden entfernt, Zeilenumbrüche zu Leerzeichen. Für eine Statusmeldung reicht Entfernen statt
# Escapen – und es kommt ohne doppelte Backslashes aus, an denen BusyBox-sed hier gescheitert ist.
json_escape() {
  printf '%s' "$1" | tr -d '\042\134' | tr '\n\r\t' '   '
}
melde() {
  [ -n "$MQTT_HOST" ] || return 0
  status="$1"; meldung="$2"; commit="$3"
  nutzlast="{\"status\":\"$(json_escape "$status")\",\"zeitpunkt\":\"$(date '+%F %T')\",\"commit\":\"$(json_escape "$commit")\",\"meldung\":\"$(json_escape "$meldung")\"}"
  timeout 15 mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "$MQTT_TOPIC" -r -m "$nutzlast" 2>/dev/null \
    || echo "$(date '+%F %T') WARNUNG: MQTT-Meldung an $MQTT_HOST:$MQTT_PORT fehlgeschlagen"
}

# Führt ein git-Kommando mit Zeitlimit aus; Rückgabe 124 bedeutet Abbruch wegen Zeitüberschreitung.
lauf_git() {
  timeout "$GIT_TIMEOUT" "$@" 2>/tmp/err
  rc=$?
  if [ "$rc" -eq 124 ]; then
    echo "Zeitüberschreitung nach ${GIT_TIMEOUT}s" > /tmp/err
  fi
  return "$rc"
}

while true; do
  if [ -d /archiv/.git ]; then
    if lauf_git git -C /archiv pull --ff-only -q origin "$BRANCH"; then
      stand=$(git -C /archiv log -1 --format='%h %s')
      echo "$(date '+%F %T') pull ok: $stand"
      melde ok "$stand" "$(git -C /archiv log -1 --format='%h')"
    else
      fehler=$(cat /tmp/err)
      echo "$(date '+%F %T') pull FEHLER: $fehler"
      melde fehler "$fehler" "$(git -C /archiv log -1 --format='%h' 2>/dev/null || echo unbekannt)"
    fi
  else
    if [ -n "$(ls -A /archiv 2>/dev/null)" ]; then
      meldung="/archiv ist nicht leer und kein Git-Repo – nichts getan (Ordner leeren oder Repo dorthin klonen)"
      echo "$(date '+%F %T') $meldung"
      melde fehler "$meldung" ""
    elif lauf_git git clone -q --branch "$BRANCH" "$REPO" /archiv; then
      echo "$(date '+%F %T') geklont: $REPO"
      melde ok "geklont: $REPO" "$(git -C /archiv log -1 --format='%h' 2>/dev/null || echo unbekannt)"
    else
      fehler=$(cat /tmp/err)
      echo "$(date '+%F %T') clone FEHLER: $fehler"
      melde fehler "$fehler" ""
    fi
  fi
  sleep "$INTERVAL"
done
