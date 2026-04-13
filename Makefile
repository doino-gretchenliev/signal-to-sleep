# Signal-to-Sleep — Developer Makefile
# ─────────────────────────────────────────────────────────────
#
#  Granular targets (use individually):
#    make build          docker compose build
#    make up             docker compose up -d
#    make down           docker compose stop
#    make seed           seed 7 nights of simulated sleep data
#    make stream         start live data streamer (background)
#    make analyze        re-analyze the latest session via API
#    make open           open the dashboard in a browser
#    make status         show container & health status
#    make logs           tail all container logs
#    make logs-app       tail only the app container log
#    make logs-mqtt      tail only the mosquitto log
#
#  Combo targets (compose the above):
#    make demo-start     build + up + seed + stream + open
#    make demo-stop      down
#    make demo-destroy   down + remove volumes
#
#  Local dev (no Docker):
#    make venv           create .venv
#    make install        pip install into .venv
#    make dev            run uvicorn locally (no MQTT)
#
#  Frontend (Vue + Vite):
#    make frontend       build Vue SPA → frontend/dist/
#    make frontend-dev   start Vite dev server (HMR, proxy to backend)
#
# ─────────────────────────────────────────────────────────────

SHELL        := /bin/bash
PROJECT_DIR  := $(shell pwd)
COMPOSE      := docker compose
COMPOSE_FILE := $(PROJECT_DIR)/docker-compose.yml
BACKEND_SERVICE := backend
MQTT_SERVICE := mosquitto
VENV_DIR     := $(PROJECT_DIR)/.venv
PYTHON       := $(VENV_DIR)/bin/python
PIP          := $(VENV_DIR)/bin/pip
PID_FILE     := $(PROJECT_DIR)/.demo.pid
LOG_FILE     := $(PROJECT_DIR)/.demo.log
PORT         := 8080
DASHBOARD    := http://localhost:$(PORT)
HEALTH_URL   := http://127.0.0.1:$(PORT)/api/health

# ── Detect OS for open command ─────────────────────────────
UNAME := $(shell uname -s)
ifeq ($(UNAME),Darwin)
  OPEN := open
else ifeq ($(UNAME),Linux)
  OPEN := xdg-open 2>/dev/null || echo "Visit"
else
  OPEN := start
endif

.PHONY: init build up down seed stream stream-stop analyze open status logs logs-app logs-mqtt \
        start stop sniff _print-mqtt \
        demo-start demo-stop demo-destroy \
        venv install dev dev-stop \
        frontend frontend-dev frontend-install \
        _wait-healthy


# ═════════════════════════════════════════════════════════════
# Granular targets — Docker
# ═════════════════════════════════════════════════════════════

# ── init (first-time setup) ───────────────────────────────
# Generates .env with a random MQTT password and creates mosquitto/passwd.
# Safe to run multiple times — skips if .env already has a password set.
init:
	@if [ -f .env ] && grep -q '^MQTT_PASSWORD=.\+' .env 2>/dev/null; then \
		echo "  ✓ Already initialized (.env has MQTT_PASSWORD set)"; \
	else \
		PASS=$$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24); \
		echo "  → Generating .env with random MQTT password …"; \
		cp .env.example .env; \
		if [ "$$(uname)" = "Darwin" ]; then \
			sed -i '' "s/^MQTT_PASSWORD=$$/MQTT_PASSWORD=$$PASS/" .env; \
		else \
			sed -i "s/^MQTT_PASSWORD=$$/MQTT_PASSWORD=$$PASS/" .env; \
		fi; \
		USER=$$(grep '^MQTT_USERNAME=' .env | cut -d= -f2); \
		echo "$$USER:$$PASS" > mosquitto/passwd; \
		echo "    ✓ .env created"; \
		echo "    ✓ mosquitto/passwd created"; \
		echo ""; \
		echo "  ┌─────────────────────────────────────────────┐"; \
		echo "  │  MQTT credentials (save these!)             │"; \
		echo "  │                                             │"; \
		echo "  │  Username:  $$USER"; \
		echo "  │  Password:  $$PASS"; \
		echo "  └─────────────────────────────────────────────┘"; \
	fi
	@echo ""


