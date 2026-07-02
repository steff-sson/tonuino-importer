# TonUINO Importer

Web-App zum Importieren von Hörspielen für die TonUINO NFC-Musikbox.

## Tech-Stack

- FastAPI + Jinja2 + HTMX + Tailwind (automation-themes)
- Keine DB: Dateisystem + `.import.json` pro SD-Ordner
- Docker (Media-Stack, SWAG Reverse Proxy)

## Projekt-Struktur

```
app/
├── main.py          # FastAPI App + Router
├── config.py        # SOURCE_DIR, DEST_DIR, MAX_TRACKS
├── scanner.py       # Quell-Ordner scannen (natsort)
├── importer.py      # Tracks kopieren + umbenennen
├── overview.py      # SD-Ordner-Details aus Dateisystem
├── render.py        # Jinja2 Helper
├── rsync.py         # rsync-Wrapper für SD-Karten-Export
└── routers/
    ├── dashboard.py # GET / — Dashboard + SD-Übersicht + Tabellen-Daten
    ├── import_.py   # GET /import, POST /api/scan, POST /api/import/start
    └── sd.py        # GET /sd, GET /sd/{n}
templates/           # Jinja2 Templates
static/              # CSS (Tailwind Output)
```

## Wichtige Pfade

- `/browse/{path}` — File-Browser (HTMX lazy-load)
- `/api/scan` — Quelle scannen (POST, source als Form-Daten)
- `/api/scan-multiple` — Mehrere Quell-Ordner scannen (POST, JSON: `{paths: [...]}`)
- `/api/import/start` — Import starten (POST, JSON)
- `/api/import/split-start` — Split-Import starten (POST, JSON)
- `/api/import/progress/{id}` — SSE-Fortschritt
- `/api/sd/folders` — Alle 99 Ordner mit Belegungsstatus (GET)
- `/sd` — SD-Ordner-Übersicht (01-99)

## Neue Funktionen

- **scanner.py:** `scan_multiple_sources`, `collect_mp3s_from_paths`, `compute_split_chunks`
- **importer.py:** `run_split_import`
- **overview.py:** `get_populated_folders`, `get_free_folders`, `get_stats`

## Features

- **Multi-Source-Auswahl:** Checkboxen im File-Browser → mehrere Ordner als eine Quelle importieren
- **Auto-Split:** Quelle mit >255 Tracks automatisch auf mehrere Ordner verteilen (Episoden-Grenzen respektiert)
- **Overwrite:** Checkbox "Bestehenden Ordner überschreiben" löscht alte Tracks vor Import
- **Mobile-First:** Responsive Tabellen mit `overflow-x-auto`, `line-clamp-2`, 44px Touch-Targets

## Coding-Konventionen

- Python: venv, keine globalen pip-Installs
- HTMX: `hx-get`, `hx-post`, `hx-swap="innerHTML"`, `hx-target`
- Tailwind: Klassen aus automation-themes, keine inline styles
- SSE: `StreamingResponse` mit `text/event-stream`

## Deployment

- **Media-Stack:** `/home/stef/docker/media/docker-compose.yml`
- **SWAG:** `tonuino.weitzelnet.com` (Authelia-geschützt)
- **Kein Port-Exposure** (außer Dev)
- **Volumes:**
  - `Hoerspiele:/source:ro` (NFS-Volume)
  - `./tonuino/sd-card-complete:/app/sd-card-complete`

## Features (entfernt)

- SD-Card-Download (ZIP + FSA) — wurde entfernt, User löst extern
- **SD-Ordner-Übersicht:** Im Dashboard integriert (`#sd`), zeigt Tabelle belegter Ordner (Nr. | Hörspiel | Tracks). `/sd` redirected auf `/#sd`.
