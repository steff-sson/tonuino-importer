import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..scanner import scan_source, scan_multiple_sources, collect_mp3s_from_paths, compute_split_chunks, TrackLimitError
from ..importer import run_import, run_split_import
from ..overview import get_free_folders
from ..config import MAX_TRACKS
from ..render import render

router = APIRouter()

# In-memory task store
_tasks: dict[str, dict] = {}

BROWSE_ROOT = Path("/volume1/")
NAV_ROOT = Path("/")
SYSTEM_EXCLUDED = {"/proc", "/sys", "/dev", "/run", "/lost+found", "/snapshots", "/backups", "@eaDir"}


@router.get("/import")
async def import_page(request: Request):
    return render("import.html", {"request": request})


@router.get("/browse/{path:path}")
async def browse(request: Request, path: str = "", q: str = ""):
    """Breadcrumb + List-View für eine Verzeichnisebene."""
    target = (NAV_ROOT / path).resolve() if path else NAV_ROOT.resolve()

    # Sicherheit: Systemverzeichnisse blocken
    if any(str(target).startswith(p) for p in SYSTEM_EXCLUDED):
        return JSONResponse(status_code=403, content={"error": "Nicht erlaubt"})

    # Sicherheit: Nicht über NAV_ROOT hinaus
    if not str(target).startswith(str(NAV_ROOT.resolve())):
        target = NAV_ROOT.resolve()

    if not target.exists() or not target.is_dir():
        return JSONResponse(status_code=404)

    # Breadcrumb bauen (von NAV_ROOT)
    crumbs = []
    current = target
    while current != NAV_ROOT.resolve() and current != current.parent:
        crumbs.insert(0, {"name": current.name, "path": str(current.relative_to(NAV_ROOT))})
        current = current.parent
    crumbs.insert(0, {"name": NAV_ROOT.name, "path": ""})

    # Items auflisten
    items = []
    try:
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith('.'):
                continue
            if item.is_dir() and not item.is_symlink():
                has_mp3 = False
                try:
                    has_mp3 = any(item.glob("*.mp3"))
                except (PermissionError, OSError):
                    pass
                items.append({
                    "type": "folder",
                    "name": item.name,
                    "rel_path": str(item.relative_to(NAV_ROOT)),
                    "has_mp3": has_mp3,
                })
            elif not item.is_dir():
                items.append({"type": "file", "name": item.name})
    except PermissionError:
        pass

    # Filter (case-insensitive)
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["name"].lower()]

    return render("partials/browser.html", {
        "request": request,
        "crumbs": crumbs,
        "items": items,
        "current_path": str(target),
        "parent_path": None if target == NAV_ROOT.resolve() else ("" if target.parent == NAV_ROOT.resolve() else str(target.parent.relative_to(NAV_ROOT))),
        "query": q,
    })


class ScanRequest(BaseModel):
    source: str


@router.post("/api/scan")
async def api_scan(request: Request, source: str = Form(...)):
    """Scan source directory — returns HTML partial."""
    try:
        # Resolve relative paths to absolute
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = (NAV_ROOT / source).resolve()
        result = await asyncio.to_thread(scan_source, source_path)
        ctx = {
            "request": request,
            "source": str(source_path),
            "series": result["series"],
            "total": result["total"],
            "episodes": result["episodes"],
            "max_tracks": MAX_TRACKS,
        }

        if result["total"] > MAX_TRACKS:
            # Compute split
            chunks = compute_split_chunks(result["episodes"], result["total"], MAX_TRACKS)
            free_folders = get_free_folders(len(chunks))

            # Assign folder numbers for preview
            for i, chunk in enumerate(chunks):
                if i < len(free_folders):
                    chunk["folder_number"] = free_folders[i]
                else:
                    chunk["folder_number"] = None

            ctx["split_chunks"] = chunks
            ctx["free_folders"] = free_folders
            ctx["tracks"] = []  # don't show rename preview for split (would be huge)
        else:
            ctx["tracks"] = result["tracks"]

        return render("partials/preview.html", ctx)
    except Exception as e:
        return render("partials/preview.html", {
            "request": request,
            "error": str(e),
        })


class ImportRequest(BaseModel):
    source: str
    sd_folder: int
    overwrite: bool = False
    paths: list[str] | None = None


class SplitImportRequest(BaseModel):
    source: str
    overwrite: bool = False
    paths: list[str] | None = None


class ScanMultipleRequest(BaseModel):
    paths: list[str]