# ── build ─────────────────────────────────────────────────
build:
	@echo "  → Building backend and frontend …"
	@$(COMPOSE) build -q backend frontend
	@echo "    ✓ Build complete"
	@echo ""


# ── up ────────────────────────────────────────────────────
up:
	@echo "  → Starting containers …"
	@$(COMPOSE) up -d
	@echo ""


# ── down ──────────────────────────────────────────────────
down:
	@echo "  → Stopping containers …"
	@$(COMPOSE) stop
	@echo "    ✓ Stopped"
	@echo ""


# ── seed ──────────────────────────────────────────────────
seed: _wait-healthy
	@echo "  → Seeding 7 nights of simulated sleep data …"
	@echo ""
	@$(COMPOSE) exec $(BACKEND_SERVICE) python scripts/demo_seed.py --seed-only
	@echo ""

# ── reseed (wipe + fresh seed) ────────────────────────────
reseed: _wait-healthy
	@echo "  → Wiping existing data and reseeding …"
	@$(COMPOSE) exec $(BACKEND_SERVICE) rm -f /app/db/sleep_data.db
	@$(COMPOSE) restart $(BACKEND_SERVICE)
	@sleep 3
	@$(MAKE) --no-print-directory _wait-healthy
	@$(COMPOSE) exec $(BACKEND_SERVICE) python scripts/demo_seed.py --seed-only
	@echo "    ✓ Fresh data ready"
	@echo ""


# ── stream (background) ──────────────────────────────────
stream: _wait-healthy
	@echo "  → Starting live data streamer in background …"
	@$(COMPOSE) exec -d $(BACKEND_SERVICE) python scripts/demo_seed.py --stream-only
	@echo "    ✓ Streamer running (detached)"
	@echo ""

stream-stop:
	@echo "  → Stopping live data streamer …"
	@$(COMPOSE) exec $(BACKEND_SERVICE) pkill -f "demo_seed.py --stream-only" 2>/dev/null || true
	@echo "    ✓ Stopped"
	@echo ""


