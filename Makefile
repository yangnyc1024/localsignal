PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTHONPYCACHEPREFIX := .python-cache
PIP_CACHE_DIR := .pip-cache

export PYTHONPYCACHEPREFIX
export PIP_CACHE_DIR

.PHONY: dev up up-detached down ps logs setup-python api engine demo-report evidence-ingestion baseline-profiles discover-places report send-digest send-test-email scheduler web validate-social apify-instagram-search docker-discover docker-evidence docker-report docker-send-digest docker-shell

dev: up

setup-python:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

up:
	docker compose up --build

up-detached:
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=120

api:
	cd services/api && ../../.venv/bin/uvicorn app.main:app --reload --port 8000

engine:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_demo

demo-report:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_demo_report

evidence-ingestion:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_evidence_ingestion

baseline-profiles:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_baseline_profiles

discover-places:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.discover_places

report:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_weekly

send-digest:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.send_digest

send-test-email:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.send_test_email

scheduler:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.scheduler

web:
	cd apps/web && npm run dev

validate-social:
	PYTHONPATH=services/engine SOCIAL_JSON_PATHS="$(SOCIAL_JSON_PATHS)" $(PYTHON) -m localsignal_engine.validate_social_metadata

apify-instagram-search:
	set -a && source .env && PYTHONPATH=services/engine $(PYTHON) -m localsignal_engine.run_apify_instagram_search

# Docker-first pipeline commands. These use the same services/env as docker compose.
docker-discover:
	docker compose run --rm engine python -m localsignal_engine.discover_places

docker-evidence:
	docker compose run --rm -e REDDIT_SUBREDDITS= engine python -m localsignal_engine.run_evidence_ingestion

docker-report:
	docker compose run --rm -e SEND_DIGEST_ENABLED=false -e REDDIT_SUBREDDITS= engine python -m localsignal_engine.run_weekly

docker-send-digest:
	docker compose exec -T scheduler python -m localsignal_engine.send_digest

docker-shell:
	docker compose exec api /bin/sh
