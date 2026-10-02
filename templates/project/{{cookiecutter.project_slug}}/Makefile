.PHONY: up down migrate types check context rules agents test logs

up:
	docker compose up -d

down:
	docker compose down

migrate:
	docker compose exec django python manage.py makemigrations
	docker compose exec django python manage.py migrate

types:
	karni types

check:
	karni check
	karni rules sync --check

# Agent guidance: conventions, and regenerating AGENTS.md / CLAUDE.md / tool adapters.
rules:
	karni rules

agents:
	karni rules sync

context:
	karni context

test:
	docker compose exec django pytest

logs:
	docker compose logs -f django worker beat