# ── analyze ───────────────────────────────────────────────
analyze: _wait-healthy
	@echo "  → Triggering analysis on latest session …"
	@SESSION=$$(curl -sf http://127.0.0.1:$(PORT)/api/sessions | python3 -c \
		"import sys,json; ss=json.load(sys.stdin); print(ss[0]['session_id'] if ss else '')" 2>/dev/null); \
	if [ -z "$$SESSION" ]; then \
		echo "    ✗ No sessions found. Run 'make seed' first."; \
		exit 1; \
	fi; \
	echo "    Session: $$SESSION"; \
	RESULT=$$(curl -sf -X POST http://127.0.0.1:$(PORT)/api/analyze/$$SESSION); \
	echo "    $$RESULT"; \
	echo "    ✓ Analysis complete"
	@echo ""


# ── open ──────────────────────────────────────────────────
open:
	@echo "  → Opening $(DASHBOARD) …"
	@$(OPEN) "$(DASHBOARD)" 2>/dev/null || true
	@echo ""


# ── status ────────────────────────────────────────────────
status:
	@echo ""
	@$(COMPOSE) ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $(COMPOSE) ps
	@echo ""
	@echo "  Health:"
	@curl -sf $(HEALTH_URL) | python3 -m json.tool 2>/dev/null || echo "    Server not reachable"
	@echo ""


# ── logs ──────────────────────────────────────────────────
logs:
	@$(COMPOSE) logs -f --tail 50

logs-app:
	@$(COMPOSE) logs -f --tail 50 $(BACKEND_SERVICE)

logs-mqtt:
	@$(COMPOSE) logs -f --tail 50 $(MQTT_SERVICE)

sniff: _wait-healthy
	@echo "  → Listening for MQTT messages (Ctrl+C to stop) …"
	@echo ""
	@$(COMPOSE) exec $(BACKEND_SERVICE) python scripts/mqtt_sniff.py


# ═════════════════════════════════════════════════════════════
# Combo targets
# ═════════════════════════════════════════════════════════════

# ── start (clean, no seed data — for real Apple Watch use) ──
start: init build up _wait-healthy open _print-mqtt

_print-mqtt:
	@HOST_IP=$$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "localhost"); \
	MQTT_USER=$$(grep '^MQTT_USERNAME=' .env | cut -d= -f2); \
	MQTT_PASS=$$(grep '^MQTT_PASSWORD=' .env | cut -d= -f2); \
	MQTT_TOPIC=$$(grep '^MQTT_TOPIC=' .env | cut -d= -f2); \
	echo ""; \
	echo "  ┌─────────────────────────────────────────────┐"; \
	echo "  │  Dashboard: $(DASHBOARD)            │"; \
	echo "  └─────────────────────────────────────────────┘"; \
	echo ""; \
	echo "  ── Sensor Logger MQTT Settings ──────────────────"; \
	echo "  Connection: WebSocket"; \
	echo "  Host:       $$HOST_IP"; \
	echo "  Port:       1884"; \
	echo "  Topic:      $$MQTT_TOPIC"; \
	echo "  Username:   $$MQTT_USER"; \
	echo "  Password:   $$MQTT_PASS"; \
	echo "  ─────────────────────────────────────────────────"; \
	echo ""; \
	echo "  make status   → health & containers"; \
	echo "  make logs     → tail all logs"; \
	echo "  make sniff    → watch MQTT messages"; \
	echo "  make stop     → stop containers"; \
	echo ""

stop: down

# ── demo-start (with seed data) ───────────────────────────
demo-start: init build up open seed stream
	@echo "  ┌─────────────────────────────────────────────┐"
	@echo "  │  Dashboard: $(DASHBOARD)            │"
	@echo "  │                                             │"
	@echo "  │  make status        → health & containers   │"
	@echo "  │  make logs          → tail all logs         │"
	@echo "  │  make seed          → add more test data    │"
	@echo "  │  make sniff         → watch MQTT messages   │"
	@echo "  │  make demo-stop     → stop containers       │"
	@echo "  │  make demo-destroy  → stop + wipe all data  │"
	@echo "  └─────────────────────────────────────────────┘"
	@echo ""


# ── demo-stop ──────────────────────────────────────────────
demo-stop: stream-stop down


# ── demo-destroy ───────────────────────────────────────────
demo-destroy:
	@echo "  → Tearing down containers and volumes …"
	@$(COMPOSE) down -v
	@echo "    ✓ Clean slate"
	@echo ""


# ═════════════════════════════════════════════════════════════
# Local dev (no Docker, no MQTT)
# ═════════════════════════════════════════════════════════════

venv:
	@if [ -d "$(VENV_DIR)" ]; then \
		echo "  ✓ Virtual environment already exists"; \
	else \
		echo "  → Creating virtual environment …"; \
		python3 -m venv "$(VENV_DIR)" || python -m venv "$(VENV_DIR)"; \
		echo "    ✓ Created $(VENV_DIR)"; \
	fi
	@echo ""

install: venv
	@echo "  → Installing dependencies into venv …"
	@"$(PIP)" install -r requirements.txt -q
	@echo "    ✓ Done"
	@echo ""

