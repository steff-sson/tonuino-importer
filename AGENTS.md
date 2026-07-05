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
- `/api/sd/{n}/clear` — Ordner-Inhalt löschen (POST)
- `/sd` — SD-Ordner-Übersicht (01-99)
- `.github/workflows/docker-build.yml` — CI/CD Pipeline (Docker-Image Build + Push)

## Neue Funktionen

- **scanner.py:** `find_mp3s`, `_scan_single`, `_scan_with_subdirs`, `_scan_flat`, `_get_visible_subdirs`, `scan_multiple_sources`, `collect_mp3s_from_paths`, `compute_split_chunks`
- **importer.py:** `run_split_import`, `_group_mp3s_by_parent`
- **overview.py:** `get_populated_folders`, `get_free_folders`, `get_stats`, `clear_folder`
- **Entfernt:** `_normalize_episode`, `_extract_episode_title` — ersetzt durch Dateisystem-basierte Logik

## Features

- **Dateisystem-basierte Episoden-Erkennung:** Unterordner = Episoden (mit von‑bis), flache Ordner = ein Block (kein von‑bis). Kein Regex.
- **Multi-Source-Auswahl:** Checkboxen im File-Browser → mehrere Ordner als eine Quelle importieren
- **Auto-Split:** Quelle mit >255 Tracks automatisch auf mehrere Ordner verteilen (Episoden-Grenzen respektiert)
- **Split-Ordnerwahl:** User wählt Zielordner pro Chunk via Dropdown (statt Auto-Zuweisung)
- **Ordner leeren:** Button in SD-Detailansicht zum Löschen aller Tracks eines Ordners
- **Overwrite:** Checkbox "Bestehenden Ordner überschreiben" löscht alte Tracks vor Import
- **Mobile-First:** Responsive Tabellen mit `overflow-x-auto`, `line-clamp-3`, 44px Touch-Targets

## Coding-Konventionen

- Python: venv, keine globalen pip-Installs
- HTMX: `hx-get`, `hx-post`, `hx-swap="innerHTML"`, `hx-target`
- Tailwind: Klassen aus automation-themes, keine inline styles
- SSE: `StreamingResponse` mit `text/event-stream`

## Scripts

- `scripts/cleanup-eadir.sh` — Löscht alle @eaDir-Metadaten-Ordner rekursiv (Synology NAS). `--path`-Flag erforderlich.
- `scripts/restructure-hoerspiele.sh` — Flattet mehrteilige Ordner + splittet lange Einzel-MP3s in 120s-Chunks (ffmpeg). `--path` + `--dry-run`.

## Deployment

- **Media-Stack:** `/home/stef/docker/media/docker-compose.yml`
- **SWAG:** `<your-domain>` (Authelia-geschützt)
- **Kein Port-Exposure** (außer Dev)
- **Volumes:**
  - `Hoerspiele:/source:ro` (NFS-Volume)
  - `./tonuino/sd-card-complete:/app/sd-card-complete`
- **CI/CD:** GitHub Actions (`.github/workflows/docker-build.yml`) — Push auf `master` → Build + Push nach `ghcr.io/steff-sson/tonuino-importer` (Tags: `latest`, `sha-<commit>`, `master`)
- **Registry:** `ghcr.io/steff-sson/tonuino-importer` (public, anonym pullbar)
- **Server:** Media-Stack `docker-compose.yml` nutzt `image: ghcr.io/steff-sson/tonuino-importer:latest`
- **Auto-Update:** Watchtower (optional, noch nicht installiert)

## Features (entfernt)

- SD-Card-Download (ZIP + FSA) — wurde entfernt, User löst extern
- SD-Sync (`rsync`/`POST /api/sync`) — wurde entfernt, User synchronisiert extern
- **SD-Ordner-Übersicht:** Im Dashboard integriert (`#sd`), zeigt Tabelle belegter Ordner (Nr. | Hörspiel | Tracks). `/sd` redirected auf `/#sd`.
