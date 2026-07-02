# TonUINO Importer

Web-App zum Importieren von Hörspielen für die TonUINO NFC-Musikbox.

## Tech-Stack

- **Backend:** FastAPI + Jinja2 + HTMX
- **Frontend:** automation-themes (Tailwind CSS)
- **Daten:** Dateisystem + `.import.json` (keine DB)
- **Deployment:** Docker (Media-Stack, SWAG Reverse Proxy, kein Port-Exposure)

## MVP-Scope

- 2-Phasen-Flow: Quelle wählen → Import vorbereiten
- Scan & Import von Hörspielen mit Umbenennung
- SSE-Progress (Live-Statusanzeige)
- Von-Bis-Anzeige (aus `.import.json`)
- ≤255 Track-Limit
- File-Browser mit Breadcrumb + List-View

## Starten

```bash
# Dev
make install
make dev

# Docker (Media-Stack)
cd /home/stef/docker/media
docker compose up -d tonuino-importer
```

## Erreichbarkeit

- **Intern:** `http://<host-ip>:8501` (Port-Exposure)
- **Extern:** `https://<your-domain>` (SWAG + Authelia)

## Architektur-Pläne

- `.opencode/plans/tonuino-importer.md` — Hauptarchitektur
- `.opencode/plans/sd-card-download.md` — SD-Card-Download (entfernt)
- `.opencode/plans/media-stack-swag-sd-cleanup.md` — Media-Stack + SWAG
