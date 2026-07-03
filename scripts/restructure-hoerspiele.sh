#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# restructure-hoerspiele.sh
# Filesystem-Restructuring für TonUINO Episode-Detection
#
# Section 1: FLATTEN — Move MP3s from subdirs up (Krachmacherstraße, Emil)
# Section 2: SPLIT  — ffmpeg 120s chunks (Pumuckl 1-14, Batwheels, PJ Masks)
# Section 3: CLEANUP — Summary + .originals/ hint
# =============================================================================

# === Config ===
BASE_PATH=""
DRY_RUN=false

# === Colors ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") --path <base_path> [--dry-run]

Options:
  --path <path>   Base path to Hoerspiele directory (required)
  --dry-run       Show what would happen, don't execute

Example:
  $(basename "$0") --path /volume1/daten/Hoerspiele --dry-run
  $(basename "$0") --path /volume1/daten/Hoerspiele
EOF
    exit 1
}

# === Helper Functions ===

log_info()  { echo -e "${GREEN}==> $*${NC}"; }
log_warn()  { echo -e "${YELLOW}==> WARN: $*${NC}"; }
log_error() { echo -e "${RED}==> ERROR: $*${NC}" >&2; }

run_cmd() {
    if $DRY_RUN; then
        echo "[DRY-RUN] $*"
        return 0
    fi
    echo "[EXEC] $*"
    "$@"
}

# === Section 1: FLATTEN ===

flatten_dir() {
    local dir="$1"
    local dir_name
    dir_name=$(basename "$dir")

    if [[ ! -d "$dir" ]]; then
        log_warn "Verzeichnis nicht gefunden: $dir — überspringe"
        return 0
    fi

    log_info "FLATTEN: $dir_name"

    local subdir_count=0
    local file_count=0

    # Find subdirectories (skip @eaDir)
    while IFS= read -r -d '' subdir; do
        # Skip @eaDir
        if [[ "$(basename "$subdir")" == "@eaDir" ]]; then
            continue
        fi

        subdir_count=$((subdir_count + 1))

        # Move all MP3s up
        local moved=0
        while IFS= read -r -d '' mp3; do
            local filename
            filename=$(basename "$mp3")
            run_cmd mv -n "$mp3" "$dir/$filename"
            moved=$((moved + 1))
            file_count=$((file_count + 1))
        done < <(find "$subdir" -maxdepth 1 -type f -name "*.mp3" -print0)

        # Try to remove empty subdirectory
        if ! $DRY_RUN; then
            if rmdir "$subdir" 2>/dev/null; then
                log_info "  Entfernt: $(basename "$subdir")/"
            else
                log_warn "  Nicht leer: $(basename "$subdir")/ — überspringe"
            fi
        else
            echo "[DRY-RUN] rmdir $subdir"
        fi

    done < <(find "$dir" -maxdepth 1 -mindepth 1 -type d -print0)

    if [[ $subdir_count -eq 0 ]]; then
        log_info "  Keine Subdirs gefunden"
    else
        log_info "  $file_count Dateien aus $subdir_count Subdirs verschoben"
    fi
}

# === Section 2: SPLIT ===

split_episode() {
    local input_file="$1"
    local series_name="$2"
    local ep_number="$3"
    local ep_title="$4"
    local output_base="$5"

    local subdir="$output_base/$ep_number - $ep_title"

    # Check if subdir already exists (idempotent)
    if [[ -d "$subdir" ]]; then
        log_warn "  Subdir existiert bereits: $ep_number - $ep_title — überspringe"
        return 0
    fi

    # Create subdir
    run_cmd mkdir -p "$subdir"

    # Split with ffmpeg
    local output_pattern="$subdir/%02d - $series_name - $ep_number - $ep_title.mp3"
    run_cmd ffmpeg -y -i "$input_file" -f segment -segment_time 120 -c copy "$output_pattern"

    # Move original to .originals/
    local originals_dir="$output_base/.originals"
    run_cmd mkdir -p "$originals_dir"
    run_cmd mv -n "$input_file" "$originals_dir/"

    log_info "  Gesplittet: $(basename "$input_file") → $ep_number - $ep_title/"
}

