# TonUINO Importer — Architecture Plan

> **Status:** PROPOSE | **Author:** @oracle | **Date:** 2026-06-20
> **Target:** @fixer — ready for BUILD phase

---

## 1. Architecture Overview

```
Browser (HTMX + Tailwind) ──HTTP──→ FastAPI (port 8501)
                                    │
  ┌─ scanner.py  ──→ SOURCE /srv/nfs/hoerspiele/ (read-only)
  ├─ importer.py ──→ DEST   sd-card-complete/      (staging)
  ├─ overview.py ──→ scan   sd-card-complete/**/*.mp3 + .import.json
  └─ rsync.py    ──→ sync   DEST → /media/usb/SD-CARD/

Single Source of Truth: DEST filesystem + .import.json pro Ordner.
Übersicht = ls sd-card-complete/05/*.mp3 + .import.json lesen.
```

**Auth:** SWAG + Authelia davor. Port 8501 (nächster nach livestream-recorder 8500).

---

## 2. Core Concepts

### 2.1 Drei Modi

| Modus | Trigger | Verhalten |
|-------|---------|-----------|
| Import | "Importieren" | SOURCE → umbenennen → DEST |
| Import + Sync | "Importieren" + ☑ "SD syncen" | Import, dann rsync DEST → SD |
| Nur Sync | "Nur syncen"-Button | rsync DEST → SD (kein Import) |

### 2.2 Dateinamen-Konvention

```
SOURCE:  001 - Folge - 01 - Der Spinnen-Biss.mp3
         (oder ohne führende Nummer: Folge 01 - Der Spinnen-Biss.mp3)

DEST:    {global:03d} - {rest}.mp3
         005 - Folge - 01 - Der Spinnen-Biss.mp3
         006 - Folge - 01 - Die Jagd beginnt.mp3
         007 - Folge - 02 - Electro schlägt zu.mp3
```

**Logik:** Führende Nummer im SOURCE-Namen via Regex `^\d{1,4}\s*[-–]\s*` strippen, globale Track-Nummer (001–255) davorsetzen. `rest` = alles nach der alten Nummer.

```python
LEADING_NUM = re.compile(r'^\d{1,4}\s*[-–]\s*')
def build_dest_name(src_stem: str, global_num: int) -> str:
    rest = LEADING_NUM.sub('', src_stem)
    return f"{global_num:03d} - {rest}.mp3"
```

### 2.3 ≤255 Track-Limit

Pro Ordner max 255 MP3s (TonUINO-Hardlimit). Überschreitung → Fehler, kein Auto-Split. User verteilt manuell.

### 2.4 Single Source of Truth

| Frage | Quelle |
|-------|--------|
| Was ist in Ordner 05? | `ls sd-card-complete/05/*.mp3` |
| Von-Bis pro Folge? | `sd-card-complete/05/.import.json` (geschrieben bei Import) |

---

## 3. Import-Workflow

```
USER                            SYSTEM
────                            ──────
1. /import → Formular           GET  /import

2. Pfad eingeben, [Scannen]     POST /api/scan
   /srv/nfs/hoerspiele/Spidey/  → scanner.py: alle *.mp3 rekursiv,
                                  natsort, zählen, preview:
                                  {series, tracks:[{src, dest_preview}],
                                   total, estimated_folders}

3. Vorschau (HTMX partial)      Limit-Check: neu + vorhanden ≤ 255?
   "12 Folgen, 87 Tracks"
   DEST-Vorschau erste 3 Namen

4. Nutzer wählt:                Dropdown 01-99 + ☑ Sync-Checkbox
   - Ziel-Ordner (05)
   - Modus

5. [Importieren]                POST /api/import/start
                                → importer.py:
                                  a) next_free = len(glob("*.mp3")) + 1
                                  b) für jeden Track (natsort):
                                     copy2(src, dest/{next_free:03d} - {rest})
                                     SSE progress
                                     next_free++
                                   c) .import.json schreiben
                                   d) wenn sync_after: rsync starten

6. Fortschritt                  SSE: GET /api/import/progress/{task_id}
   Progress-Bar (HTMX sse)      event: progress/complete/error

7. Ergebnis: Von-Bis-Tabelle
   Folge 01: 001–007
   Folge 02: 008–014
```

### 3.1 Edge Cases

