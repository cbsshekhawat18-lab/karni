.PHONY: up down serve migrate types check context rules agents test shell routes schedules superuser logs

# Every target is a thin alias for a `karni` command, which runs through the
# project .venv when present, else the running compose service.

up:
	karni serve -d

down:
	docker compose down

serve:
	karni serve

migrate:
	karni manage makemigrations
	karni migrate

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
	karni test

shell:
	karni shell

routes:
	karni routes

schedules:
	karni schedule list

superuser:
	karni createsuperuser

logs:
	docker compose logs -f django worker beat
