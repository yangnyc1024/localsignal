.PHONY: dev up down api engine web

dev: up

up:
	docker compose up --build

down:
	docker compose down

api:
	cd services/api && uvicorn app.main:app --reload --port 8000

engine:
	cd services/engine && python -m localsignal_engine.run_demo

web:
	cd apps/web && npm run dev
