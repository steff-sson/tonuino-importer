import asyncio
import subprocess
import os

from .config import DEST_DIR


SD_CARD_PATH = os.environ.get("SD_CARD_PATH", "/media/usb/SD-CARD")


async def run_rsync(task_id: str = "", progress_cb=None) -> dict:
    """Rsync DEST_DIR to SD card. Returns result dict."""
    if progress_cb:
        await progress_cb(current=0, total=1, file="rsync startet...")

    cmd = [
        "rsync", "-av", "--delete",
        str(DEST_DIR) + "/",
        SD_CARD_PATH + "/",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        msg = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"rsync fehlgeschlagen (rc={proc.returncode}): {msg}")

    if progress_cb:
        await progress_cb(current=1, total=1, file="rsync abgeschlossen")

    return {"status": "ok", "message": "Sync abgeschlossen"}
