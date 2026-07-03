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


def _get_visible_subdirs(path: Path) -> list[Path]:
    """Return visible subdirectories, excluding hidden, @eaDir, and non-directories."""
    return sorted(
        [d for d in path.iterdir()
         if d.is_dir() and not d.name.startswith('.') and d.name != '@eaDir'],
        key=lambda d: str(d).lower()
    )


def _scan_single(source: Path, start_num: int = 1) -> dict:
    """Core scan logic: detect subdirs, build tracks + episodes.

    Returns dict with keys: tracks, total, episodes.
    Global track numbering starts at start_num.
    """
    subdirs = _get_visible_subdirs(source)

    if subdirs:
        return _scan_with_subdirs(source, subdirs, start_num)
    else:
        return _scan_flat(source, start_num)


def _scan_with_subdirs(source: Path, subdirs: list[Path], start_num: int) -> dict:
    """Rule 1: each subdir = one episode."""
    tracks = []
    episodes = []
    global_num = start_num

    for subdir in subdirs:
        ep_start = global_num
        mp3s = natsorted(find_mp3s(subdir))
        if not mp3s:
            continue  # empty subdir — skip silently
        for mp3 in mp3s:
            dest_name = build_dest_name(mp3.stem, global_num) + ".mp3"
            tracks.append({
                "src": str(mp3),
                "src_name": mp3.name,
                "dest_preview": dest_name,
                "global_num": global_num,
            })
            global_num += 1
        episodes.append({
            "title": subdir.name,
            "track_start": ep_start,
            "track_end": global_num - 1,
        })

    return {"tracks": tracks, "total": len(tracks), "episodes": episodes}


def _scan_flat(source: Path, start_num: int) -> dict:
    """Rule 2: no subdirs — all MP3s = one episode."""
    mp3s = natsorted(find_mp3s(source))
    if not mp3s:
        return {"tracks": [], "total": 0, "episodes": []}

    tracks = []
    for i, mp3 in enumerate(mp3s, start_num):
        dest_name = build_dest_name(mp3.stem, i) + ".mp3"
        tracks.append({
            "src": str(mp3),
            "src_name": mp3.name,
            "dest_preview": dest_name,
            "global_num": i,
        })

    return {
        "tracks": tracks,
        "total": len(tracks),
        "episodes": [{
            "title": source.name,
            "track_start": start_num,
            "track_end": start_num + len(tracks) - 1,
        }],
    }


def scan_source(source: Path) -> dict:
    """Scan SOURCE directory for mp3 files.

    - Has subdirs → each subdir = one episode (Rule 1)
    - No subdirs → all MP3s = one episode, title = source.name (Rule 2)
    """
    if not source.exists():
        raise FileNotFoundError(f"Pfad nicht gefunden: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {source}")

    result = _scan_single(source, 1)
    return {
        "series": source.name,
        **result,
    }


def scan_multiple_sources(sources: list[Path]) -> dict:
    """Scan multiple source directories. Each processed through Rule 1/2, merged."""
    if not sources:
        raise ValueError("Keine Quellverzeichnisse angegeben")
    for s in sources:
        if not s.exists():
            raise FileNotFoundError(f"Pfad nicht gefunden: {s}")
        if not s.is_dir():
            raise NotADirectoryError(f"Kein Verzeichnis: {s}")

    series = _common_parent_name(sources)
    all_tracks = []
    all_episodes = []
    offset = 1

    for s in sorted(sources, key=lambda p: str(p).lower()):
        result = _scan_single(s, offset)
        all_tracks.extend(result["tracks"])
        all_episodes.extend(result["episodes"])
        offset = len(all_tracks) + 1

    return {
        "series": series,
        "tracks": all_tracks,
        "total": len(all_tracks),
        "episodes": all_episodes,
    }


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

