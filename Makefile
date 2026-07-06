.PHONY: help setup up down dev test lint health seed migrate clean

help:
	@echo "FlightDeck - common commands"
	@echo "  make setup    - install dependencies (uv sync)"
	@echo "  make up       - start postgres + redis"
	@echo "  make down     - stop postgres + redis"
	@echo "  make dev      - run API server with reload"
	@echo "  make migrate  - apply DB migrations"
	@echo "  make seed     - seed airports + transfer partners"
	@echo "  make health   - check API + DB + Redis + API keys"
	@echo "  make test     - run pytest"
	@echo "  make lint     - run ruff"

setup:
	uv sync

up:
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@until docker compose ps postgres | grep -q "healthy"; do sleep 1; done
	@until docker compose ps redis | grep -q "healthy"; do sleep 1; done
	@echo "Services ready."

down:
	docker compose down

dev:
	uv run uvicorn app.main:app --reload --port 8002

migrate:
	uv run flightdeck db init

seed:
	uv run flightdeck db seed

health:
	uv run flightdeck health

test:
	uv run pytest -v

lint:
	uv run ruff check app tests

clean:
	docker compose down -v
