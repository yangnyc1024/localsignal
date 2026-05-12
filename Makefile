PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTHONPYCACHEPREFIX := .python-cache
PIP_CACHE_DIR := .pip-cache

export PYTHONPYCACHEPREFIX
export PIP_CACHE_DIR

.PHONY: dev up down setup-python api engine demo-report report send-digest scheduler web

dev: up

setup-python:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

up:
	docker compose up --build

down:
	docker compose down

api:
	cd services/api && ../../.venv/bin/uvicorn app.main:app --reload --port 8000

engine:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_demo

demo-report:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_demo_report

report:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.run_weekly

send-digest:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.send_digest

scheduler:
	cd services/engine && ../../$(PYTHON) -m localsignal_engine.scheduler

web:
	cd apps/web && npm run dev