split_pumuckl() {
    local pumuckl_dir="$BASE_PATH/Pumuckl"

    if [[ ! -d "$pumuckl_dir" ]]; then
        log_warn "Pumuckl-Verzeichnis nicht gefunden: $pumuckl_dir"
        return 0
    fi

    log_info "SPLIT: Pumuckl (Episoden 1-14)"

    # Pattern: Pumuckl - NN - Title - 01.mp3
    local pattern="Pumuckl - ([0-9]{2}) - (.+?) - [0-9]{2}\.mp3"

    while IFS= read -r -d '' mp3; do
        local filename
        filename=$(basename "$mp3")

        # Extract episode number and title
        local ep_number ep_title
        if [[ "$filename" =~ ^Pumuckl\ -\ ([0-9]{2})\ -\ (.+?)\ -\ [0-9]{2}\.mp3$ ]]; then
            ep_number="${BASH_REMATCH[1]}"
            ep_title="${BASH_REMATCH[2]}"
        else
            log_warn "  Dateiname passt nicht zum Muster: $filename — überspringe"
            continue
        fi

        # Skip episode 15 (already exists as subdir)
        if [[ "$ep_number" == "15" ]]; then
            log_info "  Überspringe Episode 15 (bereits als Subdir vorhanden)"
            continue
        fi

        split_episode "$mp3" "Pumuckl" "$ep_number" "$ep_title" "$pumuckl_dir"

    done < <(find "$pumuckl_dir" -maxdepth 1 -type f -name "Pumuckl - *.mp3" -print0)
}

split_batwheels() {
    local batwheels_dir="$BASE_PATH/Batwheels"

    if [[ ! -d "$batwheels_dir" ]]; then
        log_warn "Batwheels-Verzeichnis nicht gefunden: $batwheels_dir"
        return 0
    fi

    log_info "SPLIT: Batwheels (20 Episoden)"

    # Pattern: Batwheels - NN - Title.mp3 or Batwheels - NN.mp3
    while IFS= read -r -d '' mp3; do
        local filename
        filename=$(basename "$mp3")

        local ep_number ep_title
        if [[ "$filename" =~ ^Batwheels\ -\ ([0-9]{2})\ -\ (.+)\.mp3$ ]]; then
            ep_number="${BASH_REMATCH[1]}"
            ep_title="${BASH_REMATCH[2]}"
        elif [[ "$filename" =~ ^Batwheels\ -\ ([0-9]{2})\.mp3$ ]]; then
            ep_number="${BASH_REMATCH[1]}"
            ep_title="Episode $ep_number"
        else
            log_warn "  Dateiname passt nicht zum Muster: $filename — überspringe"
            continue
        fi

        split_episode "$mp3" "Batwheels" "$ep_number" "$ep_title" "$batwheels_dir"

    done < <(find "$batwheels_dir" -maxdepth 1 -type f -name "Batwheels - *.mp3" -print0)
}

split_pjmasks() {
    local pjmasks_dir="$BASE_PATH/PJ Masks - Wir knacken den Fall!"

    if [[ ! -d "$pjmasks_dir" ]]; then
        log_warn "PJ Masks-Verzeichnis nicht gefunden: $pjmasks_dir"
        return 0
    fi

    log_info "SPLIT: PJ Masks - Wir knacken den Fall! (6 Episoden)"

    # Pattern: PJ Masks - NN - Title.mp3
    while IFS= read -r -d '' mp3; do
        local filename
        filename=$(basename "$mp3")

        local ep_number ep_title
        if [[ "$filename" =~ ^PJ\ Masks\ -\ ([0-9]{2})\ -\ (.+)\.mp3$ ]]; then
            ep_number="${BASH_REMATCH[1]}"
            ep_title="${BASH_REMATCH[2]}"
        elif [[ "$filename" =~ ^PJ\ Masks\ -\ ([0-9]{2})\.mp3$ ]]; then
            ep_number="${BASH_REMATCH[1]}"
            ep_title="Episode $ep_number"
        else
            log_warn "  Dateiname passt nicht zum Muster: $filename — überspringe"
            continue
        fi

        split_episode "$mp3" "PJ Masks" "$ep_number" "$ep_title" "$pjmasks_dir"

    done < <(find "$pjmasks_dir" -maxdepth 1 -type f -name "PJ Masks - *.mp3" -print0)
}