@router.post("/api/scan-multiple")
async def api_scan_multiple(request: Request, req: ScanMultipleRequest):
    """Scan multiple source directories — returns HTML partial."""
    try:
        source_paths = []
        for p in req.paths:
            sp = Path(p)
            if not sp.is_absolute():
                sp = (NAV_ROOT / p).resolve()
            source_paths.append(sp)

        result = await asyncio.to_thread(scan_multiple_sources, source_paths)
        ctx = {
            "request": request,
            "source": str(source_paths[0].parent) if source_paths else "",
            "series": result["series"],
            "total": result["total"],
            "episodes": result["episodes"],
            "max_tracks": MAX_TRACKS,
        }

        if result["total"] > MAX_TRACKS:
            chunks = compute_split_chunks(result["episodes"], result["total"], MAX_TRACKS)
            free_folders = get_free_folders(len(chunks))
            for i, chunk in enumerate(chunks):
                chunk["folder_number"] = free_folders[i] if i < len(free_folders) else None
            ctx["split_chunks"] = chunks
            ctx["free_folders"] = free_folders
            ctx["tracks"] = []
        else:
            ctx["tracks"] = result["tracks"]

        return render("partials/preview.html", ctx)
    except Exception as e:
        return render("partials/preview.html", {"request": request, "error": str(e)})


@router.post("/api/import/start")
async def api_import_start(req: ImportRequest):
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {"status": "running", "progress": None, "result": None, "error": None}

    source = Path(req.source)

    async def progress_cb(current: int, total: int, file: str = ""):
        _tasks[task_id]["progress"] = {
            "current": current,
            "total": total,
            "file": file,
            "percent": round(current / total * 100, 1) if total else 0,
        }

    async def _run():
        try:
            if req.paths:
                mp3_paths = collect_mp3s_from_paths(req.paths, NAV_ROOT)
                if not mp3_paths:
                    raise ValueError("Keine MP3-Dateien in den ausgewählten Ordnern")
            else:
                mp3_paths = None

            result = await run_import(source, req.sd_folder, task_id, progress_cb, req.overwrite, mp3_paths)
            _tasks[task_id]["status"] = "complete"
            _tasks[task_id]["result"] = result
        except TrackLimitError as e:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)
        except Exception as e:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)

    asyncio.create_task(_run())
    return {"task_id": task_id}


@router.get("/api/import/progress/{task_id}")
async def api_import_progress(task_id: str):
    from starlette.responses import StreamingResponse
    import asyncio
    import json

    async def event_stream():
        while True:
            task = _tasks.get(task_id)
            if not task:
                yield f"event: error\ndata: {json.dumps({'message': 'Task nicht gefunden'})}\n\n"
                break

            if task["status"] == "running" and task["progress"]:
                yield f"event: progress\ndata: {json.dumps(task['progress'])}\n\n"
            elif task["status"] == "complete":
                yield f"event: complete\ndata: {json.dumps(task['result'])}\n\n"
                break
            elif task["status"] == "error":
                yield f"event: error\ndata: {json.dumps({'message': task['error']})}\n\n"
                break

            # Keepalive
            yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/import/split-start")
async def api_split_import_start(req: SplitImportRequest):
    """Start a split import: scan source, compute chunks, assign folders, run."""
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {"status": "running", "progress": None, "result": None, "error": None}

    source = Path(req.source)

    async def progress_cb(current: int, total: int, file: str = ""):
        _tasks[task_id]["progress"] = {
            "current": current,
            "total": total,
            "file": file,
            "percent": round(current / total * 100, 1) if total else 0,
        }

    async def _run():
        try:
            # Scan + compute split
            if req.paths:
                # Multi-source: collect MP3s AND scan for episode data
                mp3_paths = collect_mp3s_from_paths(req.paths, NAV_ROOT)
                if not mp3_paths:
                    raise ValueError("Keine MP3-Dateien in den ausgewählten Ordnern")
                source_paths = [Path(p) for p in req.paths]
                scan_result = await asyncio.to_thread(scan_multiple_sources, source_paths)
            else:
                mp3_paths = None
                scan_result = await asyncio.to_thread(scan_source, source)

            if scan_result["total"] == 0:
                raise ValueError("Keine MP3-Dateien im Quellverzeichnis")

            chunks = compute_split_chunks(
                scan_result["episodes"], scan_result["total"], MAX_TRACKS
            )
            free_folders = get_free_folders(len(chunks))

            if len(free_folders) < len(chunks):
                raise ValueError(
                    f"Nicht genügend freie Ordner: {len(chunks)} benötigt, "
                    f"nur {len(free_folders)} verfügbar"
                )

            # Assign folder numbers
            for i, chunk in enumerate(chunks):
                chunk["folder_number"] = free_folders[i]

            # Run split import
            result = await run_split_import(
                source, chunks, task_id, progress_cb, req.overwrite, mp3_paths
            )
            _tasks[task_id]["status"] = "complete"
            _tasks[task_id]["result"] = result
        except Exception as e:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)

    asyncio.create_task(_run())
    return {"task_id": task_id}


@router.post("/api/sync")
async def api_sync():
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {"status": "running", "progress": None, "result": None, "error": None}

    async def progress_cb(current: int, total: int, file: str = ""):
        _tasks[task_id]["progress"] = {
            "current": current, "total": total, "file": file,
            "percent": round(current / total * 100, 1) if total else 0,
        }

    async def _run():
        try:
            from ..rsync import run_rsync
            result = await run_rsync(task_id=task_id, progress_cb=progress_cb)
            _tasks[task_id]["status"] = "complete"
            _tasks[task_id]["result"] = result
        except Exception as e:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)

    asyncio.create_task(_run())
    return {"task_id": task_id}
