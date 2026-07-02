# Build stage: Tailwind CSS
FROM node:20-alpine AS build
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY tailwind.config.js .
COPY static/css/ ./static/css/
COPY templates/ ./templates/
RUN mkdir -p templates/automation-themes/templates && \
    cp -rn node_modules/@steff-sson/automation-themes/templates/* templates/automation-themes/templates/ || true
RUN npx @tailwindcss/cli -i ./static/css/style.css -o ./static/css/output.css --minify

# Runtime stage
FROM python:3.12-slim
WORKDIR /app
COPY --from=build /build/static/css/output.css ./static/css/output.css
COPY . .
COPY --from=build /build/templates/ ./templates/
RUN python3 -m venv .venv && .venv/bin/pip install --no-cache-dir .
RUN useradd -m -u 1000 appuser && mkdir -p /app/sd-card-complete && chown -R appuser:appuser /app
USER appuser
EXPOSE 8501
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8501"]
