#!/usr/bin/env bash
# Delete all @eaDir metadata directories recursively from SOURCE_MEDIA.
# Synology NAS creates these; they contain pseudo-.mp3 directories that
# break rglob("*.mp3") scans.
# Idempotent – safe to run multiple times.

set -euo pipefail

usage() {
    echo "Usage: $0 --path <verzeichnis>"
    exit 1
}

SOURCE_MEDIA=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --path)
            [[ -z "${2:-}" ]] && usage
            SOURCE_MEDIA="$2"
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

[[ -z "$SOURCE_MEDIA" ]] && usage

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
