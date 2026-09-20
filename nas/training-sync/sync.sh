#!/bin/sh
# Holt das Archiv-Repo in einer Schleife (alle $INTERVAL Sekunden) nach /archiv.
# Läuft im Container training-sync (alpine/git). Deploy-Key: /keys/training-archiv_deploy (nur lesend).
set -u
REPO="${ARCHIV_REPO:?ARCHIV_REPO fehlt}"
BRANCH="${ARCHIV_BRANCH:-main}"
INTERVAL="${INTERVAL:-600}"
KEY=/keys/training-archiv_deploy

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
export GIT_SSH_COMMAND="ssh -i /tmp/.ssh/key -o UserKnownHostsFile=/tmp/.ssh/known_hosts -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"

while true; do
  if [ -d /archiv/.git ]; then
    if git -C /archiv pull --ff-only -q origin "$BRANCH" 2>/tmp/err; then
      echo "$(date '+%F %T') pull ok: $(git -C /archiv log -1 --format='%h %s')"
    else
      echo "$(date '+%F %T') pull FEHLER: $(cat /tmp/err)"
    fi
  else
    if [ -n "$(ls -A /archiv 2>/dev/null)" ]; then
      echo "$(date '+%F %T') /archiv ist nicht leer und kein Git-Repo – nichts getan (Ordner leeren oder Repo dorthin klonen)"
    elif git clone -q --branch "$BRANCH" "$REPO" /archiv 2>/tmp/err; then
      echo "$(date '+%F %T') geklont: $REPO"
    else
      echo "$(date '+%F %T') clone FEHLER: $(cat /tmp/err)"
    fi
  fi
  sleep "$INTERVAL"
done
