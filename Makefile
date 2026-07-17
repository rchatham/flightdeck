.PHONY: help setup up down dev test lint health seed migrate clean docker-build docker-up-full docker-down-full backup restore

help:
	@echo "FlightDeck - common commands"
	@echo "  make setup           - install dependencies (uv sync)"
	@echo "  make up              - start postgres + redis"
	@echo "  make down            - stop postgres + redis"
	@echo "  make dev             - run API server with reload"
	@echo "  make migrate         - apply DB migrations"
	@echo "  make seed            - seed airports + transfer partners"
	@echo "  make health          - check API + DB + Redis + API keys"
	@echo "  make test            - run pytest"
	@echo "  make lint            - run ruff"
	@echo "  make docker-build    - build the api/worker/beat image"
	@echo "  make docker-up-full  - run the full stack in Docker (api + worker + beat + postgres + redis)"
	@echo "  make docker-down-full - stop the full Docker stack"
	@echo "  make backup          - dump the postgres DB to backups/"
	@echo "  make restore FILE=.. - restore the postgres DB from a dump file"

setup:
	uv sync

up:
	docker compose up -d postgres redis
	@echo "Waiting for services to be healthy..."
	@until docker compose ps postgres | grep -q "healthy"; do sleep 1; done
	@until docker compose ps redis | grep -q "healthy"; do sleep 1; done
	@echo "Services ready."

down:
	docker compose down postgres redis

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

docker-build:
	docker compose build api worker beat

docker-up-full:
	docker compose up -d --build

docker-down-full:
	docker compose down

backup:
	mkdir -p backups
	docker compose exec -T postgres pg_dump -U flightdeck -Fc flightdeck > backups/flightdeck_$(shell date +%Y%m%d_%H%M%S).dump

restore:
ifndef FILE
	$(error FILE is not set. Usage: make restore FILE=backups/flightdeck_YYYYMMDD_HHMMSS.dump)
endif
	docker compose exec -T postgres pg_restore -U flightdeck -d flightdeck --clean --if-exists < $(FILE)
