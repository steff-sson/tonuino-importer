from fastapi import APIRouter, Request

from ..overview import get_populated_folders, get_stats
from ..render import render

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    stats = get_stats()
    folders = get_populated_folders()
    total_empty = 99 - len(folders)
    return render("dashboard.html", {
        "request": request,
        "stats": stats,
        "folders": folders,
        "total_empty": total_empty,
    })