| Case | Behavior |
|------|----------|
| SOURCE nicht lesbar | 404 + "Pfad nicht gefunden" |
| Keine MP3s | Warnung, leere Vorschau |
| ∑(existing + new) > 255 | **Block.** Fehlermeldung mit Zahlen |
| Ziel-Ordner leer | next_free = 1 |
| Ziel-Ordner hat Dateien | next_free = max_bestehend + 1 (anhängen) |
| Unicode/ Sonderzeichen | NFC-normalisieren, `< > : " / \ | ? *` → `-` |
| SD nicht gemountet (Sync) | rsync-Fehler → Meldung im UI |

---

## 4. .import.json (pro Ordner)

Nach jedem Import in `sd-card-complete/{folder}/.import.json`:

```json
{
  "series": "Spidey und seine Super-Freunde",
  "imported_at": "2026-06-20T14:30:00",
  "source_path": "/srv/nfs/hoerspiele/Spidey/",
  "total_tracks": 87,
  "episodes": [
    {"title": "Folge 01 - Der Spinnen-Biss", "track_start": 1, "track_end": 7},
    {"title": "Folge 02 - Electro schlägt zu", "track_start": 8, "track_end": 14}
  ]
}
```

Übersichtsseite liest `.import.json` für zuverlässige Von-Bis-Daten. Ohne diese Datei: Fallback auf reines Datei-Listing (ohne Gruppierung).

---

## 5. API Design

### 5.1 Routes

| Method | Path | Response | Beschreibung |
|--------|------|----------|-------------|
| GET | `/` | HTML | Dashboard: Ordner, Tracks, Größe (aus Dateisystem) |
| GET | `/import` | HTML | Import-Formular |
| GET | `/sd` | HTML | SD-Ordner-Grid (01-99, belegte markiert) |
| GET | `/sd/{n}` | HTML | Ordner-Detail: Trackliste + Von-Bis |
| POST | `/api/scan` | JSON | `{source}` → `{series, tracks, total, estimated_folders}` |
| POST | `/api/import/start` | JSON | `{source, sd_folder, sync_after}` → `{task_id}` |
| GET | `/api/import/progress/{id}` | SSE | `progress` / `complete` / `error` |
| POST | `/api/sync` | JSON | rsync DEST→SD → `{task_id}` (SSE wie Import) |
| GET | `/api/sd/status` | JSON | `{mounted, path, free_gb}` |
| GET | `/api/sd/{n}` | JSON | `{folder, tracks[], episodes[]}` |
| GET | `/api/stats` | JSON | `{folders_used, total_tracks, total_size_gb}` |

### 5.2 SSE Events

```
event: progress
data: {"current":45,"total":87,"file":"045 - Folge 06 - Kapitel 03.mp3","percent":51.7}

event: complete
data: {"series":"Spidey","sd_folder":5,"total_tracks":87,
       "episodes":[{"title":"Folge 01 - ...","track_start":1,"track_end":7}]}

event: error
data: {"message":"Ordner 05: 287 Tracks (vorhanden 200 + neu 87) > Limit 255"}
```

---

## 6. Web UI (Kompakt)

**Navigation:** [Dashboard] [Import] [SD-Ordner]

**/import Seite:**
- Eingabefeld SOURCE-Pfad + [Scannen]-Button
- Vorschau-Bereich (HTMX partial nach Scan): Serienname, Trackzahl, DEST-Namensvorschau (3 Beispiele), Limit-Check
- Ziel-Ordner-Dropdown (01-99) mit Anzeige "bereits X Tracks"
- ☑ "Nach Import auf SD-Karte synchronisieren"
- [Importieren]-Button + [Nur syncen]-Button
- Fortschrittsbalken (SSE via HTMX `hx-ext="sse"`)
- Ergebnis: Von-Bis-Tabelle + Link zu `/sd/{folder}`

**/sd Seite:** Grid 01-99, belegte Ordner hervorgehoben mit Track-Anzahl.

**/sd/{n} Seite:** Track-Liste (nummeriert) + Von-Bis-Gruppierung (aus `.import.json`).

**HTMX Patterns:** `hx-post` für Aktionen, `hx-target` + `hx-swap="outerHTML"` für Partials, `hx-ext="sse"` für Progress, `hx-trigger="load"` für Auto-Refresh.

---

## 7. Docker + Cloud-Stack

