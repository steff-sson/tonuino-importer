import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from natsort import natsorted

from .config import DEST_DIR, MAX_TRACKS
from .scanner import build_dest_name, check_limit, find_mp3s, TrackLimitError


async def run_import(
    source: Path,
    sd_folder: int,
    task_id: str,
    progress_cb=None,
    overwrite: bool = False,
    mp3_paths: list[Path] | None = None,
) -> dict:
    """Import tracks from SOURCE to DEST/sd_folder. Returns result dict."""
    dest = DEST_DIR / f"{sd_folder:02d}"
    dest.mkdir(parents=True, exist_ok=True)

    if overwrite:
        for f in dest.glob("*.mp3"):
            f.unlink()
        import_file = dest / ".import.json"
        if import_file.exists():
            import_file.unlink()

    if mp3_paths is not None:
        mp3s = mp3_paths
        total = len(mp3s)
        if total == 0:
            raise ValueError("Keine MP3-Dateien im Quellverzeichnis")
    else:
        mp3s = natsorted(find_mp3s(source))
        total = len(mp3s)
        if total == 0:
            raise ValueError("Keine MP3-Dateien im Quellverzeichnis")

    existing = check_limit(dest, total)

    # Bestehende Nummierung: next_free = max(existing_nummer, 0) + 1
    next_free = 1
    for f in dest.glob("*.mp3"):
        m = _parse_track_num(f.stem)
        if m and m >= next_free:
            next_free = m + 1

    imported_files = []
    episodes = []
    current_episode = None
    global_num = next_free

    for i, mp3 in enumerate(mp3s):
        dest_name = build_dest_name(mp3.stem, global_num) + mp3.suffix
        dest_path = dest / dest_name

        await asyncio.to_thread(shutil.copy2, str(mp3), str(dest_path))
        imported_files.append(dest_name)

        # Episode-Gruppierung
        episode_title = _extract_episode_title(mp3.stem)
        if episode_title and (current_episode is None or current_episode["title"] != episode_title):
            if current_episode:
                current_episode["track_end"] = global_num - 1
                episodes.append(current_episode)
            current_episode = {"title": episode_title, "track_start": global_num, "track_end": 0}

        if progress_cb:
            await progress_cb(current=global_num - next_free + 1, total=total, file=dest_name)

        global_num += 1

    if current_episode:
        current_episode["track_end"] = global_num - 1
        episodes.append(current_episode)

    # .import.json schreiben
    import_file = dest / ".import.json"
    if overwrite:
        import_data = {
            "series": source.name,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source_path": str(source),
            "total_tracks": total,
            "episodes": episodes,
        }
    else:
        prev_data = {}
        if import_file.exists():
            try:
                prev_data = json.loads(import_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        prev_episodes = prev_data.get("episodes", [])
        merged_episodes = prev_episodes + episodes
        import_data = {
            "series": prev_data.get("series", source.name),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source_path": str(source),
            "total_tracks": existing + total,
            "episodes": merged_episodes,
        }
    import_file.write_text(json.dumps(import_data, indent=2, ensure_ascii=False))

    return {
        "series": source.name,
        "sd_folder": sd_folder,
        "total_tracks": existing + total,
        "new_tracks": total,
        "existing_tracks": existing,
        "episodes": episodes,
    }


async def run_split_import(
    source: Path,
    chunks: list[dict],  # each: {track_start, track_end, episodes, folder_number}
    task_id: str,
    progress_cb=None,
    overwrite: bool = False,
    mp3_paths: list[Path] | None = None,
) -> dict:
    """Import a large source split across multiple SD folders.

    Scans source once, copies track slices to assigned folders with local
    numbering (001, 002, ...). Each folder gets its own .import.json with
    episode ranges localized to that folder's track numbering.
    """
    if mp3_paths is not None:
        mp3s = mp3_paths
    else:
        mp3s = natsorted(find_mp3s(source))
    total = len(mp3s)
    if total == 0:
        raise ValueError("Keine MP3-Dateien im Quellverzeichnis")

    results = []
    global_done = 0

    for chunk in chunks:
        folder = chunk["folder_number"]
        dest = DEST_DIR / f"{folder:02d}"
        dest.mkdir(parents=True, exist_ok=True)

        # --- Overwrite cleanup (same logic as run_import) ---
        if overwrite:
            for f in dest.glob("*.mp3"):
                f.unlink()
            ij = dest / ".import.json"
            if ij.exists():
                ij.unlink()

        # --- Slice tracks for this chunk (1-indexed → 0-indexed) ---
        start_idx = chunk["track_start"] - 1
        end_idx = chunk["track_end"]  # exclusive: track_end is inclusive, so slice to track_end
        chunk_mp3s = mp3s[start_idx:end_idx]
        chunk_total = len(chunk_mp3s)

        # --- Copy with local numbering (001, 002, ...) ---
        local_num = 1
        for mp3 in chunk_mp3s:
            dest_name = build_dest_name(mp3.stem, local_num) + mp3.suffix
            dest_path = dest / dest_name

            await asyncio.to_thread(shutil.copy2, str(mp3), str(dest_path))

            local_num += 1
            global_done += 1

            if progress_cb:
                await progress_cb(
                    current=global_done,
                    total=total,
                    file=f"[Ordner {folder:02d}] {dest_name}",
                )

        # --- Localize episode track numbers for this folder ---
        local_episodes = []
        for ep in chunk.get("episodes", []):
            local_episodes.append({
                "title": ep["title"],
                "track_start": ep["track_start"] - chunk["track_start"] + 1,
                "track_end": ep["track_end"] - chunk["track_start"] + 1,
            })

        # --- Write .import.json ---
        import_data = {
            "series": source.name,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source_path": str(source),
            "total_tracks": chunk_total,
            "episodes": local_episodes,
        }
        ij_path = dest / ".import.json"
        ij_path.write_text(json.dumps(import_data, indent=2, ensure_ascii=False))

        results.append({
            "folder_number": folder,
            "track_count": chunk_total,
            "episodes": local_episodes,
        })

    return {
        "series": source.name,
        "total_tracks": total,
        "folders": results,
    }


def _parse_track_num(stem: str) -> int | None:
    """Extract leading 3-digit track number from stem."""
    import re
    m = re.match(r"^(\d{3})\s*[-–]", stem)
    return int(m.group(1)) if m else None


def _extract_episode_title(stem: str) -> str:
    """Extract episode title for grouping."""
    import re
    cleaned = re.sub(r"^\d{1,4}\s*[-–]\s*", "", stem)
    # Strip trailing per-episode track number (e.g. " - 01" at end)
    cleaned = re.sub(r"\s*[-–]\s*\d{1,3}$", "", cleaned)
    # Find episode marker anywhere in the string (not just at start)
    m = re.search(
        r"((?:Folge|Episode|Teil|Kapitel)\s*\d{1,3})(?:\s*[-–]\s*(.+))?",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        title = m.group(1)
        if m.group(2):
            title += f" - {m.group(2)}"
        return title
    return cleaned