dev: install
	@# Kill anything on the port first
	@STALE=$$(lsof -ti tcp:$(PORT) 2>/dev/null | head -1); \
	if [ -n "$$STALE" ]; then \
		echo "  ⚠  Port $(PORT) in use (PID $$STALE) — killing …"; \
		kill $$STALE 2>/dev/null; sleep 1; \
	fi
	@mkdir -p "$(PROJECT_DIR)/db"
	@echo "  → Starting dev server on port $(PORT) (no MQTT) …"
	@cd "$(PROJECT_DIR)" && \
		DATABASE_PATH="$(PROJECT_DIR)/db/sleep_data.db" \
		WEB_PORT=$(PORT) \
		nohup "$(PYTHON)" -m uvicorn server:app \
			--host 127.0.0.1 --port $(PORT) --reload \
			> "$(LOG_FILE)" 2>&1 & \
		echo $$! > "$(PID_FILE)"
	@echo "    PID: $$(cat $(PID_FILE))"
	@echo "  → Waiting for server …"
	@for i in $$(seq 1 40); do \
		if curl -sf $(HEALTH_URL) > /dev/null 2>&1; then break; fi; \
		if [ $$i -eq 40 ]; then echo "    ✗ Failed. Check .demo.log"; exit 1; fi; \
		sleep 0.5; \
	done
	@echo "    ✓ Dev server running — $(DASHBOARD)"
	@echo ""

dev-seed: install
	@echo "  → Seeding demo data (local) …"
	@cd "$(PROJECT_DIR)/backend" && \
		DATABASE_PATH="$(PROJECT_DIR)/db/sleep_data.db" \
		"$(PYTHON)" scripts/demo_seed.py --seed-only
	@echo ""

dev-reseed: install
	@echo "  → Wiping and reseeding demo data (local) …"
	@rm -f "$(PROJECT_DIR)/db/sleep_data.db"
	@cd "$(PROJECT_DIR)/backend" && \
		DATABASE_PATH="$(PROJECT_DIR)/db/sleep_data.db" \
		"$(PYTHON)" scripts/demo_seed.py --seed-only
	@echo ""

dev-stop:
	@if [ -f "$(PID_FILE)" ]; then \
		PID=$$(cat "$(PID_FILE)"); \
		if kill -0 $$PID 2>/dev/null; then \
			echo "  → Stopping dev server (PID $$PID) …"; \
			kill $$PID 2>/dev/null; sleep 1; \
			kill -0 $$PID 2>/dev/null && kill -9 $$PID 2>/dev/null; \
		fi; \
		rm -f "$(PID_FILE)"; \
	fi
	@STALE=$$(lsof -ti tcp:$(PORT) 2>/dev/null); \
	if [ -n "$$STALE" ]; then \
		echo "  → Killing orphan on port $(PORT) …"; \
		echo "$$STALE" | xargs kill 2>/dev/null; \
	fi
	@rm -f "$(LOG_FILE)"
	@echo "    ✓ Dev server stopped"
	@echo ""

# ═════════════════════════════════════════════════════════════
# Frontend (Vue + Vite)
# ═════════════════════════════════════════════════════════════

frontend-install:
	@echo "  → Installing frontend dependencies …"
	@cd "$(PROJECT_DIR)/frontend" && npm install --no-audit --no-fund
	@echo "    ✓ Done"
	@echo ""

frontend: frontend-install
	@echo "  → Building Vue frontend …"
	@cd "$(PROJECT_DIR)/frontend" && npm run build
	@echo "    ✓ Built → frontend/dist/"
	@echo ""

frontend-dev: frontend-install
	@echo "  → Starting Vite dev server (port 5173, proxying API to $(PORT)) …"
	@cd "$(PROJECT_DIR)/frontend" && npx vite --host
	@echo ""


# ═════════════════════════════════════════════════════════════
# Internal helpers
# ═════════════════════════════════════════════════════════════

_wait-healthy:
	@echo "  → Waiting for app to be healthy …"
	@for i in $$(seq 1 60); do \
		if curl -sf $(HEALTH_URL) > /dev/null 2>&1; then \
			echo "    ✓ Healthy"; \
			break; \
		fi; \
		if [ $$i -eq 60 ]; then \
			echo "    ✗ App not healthy after 30s. Run 'make logs-app' to debug."; \
			exit 1; \
		fi; \
		sleep 0.5; \
	done