```yaml
# cloud/docker-compose.yml
tonuino-importer:
  build: /home/stef/github/tonuino-importer
  container_name: tonuino-importer
  environment:
    - TZ=Europe/Berlin
    - SOURCE_DIR=/source
    - DEST_DIR=/app/sd-card-complete
  volumes:
    - /srv/nfs/hoerspiele:/source:ro
    - /home/stef/github/tonuino-importer/sd-card-complete:/app/sd-card-complete
  networks: [net_cloud]
  restart: unless-stopped
```

SWAG: `tonuino.weitzel.app` → `tonuino-importer:8501`.

**rsync:** `rsync -av --delete /app/sd-card-complete/ /media/sd/` als `subprocess.run()`. Kein Progress-Parsing — nur "läuft" / "fertig" / "fehler".

**Dockerfile:** Zweistufig (node build für Tailwind → python:3.12-slim). Gleiches Muster wie livestream-recorder: automation-themes-Templates kopieren, Tailwind kompilieren, uvicorn starten.

---

## 8. Project Structure

```
tonuino-importer/
├── app/
│   ├── main.py              # FastAPI + SSE + lifespan
│   ├── config.py            # SOURCE_DIR, DEST_DIR, MAX_TRACKS=255
│   ├── scanner.py           # SOURCE → [TrackInfo] (rekursiv, natsort)
│   ├── importer.py          # copy+rename, .import.json, SSE-Events, Limit-Check
│   ├── overview.py          # DEST scannen, .import.json lesen, von-Bis
│   ├── rsync.py             # subprocess.run(["rsync", ...])
│   └── routers/
│       ├── dashboard.py     # GET /
│       ├── import_.py       # GET /import, POST /api/scan, POST /api/import/start
│       └── sd.py            # GET /sd, /sd/{n}, POST /api/sync
├── templates/
│   ├── base.html            # extends automation-themes
│   ├── dashboard.html
│   ├── import.html
│   ├── sd.html / sd_detail.html
│   └── partials/
│       ├── preview.html     # Scan-Vorschau
│       ├── progress.html    # SSE-Balken
│       └── result.html      # Von-Bis-Tabelle
├── static/css/style.css     # @import automation-themes
├── sd-card-complete/        # gitignored
├── Dockerfile / docker-compose.yml
├── tailwind.config.js / package.json / pyproject.toml
└── README.md
```

**Module:** Single-file, flach unter `app/`. `render()`-Helper wie livestream-recorder. SSE via `StreamingResponse(text/event-stream)`. Tasks via `asyncio.create_task()` + in-memory dict. Kein Celery/Redis.

**Dependencies:** `fastapi`, `uvicorn[standard]`, `jinja2`, `natsort`, `python-multipart`. Keine Datenbank-Abhängigkeiten.

---

## 9. MVP Scope

### ✅ Enthalten

| Feature |
|---------|
| SOURCE scannen → Vorschau mit DEST-Namensvorschau |
| Import: copy + rename mit globaler Nummerierung + `.import.json` |
| Drei Modi: Import / Import+Sync / Nur Sync |
| SSE-Fortschritt |
| Von-Bis-Anzeige (aus `.import.json`) |
| SD-Ordner-Übersicht + Detail (aus Dateisystem + `.import.json`) |
| ≤255 Limit → Fehler |
| Docker + Cloud-Stack + SWAG |
| automation-themes Styling |

### ❌ Nicht enthalten

rsync-Progress-Parsing, Resume, Duplicate Detection, Bulk Import, NFC-Export, Admin-Panel, Cover, Audio-Preview, Suche, Drag & Drop, Multi-User, SQLite/History.

---

## 10. Implementation Notes

**Critical Path:** scanner.py → importer.py → overview.py → rsync.py → routers → templates → Docker.

**Key Gotchas:**
- `natsort` für Track-Reihenfolge (nicht `sorted()`)
- FAT32-Safety: `< > : " / \ | ? *` → `-`, Umlaute behalten
- SSE-Keepalive: `: ping\n\n` alle 15s
- DEST-Dateinamen-Parsing: Regex `^(\d{3})\s*[-–]\s*(.+)$`
- `.import.json` immer nach Import schreiben — **einzige** Von-Bis-Quelle
- Port 8501 (8500 = livestream-recorder)

**Limit-Check (vor Import):**
```python
def check_limit(dest: Path, new_count: int, max_t=255):
    exist = len(list(dest.glob("*.mp3"))) if dest.exists() else 0
    if exist + new_count > max_t:
        raise TrackLimitError(f"{dest.name}: {exist}+{new_count}={exist+new_count} > {max_t}")
```
