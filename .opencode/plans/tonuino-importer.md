# TonUINO Importer — Architecture Plan

> **Status:** PROPOSE | **Author:** @oracle | **Date:** 2026-06-19
> **Target:** @fixer — ready for BUILD phase

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (HTMX + automation-themes Tailwind)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │Dashboard │ │ Series   │ │ Import   │ │ SD Overview  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP/SSE
┌──────────────────────▼──────────────────────────────────────┐
│  FastAPI (port 8501)                                        │
│  ┌──────────┐ ┌───────────┐ ┌───────────┐ ┌──────────┐    │
│  │scanner.py│ │importer.py│ │ rsync.py  │ │ routers/ │    │
│  └────┬─────┘ └─────┬─────┘ └─────┬─────┘ └────┬─────┘    │
│       │             │             │             │           │
│  ┌────▼─────────────▼─────────────▼─────────────▼────┐      │
│  │              SQLite (aiosqlite)                   │      │
│  │  series │ episodes │ tracks │ sd_folders          │      │
│  └───────────────────────────────────────────────────┘      │
└──────────────────────┬──────────────────────────────────────┘
                       │ Filesystem
┌──────────────────────▼──────────────────────────────────────┐
│  /srv/nfs/hoerspiele/  (SOURCE, read-only)                  │
│  sd-card-complete/     (DEST, local staging)                │
│  /media/usb/SD-CARD/   (SD mount, optional rsync target)    │
└─────────────────────────────────────────────────────────────┘
```

**Flow:** User browses to web UI → selects source series → sees preview → picks SD folder → triggers import → FastAPI copies/renames files while streaming progress via SSE → DB updated → Von-Bis ranges displayed for NFC card programming.

**Auth:** SWAG (nginx reverse proxy) + Authelia in front. App itself has no auth — trusted internal network.

---

## 2. Data Model

### 2.1 Tables

```sql
-- One record per imported series (e.g., "Spidey", "Ritter Rost")
CREATE TABLE series (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                    -- "Spidey und seine Super-Freunde"
    source_path TEXT NOT NULL,                    -- "/srv/nfs/hoerspiele/Spidey/"
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One record per episode within a series
CREATE TABLE episodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id       INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,                -- "Folge 1 - Der Spinnen-Biss"
    source_folder   TEXT NOT NULL,                -- "Folge-1-Spinnenbiss"
    episode_number  INTEGER NOT NULL,             -- 1 (chronological order)
    track_count     INTEGER NOT NULL DEFAULT 0,   -- denormalized for fast queries
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One record per MP3 file
CREATE TABLE tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id      INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    sd_folder_id    INTEGER REFERENCES sd_folders(id) ON DELETE SET NULL,
    track_number    INTEGER,                      -- global number within SD folder (001-255)
    source_filename TEXT NOT NULL,                -- "001 - Kapitel 01.mp3"
    source_path     TEXT NOT NULL,                -- full source path
    sd_filename     TEXT,                         -- "001_Spidey_Folge01_Kapitel01.mp3"
    sd_path         TEXT,                         -- full dest path after copy
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- SD card folders (01-99)
CREATE TABLE sd_folders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_number   INTEGER NOT NULL UNIQUE,      -- 1-99
    name            TEXT,                          -- optional display name
    description     TEXT,                          -- "Spidey Folgen 1-12"
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 2.2 Relationships

```
series 1──N episodes 1──N tracks N──1 sd_folders
```

- **One series** has many **episodes** (e.g., Spidey has 12 episodes)
- **One episode** has many **tracks** (e.g., Episode 1 has 7 chapters)
- **One SD folder** contains many **tracks** (from one or more episodes of the same series)
- Tracks within an SD folder are numbered globally (`track_number` 001–255)

### 2.3 Example Data

```text
Series: "Spidey und seine Super-Freunde" (id=1)
├── Episode 1: "Folge 1 - Der Spinnen-Biss" (id=10, episode_number=1)
│   ├── Track 001 (sd_folder=05, track_number=1)
│   ├── Track 002 (sd_folder=05, track_number=2)
│   └── ...
├── Episode 2: "Folge 2 - Electro schlägt zu" (id=11, episode_number=2)
│   ├── Track 008 (sd_folder=05, track_number=8)
│   └── ...
└── ...
SD Folder 05: folder_number=5, name="05", description="Spidey Folgen 1-12"

Von-Bis for NFC cards:
  Episode 1: Track 001–007
  Episode 2: Track 008–014
  Episode 3: Track 015–021
  ...
```

### 2.4 Design Decisions

| Decision | Rationale |
|----------|-----------|
| `track.sd_folder_id` on tracks, not a junction table | Each track is in exactly one SD folder. Simpler queries. |
| `episode.track_count` denormalized | Avoids COUNT(*) joins on every series list view. |
| `episode.episode_number` explicit | Source folder names may not sort cleanly. Explicit ordering. |
| SQLite (not PostgreSQL) | Zero-config, file-based, survives Docker restarts. Volume-mount the DB file. |
| No `sd_folder_tracks` junction table | Direct FK is sufficient. Re-import on same series updates existing records. |

---

## 3. Import Workflow

### 3.1 Step-by-Step

```
USER ACTION                  SYSTEM ACTION
───────────                  ─────────────
1. Open /import             → Show import form
2. Enter SOURCE path         → POST /api/scan
   e.g. /srv/nfs/hoerspiele/
        Spidey/
                             → scanner.py inspects directory:
                               - Extract series name (dirname)
                               - List subdirs → episodes
                               - Sort subdirs alphabetically
                               - Count *.mp3 per subdir
                               - Return preview JSON:
                                 { series: "Spidey",
                                   episodes: [{name: "Folge 1...",
                                     source: "...", tracks: 7}, ...],
                                   total_tracks: 87,
                                   estimated_folders: 1 }
3. UI shows preview           → Preview partial loaded via HTMX
   (12 episodes, 87 tracks,
    fits in 1 SD folder)
4. User selects DEST folder   → Dropdown of SD folders (01-99)
   or accepts auto-suggestion   Auto-suggests next free folder
5. User clicks "Importieren"  → POST /api/import/start
                                { source: "/srv/nfs/hoerspiele/Spidey/",
                                  sd_folder: 5 }

                             → importer.py (async task):
                               a) Create/update series record
                               b) Create/update episode records
                               c) For each episode (sorted):
                                  - For each track (sorted by filename):
                                    * Assign global track_number (001-255)
                                    * Validate: track_number <= 255
                                    * Build sd_filename:
                                      {track_number:03d}_{series}_{episode}_{chapter}.mp3
                                    * Copy file: shutil.copy2()
                                    * Create track record in DB
                                    * Yield progress event (SSE)
                               d) Update episode.track_count
                               e) Return Von-Bis summary

6. Progress streamed           → SSE: GET /api/import/progress/{task_id}
   Progress bar updates          Events: {event: "progress", data: {current:45, total:87, file:"..."},
   via HTMX                      event: "complete", data: {episodes:[{title, track_start, track_end},...]}}

7. Done → Show Von-Bis         → UI renders episode list with track ranges
   for NFC programming
```

### 3.2 Scanner Logic (scanner.py)

```python
def scan_source(source_path: Path) -> ScanResult:
    """
    1. Verify path exists and is readable
    2. Series name = source_path.name
    3. Episodes = subdirectories containing *.mp3 files
    4. Sort episodes by name (assumes chronological naming like "Folge 1...", "Folge 2...")
       - Natural sort: "Folge 2" before "Folge 10"
    5. Tracks per episode = sorted(glob("*.mp3"))
    6. Return preview data
    """
```

### 3.3 Edge Cases

| Case | Behavior |
|------|----------|
| **SOURCE not found** | 404 error, user-friendly message |
| **SOURCE no MP3s** | Warn: "Keine MP3-Dateien gefunden" |
| **Duplicate series** | Detect by `source_path`. Offer: "Re-import" (update) or "Skip" |
| **>255 tracks in one folder** | **Block import.** Show error: "87 Tracks benötigt, aber Ordner 05 hat bereits 200 Tracks → 287 > 255. Verwende zwei Ordner oder teile die Serie." |
| **SD folder already has files** | If re-importing same series: replace tracks for that series, keep others. If different series: warn, prevent (SD folder = one series only by convention). |
| **Missing files during copy** | Log warning, skip track, continue. Report skipped tracks at end. |
| **Unicode in filenames** | Normalize to NFC (macOS compat). Replace `/` `\` `:` with `-`. Keep Umlaute (äöü) as-is (FAT32 safe). |
| **SD card not mounted** | rsync fails gracefully. GET /api/sd/status checks mount point. |
| **Interrupted import** | Tracks are written sequentially. On restart, detect incomplete imports (episodes with track_count=0 or tracks missing sd_filename). Offer "Resume" or "Clean up". |
| **Concurrent imports** | Single-worker task queue (asyncio.Queue). Second import queued, shown as "pending". |

### 3.4 File Naming Convention

```
{track_number:03d}_{series_short}_{episode_short}_{chapter}.mp3

Examples:
001_Spidey_Folge01_Der-Spinnen-Biss.mp3
002_Spidey_Folge01_Die-Jagd-beginnt.mp3
...
087_Spidey_Folge12_Das-Finale.mp3
```

- `series_short`: First word of series name, no spaces (e.g., "Spidey", "RitterRost")
- `episode_short`: "Folge" + zero-padded number (e.g., "Folge01")
- `chapter`: Original chapter name, spaces → hyphens, special chars stripped
- Max filename length: ~100 chars (FAT32 limit is 255, but keep readable)

---

## 4. API Design

### 4.1 Page Routes (HTML)

| Method | Path | Description | Template |
|--------|------|-------------|----------|
| GET | `/` | Dashboard: stats cards + quick actions | `dashboard.html` |
| GET | `/series` | Series list: table with counts | `series_list.html` |
| GET | `/series/{id}` | Series detail: episodes + von-bis | `series_detail.html` |
| GET | `/sd` | SD folder grid: which folder has what | `sd.html` |
| GET | `/import` | Import form + preview area | `import.html` |

### 4.2 API Routes (JSON / SSE)

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| POST | `/api/scan` | Scan source directory | `{source: "/srv/nfs/..."}` | `{series_name, episodes: [...], total_tracks, estimated_folders}` |
| POST | `/api/import/start` | Start import | `{source: "...", sd_folder: 5}` | `{task_id: "uuid"}` |
| GET | `/api/import/progress/{task_id}` | SSE progress stream | — | `event: progress` / `event: complete` / `event: error` |
| DELETE | `/api/import/cancel/{task_id}` | Cancel running import | — | `{status: "cancelled"}` |
| GET | `/api/sd/status` | Check SD card mount | — | `{mounted: true, path: "/media/usb/SD-CARD", free_gb: 12.3}` |
| POST | `/api/sd/sync` | rsync dest → SD card | `{sd_path: "/media/usb/SD-CARD"}` | `{task_id: "uuid"}` (SSE for progress) |
| GET | `/api/sd/folders` | List SD folders with content | — | `[{folder_number: 1, ...}, ...]` |

### 4.3 SSE Event Format

```
event: progress
data: {"current": 45, "total": 87, "file": "045_Spidey_Folge06_Kapitel03.mp3", "percent": 51.7}

event: complete
data: {"series_name": "Spidey", "sd_folder": 5, "total_tracks": 87, "episodes": [{"title": "Folge 1...", "track_start": 1, "track_end": 7}, ...]}

event: error
data: {"message": "SD folder 05 would exceed 255 track limit (current: 200, needed: 87)"}
```

### 4.4 Dashboard Stats API

```
GET /api/stats
→ {
    "series_count": 12,
    "episode_count": 87,
    "track_count": 1240,
    "sd_folders_used": 8,
    "sd_folders_total": 99,
    "total_size_gb": 8.3,
    "last_import": "2026-06-19T14:30:00"
  }
```

---

## 5. Web UI

### 5.1 Pages

#### Dashboard (`/`)
```
┌──────────────────────────────────────────────┐
│  TonUINO Importer                [Importieren]│
├──────────────────────────────────────────────┤
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ │
│  │12      │ │87      │ │1.240   │ │8/99    │ │
│  │Serien  │ │Folgen  │ │Tracks  │ │Ordner  │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ │
│                                              │
│  Letzter Import: Spidey → Ordner 05 (87 Tr.) │
│  [Serien anzeigen]  [SD-Ordner anzeigen]     │
└──────────────────────────────────────────────┘
```

#### Import (`/import`)
```
┌──────────────────────────────────────────────┐
│  Import                                     │
├──────────────────────────────────────────────┤
│  Quell-Pfad: [/srv/nfs/hoerspiele/Spidey/  ] │
│  [Scannen]                                   │
│                                              │
│  ┌─ Vorschau (HTMX partial) ──────────────┐  │
│  │ Serie: Spidey und seine Super-Freunde  │  │
│  │ 12 Folgen, 87 Tracks, ~320 MB          │  │
│  │ Passt in 1 SD-Ordner                   │  │
│  │                                         │  │
│  │ Ziel-Ordner: [05 ▼] (nächster frei)    │  │
│  │ [Import starten]                        │  │
│  └─────────────────────────────────────────┘  │
│                                              │
│  ┌─ Fortschritt (SSE, HTMX) ──────────────┐  │
│  │ ████████████░░░░░░░░ 52% (45/87)       │  │
│  │ Datei: 045_Spidey_Folge06_...           │  │
│  └─────────────────────────────────────────┘  │
│                                              │
│  ┌─ Ergebnis (nach Import) ───────────────┐  │
│  │ ✅ Import abgeschlossen                │  │
│  │ Von-Bis für NFC-Karten:                │  │
│  │ Folge 1: Track 001–007                 │  │
│  │ Folge 2: Track 008–014                 │  │
│  │ ...                                     │  │
│  │ [SD-Karte synchronisieren]             │  │
│  └─────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

### 5.2 HTMX Patterns

| Pattern | Usage |
|---------|-------|
| `hx-post` | Scan trigger, import start |
| `hx-get` | Load preview partial, load SD status |
| `hx-swap="outerHTML"` | Replace preview with result |
| `hx-ext="sse"` | SSE progress bar (uses `hx-sse` attribute) |
| `hx-target` | Target the progress container |
| `hx-trigger="load"` | Auto-refresh dashboard stats |

### 5.3 Base Template

```html
<!-- templates/base.html -->
{% extends "automation-themes/templates/base.html" %}
{% block head_extra %}
<link rel="stylesheet" href="/static/css/output.css">
{% endblock %}
```

### 5.4 Navigation

```
[Dashboard] [Serien] [Import] [SD-Ordner]
```

Active page highlighted via `{% block nav %}`. No JavaScript framework — HTMX only.

---

## 6. Docker Setup

### 6.1 Dockerfile

```dockerfile
# Build stage: Tailwind CSS via automation-themes
FROM node:20-alpine AS build
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY tailwind.config.js .
COPY static/css/ ./static/css/
COPY templates/ ./templates/
# Merge automation-themes templates
RUN mkdir -p templates/automation-themes/templates && \
    cp -rn node_modules/@steff-sson/automation-themes/templates/* \
       templates/automation-themes/templates/ || true
RUN npx @tailwindcss/cli -i ./static/css/style.css -o ./static/css/output.css --minify

# Runtime stage
FROM python:3.12-slim
WORKDIR /app
COPY --from=build /build/static/css/output.css ./static/css/output.css
COPY . .
COPY --from=build /build/templates/ ./templates/
RUN python3 -m venv .venv && .venv/bin/pip install --no-cache-dir .
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8501
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8501"]
```

### 6.2 docker-compose.yml

```yaml
---
services:
  tonuino-importer:
    build: .
    container_name: tonuino-importer
    environment:
      - TZ=Europe/Berlin
      - CONFIG_PATH=/home/appuser/.config/automation/config.env
    volumes:
      - ./data:/app/data                           # SQLite DB
      - /srv/nfs/hoerspiele:/source:ro             # Source audiobooks (read-only)
      - ./sd-card-complete:/app/sd-card-complete   # Staging destination
      - ~/.config/automation:/home/appuser/.config/automation:ro  # Config
    ports:
      - "8501:8501"
    restart: unless-stopped
```

### 6.3 Volume Strategy

| Volume | Purpose | Persistence |
|--------|---------|-------------|
| `./data:/app/data` | SQLite database file | Must persist across rebuilds |
| `/srv/nfs/hoerspiele:/source:ro` | Source MP3 files | Read-only, external NFS |
| `./sd-card-complete:/app/sd-card-complete` | Staging area before rsync | Persist (the built SD card image) |

### 6.4 Port Assignment

| Service | Port | Reason |
|---------|------|--------|
| livestream-recorder | 8500 | Existing |
| **tonuino-importer** | **8501** | Next available in automation range |

SWAG reverse proxy: `tonuino.weitzel.app` → `tonuino-importer:8501` (container name as upstream in `net_cloud`).

### 6.5 Cloud Stack Integration

Add to `/home/stef/docker/cloud/docker-compose.yml`:

```yaml
  tonuino-importer:
    build: /home/stef/github/tonuino-importer
    container_name: tonuino-importer
    environment:
      - TZ=Europe/Berlin
    volumes:
      - ./data/tonuino-importer:/app/data
      - /srv/nfs/hoerspiele:/source:ro
      - /home/stef/github/tonuino-importer/sd-card-complete:/app/sd-card-complete
    networks:
      - net_cloud
    restart: unless-stopped
    # No ports exposed — only accessible via SWAG reverse proxy
```

---

## 7. Project Structure

```
tonuino-importer/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, SSE endpoint
│   ├── config.py            # Settings (paths, limits, env vars)
│   ├── database.py          # SQLAlchemy async engine + session
│   ├── models.py            # ORM models (Series, Episode, Track, SDFolder)
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── scanner.py           # Source directory scanner
│   ├── importer.py          # Core import logic (copy + rename + DB)
│   ├── rsync.py             # SD card sync via rsync
│   └── routers/
│       ├── __init__.py
│       ├── dashboard.py     # GET /  (stats + dashboard)
│       ├── series.py        # GET /series, GET /series/{id}
│       ├── import_.py       # GET /import, POST /api/scan, POST /api/import/start
│       └── sd.py            # GET /sd, GET /api/sd/status, POST /api/sd/sync
├── templates/
│   ├── base.html            # extends automation-themes/base.html
│   ├── dashboard.html       # Stats cards + quick links
│   ├── series_list.html     # Table of all series
│   ├── series_detail.html   # Episodes + Von-Bis table
│   ├── import.html          # Import form
│   ├── sd.html              # SD folder grid
│   └── partials/
│       ├── progress.html    # SSE progress bar (HTMX)
│       ├── preview.html     # Scan preview (loaded via hx-post)
│       └── result.html      # Import result with Von-Bis
├── static/
│   └── css/
│       └── style.css        # @import "@steff-sson/automation-themes/css/style.css";
├── data/                    # SQLite DB (gitignored, volume-mounted)
├── sd-card-complete/        # Staging destination (gitignored, volume-mounted)
├── Dockerfile
├── docker-compose.yml
├── tailwind.config.js
├── package.json
├── package-lock.json
├── pyproject.toml           # or setup.py/requirements.txt
├── .dockerignore
├── .gitignore
└── README.md
```

### 7.1 Module Responsibilities

| Module | Responsibility | Key Functions |
|--------|---------------|---------------|
| `scanner.py` | Inspect source filesystem | `scan_source(path) → ScanResult` |
| `importer.py` | Core import logic | `run_import(source, sd_folder, progress_callback) → ImportResult` |
| `rsync.py` | SD card synchronization | `sync_to_sd(sd_path, progress_callback)`, `check_sd_status() → SDStatus` |
| `database.py` | DB connection management | `init_db()`, `get_db()`, `get_sync_engine()` |
| `models.py` | SQLAlchemy ORM models | `Series`, `Episode`, `Track`, `SDFolder` |
| `config.py` | App configuration | `SOURCE_ROOT`, `DEST_DIR`, `SD_MOUNT_PATH`, `MAX_TRACKS=255` |

### 7.2 Key Dependencies

```text
# pyproject.toml / requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy[asyncio]>=2.0.30
aiosqlite>=0.20.0
jinja2>=3.1.4
python-multipart>=0.0.9         # for form parsing
httpx>=0.27.0                   # for testing
natsort>=8.4.0                  # natural sorting of episode names
```

### 7.3 Style Convention

- Single-file modules (no `__init__.py` logic, flat structure under `app/`)
- `render()` helper like livestream-recorder (Jinja2 `FileSystemLoader`)
- SSE via `fastapi.responses.StreamingResponse` with `text/event-stream`
- Background tasks via `asyncio.create_task()` + in-memory task dict
- No Celery, no Redis — single-process async is sufficient

---

## 8. MVP Scope

### V1 (MVP — first working version)

- [x] Source scanning (POST /api/scan)
- [x] Import with copy+rename (POST /api/import/start)
- [x] SSE progress streaming
- [x] von-bis display after import
- [x] SQLite database with all 4 tables
- [x] Dashboard with stats
- [x] Series list + detail views
- [x] SD folder overview
- [x] Docker build + cloud stack integration
- [x] automation-themes styling (Tailwind)
- [x] Track limit enforcement (≤255)

### V2 (Nice to have)

- [ ] Duplicate detection with merge/skip options
- [ ] Resume interrupted imports
- [ ] SD card rsync with progress (currently just UI trigger, rsync can be manual)
- [ ] Bulk import (select multiple series)
- [ ] Track reordering (drag & drop)
- [ ] NFC tag export (JSON for NFC tools)
- [ ] Album art display (cover.jpg extraction)
- [ ] Audio preview (HTML5 audio player)
- [ ] Search/filter series

### V3 (Future)

- [ ] Admin panel (edit metadata, reassign tracks)
- [ ] Export to physical SD card (one-click)
- [ ] Backup/restore DB
- [ ] Multi-user support (if ever needed)

---

## 9. Implementation Notes for @fixer

### 9.1 Critical Path

1. **models.py + database.py** — DB layer first (can be tested standalone)
2. **scanner.py** — Filesystem inspection (testable with real paths)
3. **importer.py** — Core logic (depends on 1+2)
4. **main.py + routers** — Web layer (depends on 1-3)
5. **templates** — HTML (depends on 4)
6. **Docker** — Containerization (depends on all)

### 9.2 Test Strategy

- **models/database:** `pytest` with in-memory SQLite
- **scanner:** Test with temp directories containing mock MP3 files
- **importer:** Test copy+rename with temp dirs, verify DB state
- **API:** `httpx.AsyncClient` + FastAPI `TestClient` (or `httpx` ASGI transport)

### 9.3 Gotchas

- **`natsort`** for episode ordering — alphabetical sort gets "Folge 10" before "Folge 2"
- **FAT32 filename safety:** Strip `<>:"/\|?*`, replace spaces with hyphens
- **SSE connection:** Keep-alive with `: comments` every 15s to prevent proxy timeout
- **Async SQLAlchemy:** Use `async with get_db() as db:` pattern, not sync session
- **Jinja2 + automation-themes:** Copy theme templates in Dockerfile (same pattern as livestream-recorder)
- **Port 8501:** Must not conflict with livestream-recorder (8500) or other services

### 9.4 Configuration

```bash
# ~/.config/automation/config.env
TONUINO_SOURCE_DIR=/srv/nfs/hoerspiele
TONUINO_DEST_DIR=/app/sd-card-complete
TONUINO_SD_MOUNT=/media/usb/SD-CARD
TONUINO_MAX_TRACKS=255
TONUINO_MAX_FOLDERS=99
```

Read via `os.environ.get()` with sensible defaults in `config.py`.

---

## 10. SD Card Sync Flow (rsync)

```
┌─────────────┐     rsync -av --progress     ┌──────────────┐
│ sd-card-     │ ────────────────────────────→│ SD-Karte      │
│ complete/    │                               │ (FAT32)       │
│ 05/*.mp3     │                               │ 05/*.mp3      │
└─────────────┘                               └──────────────┘

1. User inserts SD card → mounted at /media/usb/SD-CARD
2. GET /api/sd/status → {mounted: true, free_gb: 7.2}
3. POST /api/sd/sync → rsync -av --delete /app/sd-card-complete/ /media/usb/SD-CARD/
4. Progress via SSE (parse rsync --info=progress2 output)
5. Done → "SD-Karte kann entfernt werden"
```

rsync preserves the `01/`, `02/`, ... folder structure exactly as staged.

Command: `rsync -av --delete /app/sd-card-complete/ /media/usb/SD-CARD/`
- `-a`: archive mode (preserves permissions, timestamps)
- `-v`: verbose (parsed for progress)
- `--delete`: removes files on SD that are not in staging