# === Section 3: CLEANUP ===

cleanup_originals() {
    log_info "CLEANUP: Zusammenfassung der .originals/ Verzeichnisse"

    local found=0

    for dir in "$BASE_PATH/Pumuckl/.originals" "$BASE_PATH/Batwheels/.originals" "$BASE_PATH/PJ Masks - Wir knacken den Fall!/.originals"; do
        if [[ -d "$dir" ]]; then
            local count
            count=$(find "$dir" -type f -name "*.mp3" | wc -l)
            echo "  $count Originale in: $dir"
            found=$((found + count))
        fi
    done

    if [[ $found -gt 0 ]]; then
        echo ""
        echo -e "${GREEN}==> $found Originale in .originals/ — manuell löschen mit:${NC}"
        echo "  rm -rf \"$BASE_PATH/Pumuckl/.originals/\""
        echo "  rm -rf \"$BASE_PATH/Batwheels/.originals/\""
        echo "  rm -rf \"$BASE_PATH/PJ Masks - Wir knacken den Fall!/.originals/\""
    else
        log_info "Keine .originals/ Verzeichnisse gefunden"
    fi
}

# === Main ===

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --path)
                BASE_PATH="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            *)
                echo "Unbekannte Option: $1"
                usage
                ;;
        esac
    done

    # Validate required arguments
    if [[ -z "$BASE_PATH" ]]; then
        log_error "Fehlender Parameter: --path"
        usage
    fi

    if [[ ! -d "$BASE_PATH" ]]; then
        log_error "Verzeichnis existiert nicht: $BASE_PATH"
        exit 1
    fi

    # Check prerequisites
    if ! command -v ffmpeg &>/dev/null; then
        log_error "ffmpeg ist nicht installiert"
        log_error "Installiere mit: sudo pacman -S ffmpeg"
        exit 1
    fi

    echo "=========================================="
    echo "TonUINO Filesystem-Restructure"
    echo "=========================================="
    echo "Base Path: $BASE_PATH"
    echo "Dry Run:   $DRY_RUN"
    echo "=========================================="
    echo ""

    # Section 1: FLATTEN
    echo "=== Section 1: FLATTEN ==="
    flatten_dir "$BASE_PATH/Die Kinder aus der Krachmacherstraße"
    flatten_dir "$BASE_PATH/Emil und die Detektive - Hörbuch"
    echo ""

    # Section 2: SPLIT
    echo "=== Section 2: SPLIT ==="
    split_pumuckl
    split_batwheels
    split_pjmasks
    echo ""

    # Section 3: CLEANUP
    echo "=== Section 3: CLEANUP ==="
    cleanup_originals
    echo ""

    # Final summary
    echo "=========================================="
    echo -e "${GREEN}FERTIG${NC}"
    echo "=========================================="
    echo ""
    echo "Verifikation:"
    echo "  find \"$BASE_PATH/Die Kinder aus der Krachmacherstraße\" -maxdepth 1 -type f -name \"*.mp3\" | wc -l"
    echo "  find \"$BASE_PATH/Emil und die Detektive - Hörbuch\" -maxdepth 1 -type f -name \"*.mp3\" | wc -l"
    echo "  ls -d \"$BASE_PATH/Pumuckl\"/*/"
    echo "  ls -d \"$BASE_PATH/Batwheels\"/*/"
    echo "  ls -d \"$BASE_PATH/PJ Masks - Wir knacken den Fall!\"/*/"
}

main "$@"
