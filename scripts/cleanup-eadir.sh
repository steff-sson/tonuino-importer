#!/usr/bin/env bash
# Delete all @eaDir metadata directories recursively from SOURCE_MEDIA.
# Synology NAS creates these; they contain pseudo-.mp3 directories that
# break rglob("*.mp3") scans.
# Idempotent – safe to run multiple times.

set -euo pipefail

SOURCE_MEDIA="${1:-/home/stef/docker/media/tonuino/sd-card-complete/}"

if [[ ! -d "$SOURCE_MEDIA" ]]; then
    echo "ERROR: '$SOURCE_MEDIA' ist kein Verzeichnis oder existiert nicht."
    exit 1
fi

echo "==> Suche @eaDir in: $SOURCE_MEDIA"
FOUND=$(find "$SOURCE_MEDIA" -type d -name '@eaDir' 2>/dev/null)

if [[ -z "$FOUND" ]]; then
    echo "Keine @eaDir-Verzeichnisse gefunden."
    exit 0
fi

COUNT=$(echo "$FOUND" | wc -l)
echo "$FOUND"
echo "==> $COUNT @eaDir-Verzeichnis(se) gefunden."

read -r -p "Löschen? [j/N] " CONFIRM
if [[ "$CONFIRM" != "j" && "$CONFIRM" != "J" ]]; then
    echo "Abgebrochen."
    exit 0
fi

echo "Lösche..."
find "$SOURCE_MEDIA" -type d -name '@eaDir' -exec rm -rf {} + 2>/dev/null || true
echo "Fertig. $COUNT @eaDir-Verzeichnis(se) gelöscht."
