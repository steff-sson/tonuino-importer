.PHONY: install dev css-build css-watch docker-build docker-up docker-down

install:
	python3 -m venv .venv
	.venv/bin/pip install -e .
	npm install

dev:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8501 --reload

css-build:
	npx @tailwindcss/cli -i static/css/style.css -o static/css/output.css --minify

css-watch:
	npx @tailwindcss/cli -i static/css/style.css -o static/css/output.css --watch

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down
