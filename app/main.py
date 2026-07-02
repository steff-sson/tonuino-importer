from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import DEST_DIR
from .routers import dashboard, import_, sd

BASE_DIR = Path(__file__).parent.parent


@asynccontextmanager
async def lifespan(app):
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="TonUINO Importer", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(dashboard.router)
app.include_router(import_.router)
app.include_router(sd.router)
