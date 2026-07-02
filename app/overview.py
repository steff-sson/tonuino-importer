import json
from pathlib import Path

from natsort import natsorted

from .config import DEST_DIR


def get_sd_folders() -> list[dict]:
    """Scan DEST for all numbered folders (01-99). Returns list with metadata."""
    folders = []
    for n in range(1, 100):
        folder = DEST_DIR / f"{n:02d}"
        if folder.exists():
            mp3s = list(folder.glob("*.mp3"))
            import_data = _load_import_json(folder)
            # Compute display title: series first, fall back to first episode
            display_title = ""
            if import_data:
                display_title = import_data.get("series", "") or ""
                if not display_title:
                    episodes = import_data.get("episodes", [])
                    if episodes:
                        display_title = episodes[0].get("title", "")
            folders.append({
                "number": n,
                "name": f"{n:02d}",
                "track_count": len(mp3s),
                "series": import_data.get("series", "") if import_data else "",
                "display_title": display_title,
                "has_import": import_data is not None,
            })
    return folders


def get_populated_folders() -> list[dict]:
    """Return only folders that contain tracks, sorted by number."""
    return [f for f in get_sd_folders() if f["track_count"] > 0]


def get_free_folders(count: int) -> list[int]:
    """Return the first `count` free folder numbers (1-99), preferring consecutive ranges.

    Always returns consecutives because we scan 1..99 in order and skip occupied ones.
    May return fewer than `count` if not enough free folders exist.
    """
    occupied = {f["number"] for f in get_sd_folders()}
    free = []
    for n in range(1, 100):
        if n not in occupied:
            free.append(n)
            if len(free) == count:
                return free
    return free


def get_folder_detail(n: int) -> dict:
    """Get detail for a single SD folder: tracks + episodes from .import.json."""
    folder = DEST_DIR / f"{n:02d}"
    if not folder.exists():
        return {"number": n, "tracks": [], "episodes": [], "import_data": None}

    mp3s = natsorted(folder.glob("*.mp3"))
    import_data = _load_import_json(folder)

    tracks = []
    for i, mp3 in enumerate(mp3s, 1):
        tracks.append({"num": i, "name": mp3.name, "size_kb": mp3.stat().st_size // 1024})

    episodes = import_data.get("episodes", []) if import_data else []

    return {
        "number": n,
        "tracks": tracks,
        "episodes": episodes,
        "import_data": import_data,
    }


def get_stats() -> dict:
    """Global stats: folders used, total tracks, total size."""
    folders = get_sd_folders()
    total_tracks = sum(f["track_count"] for f in folders)
    total_size = 0
    for f in folders:
        folder = DEST_DIR / f"{f['number']:02d}"
        for mp3 in folder.glob("*.mp3"):
            total_size += mp3.stat().st_size
    return {
        "folders_used": len(folders),
        "total_tracks": total_tracks,
        "total_size_gb": round(total_size / (1024 ** 3), 2),
    }


def _load_import_json(folder: Path) -> dict | None:
    p = folder / ".import.json"
    if p.exists():
        return json.loads(p.read_text())
    return None
