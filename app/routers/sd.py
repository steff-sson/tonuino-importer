from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..overview import get_sd_folders, get_folder_detail, clear_folder
from ..render import render

router = APIRouter()


@router.get("/sd")
async def sd_overview(request: Request):
    return RedirectResponse(url="/#sd", status_code=302)


@router.get("/sd/{n}")
async def sd_detail(request: Request, n: int):
    detail = get_folder_detail(n)
    return render("sd_detail.html", {"request": request, "detail": detail})


@router.get("/api/sd/folders")
async def api_sd_folders():
    """Return all 01-99 folders with occupancy info for dropdown."""
    existing = get_sd_folders()
    existing_map = {f["number"]: f for f in existing}
    folders = []
    for n in range(1, 100):
        if n in existing_map:
            f = existing_map[n]
            folders.append({
                "number": n,
                "label": f"{f['name']} ({f['series']}, {f['track_count']} Tracks)" if f["series"] else f"{f['name']} ({f['track_count']} Tracks)",
                "occupied": True,
                "track_count": f["track_count"],
            })
        else:
            folders.append({
                "number": n,
                "label": f"{n:02d} (frei)",
                "occupied": False,
                "track_count": 0,
            })
    # Default: erster freier Ordner
    next_free = next((f["number"] for f in folders if not f["occupied"]), 1)
    return JSONResponse({"folders": folders, "default": next_free})


@router.post("/api/sd/{folder_num}/clear")
async def clear_sd_folder(folder_num: int):
    if folder_num < 1 or folder_num > 99:
        return JSONResponse(status_code=400, content={"error": "Ungültige Ordnernummer (1-99)"})
    count = clear_folder(folder_num)
    return {"status": "ok", "folder": f"{folder_num:02d}", "deleted": count}
