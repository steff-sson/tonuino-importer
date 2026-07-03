import os
import re
import unicodedata
from pathlib import Path

from natsort import natsorted

from .config import MAX_TRACKS

LEADING_NUM = re.compile(r"^\d{1,4}\s*[-–]\s*")
FAT32_SANITIZE = re.compile(r'[<>:"/\\|?*]')


def find_mp3s(path: Path) -> list[Path]:
    """rglob *.mp3, filter @eaDir and non-file entries (Synology NAS metadata)."""
    return [
        p for p in path.rglob("*.mp3")
        if "@eaDir" not in p.parts and p.is_file()
    ]


def scan_source(source: Path) -> dict:
    """Scan SOURCE directory recursively for mp3 files. Returns preview dict."""
    if not source.exists():
        raise FileNotFoundError(f"Pfad nicht gefunden: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {source}")

    mp3s = natsorted(find_mp3s(source))
    if not mp3s:
        return {"series": source.name, "tracks": [], "total": 0, "episodes": []}

    series = source.name
    tracks = []
    episodes = []
    current_episode = None
    global_num = 1

    for mp3 in mp3s:
        stem = mp3.stem
        dest_name = build_dest_name(stem, global_num) + ".mp3"

        # Gruppierung: Folge-/Episode-Erkennung
        episode_base = _normalize_episode(stem)

        if episode_base and (current_episode is None or current_episode["title"] != episode_base):
            if current_episode:
                current_episode["track_end"] = global_num - 1
                episodes.append(current_episode)
            current_episode = {"title": episode_base, "track_start": global_num, "track_end": 0}

        tracks.append({
            "src": str(mp3),
            "src_name": mp3.name,
            "dest_preview": dest_name,
            "global_num": global_num,
        })
        global_num += 1

    if current_episode:
        current_episode["track_end"] = global_num - 1
        episodes.append(current_episode)

    return {
        "series": series,
        "tracks": tracks,
        "total": len(tracks),
        "episodes": episodes,
    }


def scan_multiple_sources(sources: list[Path]) -> dict:
    """Scan multiple source directories and merge into one preview dict."""
    if not sources:
        raise ValueError("Keine Quellverzeichnisse angegeben")
    for s in sources:
        if not s.exists():
            raise FileNotFoundError(f"Pfad nicht gefunden: {s}")
        if not s.is_dir():
            raise NotADirectoryError(f"Kein Verzeichnis: {s}")

    all_mp3s = []
    for s in sorted(sources, key=lambda p: str(p).lower()):
        all_mp3s.extend(natsorted(find_mp3s(s)))

    if not all_mp3s:
        series = _common_parent_name(sources)
        return {"series": series, "tracks": [], "total": 0, "episodes": []}

    series = _common_parent_name(sources)
    tracks = []
    episodes = []
    current_episode = None
    global_num = 1

    for mp3 in all_mp3s:
        stem = mp3.stem
        dest_name = build_dest_name(stem, global_num) + ".mp3"
        episode_base = _normalize_episode(stem)
        if episode_base and (current_episode is None or current_episode["title"] != episode_base):
            if current_episode:
                current_episode["track_end"] = global_num - 1
                episodes.append(current_episode)
            current_episode = {"title": episode_base, "track_start": global_num, "track_end": 0}
        tracks.append({
            "src": str(mp3), "src_name": mp3.name,
            "dest_preview": dest_name, "global_num": global_num,
        })
        global_num += 1

    if current_episode:
        current_episode["track_end"] = global_num - 1
        episodes.append(current_episode)

    return {"series": series, "tracks": tracks, "total": len(tracks), "episodes": episodes}


def _common_parent_name(paths: list[Path]) -> str:
    """Return the common parent directory name for a list of paths."""
    if len(paths) == 1:
        return paths[0].parent.name if paths[0].parent != paths[0] else paths[0].name
    parents = [p.resolve() for p in paths]
    common = Path(os.path.commonpath([str(p) for p in parents]))
    return common.name if common.name else parents[0].parent.name


def collect_mp3s_from_paths(path_strs: list[str], nav_root: Path | None = None) -> list[Path]:
    """Resolve path strings, collect natsorted MP3s per folder, return merged list."""
    all_mp3s = []
    for ps in path_strs:
        p = Path(ps)
        if nav_root and not p.is_absolute():
            p = (nav_root / ps).resolve()
        if p.exists() and p.is_dir():
            all_mp3s.extend(natsorted(find_mp3s(p)))
    return all_mp3s


def build_dest_name(src_stem: str, global_num: int) -> str:
    """Strip leading number, prepend global track number."""
    rest = LEADING_NUM.sub("", src_stem)
    rest = FAT32_SANITIZE.sub("-", rest)
    rest = unicodedata.normalize("NFC", rest)
    return f"{global_num:03d} - {rest}"


def check_limit(dest: Path, new_count: int) -> int:
    """Check if adding new_count tracks exceeds MAX_TRACKS. Returns existing count."""
    exist = len(list(dest.glob("*.mp3"))) if dest.exists() else 0
    if exist + new_count > MAX_TRACKS:
        raise TrackLimitError(
            f"{dest.name}: {exist} vorhanden + {new_count} neu = {exist + new_count} > Limit {MAX_TRACKS}"
        )
    return exist


def compute_split_chunks(episodes: list[dict], total_tracks: int, max_tracks: int) -> list[dict]:
    """Split episodes into chunks that fit within max_tracks each.

    Walks episodes in order. When adding the next episode would exceed max_tracks,
    finalizes the current chunk and starts a new one. This ensures no episode is
    split across folders unless a single episode itself exceeds max_tracks
    (which would be a degenerate case — not explicitly handled; it would create
    a single-folder chunk exceeding the limit).

    Returns list of dicts with keys:
        track_start, track_end  — 1-indexed global track numbers
        track_count             — number of tracks in this chunk
        episodes                — list of episode dicts {title, track_start, track_end}
    """
    chunks = []
    current_eps = []
    current_start = None
    current_end = None

    for ep in episodes:
        ep_size = ep["track_end"] - ep["track_start"] + 1

        if current_start is None:
            # First episode in chunk
            current_start = ep["track_start"]
            current_end = ep["track_end"]
            current_eps.append(ep)
        elif (current_end - current_start + 1) + ep_size <= max_tracks:
            # Episode fits in current chunk
            current_end = ep["track_end"]
            current_eps.append(ep)
        else:
            # Episode doesn't fit — finalize current chunk, start new one
            chunks.append({
                "track_start": current_start,
                "track_end": current_end,
                "track_count": current_end - current_start + 1,
                "episodes": current_eps,
            })
            current_start = ep["track_start"]
            current_end = ep["track_end"]
            current_eps = [ep]

    # Finalize last chunk
    if current_eps:
        chunks.append({
            "track_start": current_start,
            "track_end": current_end,
            "track_count": current_end - current_start + 1,
            "episodes": current_eps,
        })

    return chunks


class TrackLimitError(Exception):
    pass


def _normalize_episode(stem: str) -> str:
    """Extract episode title for grouping."""
    cleaned = LEADING_NUM.sub("", stem)
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
