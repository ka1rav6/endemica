# EpiRoute — the root justfile is the primary command interface.
#
#   just                 list every recipe
#   just doctor          check prerequisites and configuration
#   just setup           install backend + frontend dependencies
#   just dev             run the whole development stack
#
# See docs/development.md for the full workflow.

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := true
set dotenv-filename := ".env"
set dotenv-required := false

root     := justfile_directory()
backend  := root / "backend"
frontend := root / "frontend"
venv     := backend / ".venv"
py       := venv / "bin" / "python"
data     := root / "data"

# `nvm`-managed Node is not on a non-interactive PATH. Setting EPIROUTE_NODE_BIN
# in .env makes every frontend recipe work from a plain shell too. The default
# is a non-existent directory rather than "", because an empty PATH element
# means "the current directory".
export PATH := env_var_or_default("EPIROUTE_NODE_BIN", "/nonexistent") + ":" + env_var("PATH")

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# Show all available recipes (default).
default:
    @just --list --unsorted

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Install backend and frontend dependencies and create .env if missing.
setup: _env setup-backend setup-frontend
    @echo ""
    @echo "Setup complete. Next:  just db-up && just db-migrate && just dev"

# Create .env from .env.example when it does not exist yet (never overwrites).
_env:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -f "{{ root }}/.env" ]]; then
        echo "✓ .env already exists (left untouched)"
    else
        cp "{{ root }}/.env.example" "{{ root }}/.env"
        echo "✓ created .env from .env.example"
    fi

# Create the backend virtualenv and install the package with dev extras.
setup-backend:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ backend }}"
    if command -v uv >/dev/null 2>&1; then
        # backend/.python-version pins the interpreter; --allow-existing keeps
        # `just setup` idempotent (AGENTS.md section 6.4).
        uv venv --allow-existing .venv
        uv pip install --quiet --python .venv/bin/python -e ".[dev]"
    else
        python3 -m venv .venv
        .venv/bin/python -m pip install --upgrade pip
        .venv/bin/python -m pip install -e ".[dev]"
    fi
    echo "✓ backend dependencies installed into backend/.venv"

# Install frontend dependencies from the committed lockfile.
setup-frontend:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ frontend }}"
    if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
    echo "✓ frontend dependencies installed"

# Re-install dependencies after a manifest change.
deps: setup-backend setup-frontend

# Report outdated / vulnerable dependencies (advisory only, never fails setup).
deps-check:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "── Python ──"; "{{ py }}" -m pip list --outdated || true
    echo "── Node ──";   (cd "{{ frontend }}" && npm outdated; npm audit --omit=dev) || true

# ---------------------------------------------------------------------------
# Configuration and diagnostics
# ---------------------------------------------------------------------------

# Validate configuration: required settings present, optional ones reported.
config-check:
    "{{ py }}" -m epiroute.cli config-check

# Check prerequisites, dependencies, database and data state.
doctor:
    #!/usr/bin/env bash
    set -uo pipefail
    fail=0
    chk() { printf '  %-34s' "$1"; shift; if out=$("$@" 2>&1); then echo "✓ ${out%%$'\n'*}"; else echo "✗ ${out%%$'\n'*}"; fail=1; fi; }
    echo "Prerequisites"
    chk "python3"        bash -c 'python3 --version'
    chk "node"           bash -c 'node --version'
    chk "npm"            bash -c 'npm --version'
    chk "just"           bash -c 'just --version'
    chk "docker"         bash -c 'docker --version'
    echo "Project"
    chk ".env present"   bash -c '[[ -f "{{ root }}/.env" ]] && echo "{{ root }}/.env" || { echo "missing — run: just setup"; exit 1; }'
    chk "backend venv"   bash -c '[[ -x "{{ py }}" ]] && "{{ py }}" --version || { echo "missing — run: just setup-backend"; exit 1; }'
    chk "backend deps"   bash -c '"{{ py }}" -c "import fastapi, sqlalchemy, psycopg; print(\"fastapi\", fastapi.__version__)"'
    chk "frontend deps"  bash -c '[[ -d "{{ frontend }}/node_modules" ]] && echo installed || { echo "missing — run: just setup-frontend"; exit 1; }'
    chk "data dir writable" bash -c 'touch "{{ data }}/.write-test" && rm -f "{{ data }}/.write-test" && echo "{{ data }}"'
    echo "Runtime"
    chk "postgres reachable" bash -c '"{{ py }}" -m epiroute.cli db-status --quiet'
    echo "Configuration"
    "{{ py }}" -m epiroute.cli config-check || fail=1
    echo ""
    if [[ $fail -eq 0 ]]; then echo "doctor: all checks passed"; else echo "doctor: some checks failed (see ✗ above)"; exit 1; fi

# Tail the backend development log.
logs lines="80":
    #!/usr/bin/env bash
    set -euo pipefail
    f="{{ root }}/logs/backend.log"
    [[ -f "$f" ]] || { echo "no log file yet at $f (start with: just start)"; exit 1; }
    tail -n {{ lines }} -f "$f"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Start the PostgreSQL container and wait until it accepts connections.
db-up:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose up -d postgres
    echo -n "waiting for postgres"
    for _ in $(seq 1 60); do
        if docker compose exec -T postgres pg_isready -q -U "${POSTGRES_USER:-epiroute}" -d "${POSTGRES_DB:-epiroute}" 2>/dev/null; then
            echo " ✓ ready on port ${POSTGRES_PORT:-55433}"; exit 0
        fi
        echo -n "."; sleep 1
    done
    echo " ✗ timed out"; docker compose logs --tail=40 postgres; exit 1

# Stop the PostgreSQL container (data volume is preserved).
db-down:
    docker compose stop postgres

# Show connectivity, applied migration revision and row counts.
db-status:
    "{{ py }}" -m epiroute.cli db-status

# Apply all pending Alembic migrations.
db-migrate:
    cd "{{ backend }}" && "{{ venv }}/bin/alembic" upgrade head

# Create a new migration from model changes (review the output before committing).
db-revision message:
    cd "{{ backend }}" && "{{ venv }}/bin/alembic" revision --autogenerate -m "{{ message }}"

# Roll back the most recent migration.
db-downgrade:
    cd "{{ backend }}" && "{{ venv }}/bin/alembic" downgrade -1

# DESTRUCTIVE: drop every table and re-apply migrations. Asks for confirmation.
db-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "This DROPS every table in ${POSTGRES_DB:-epiroute} and re-runs migrations."
    read -r -p "Type 'reset' to continue: " a
    [[ "$a" == "reset" ]] || { echo "aborted"; exit 1; }
    cd "{{ backend }}" && "{{ venv }}/bin/alembic" downgrade base && "{{ venv }}/bin/alembic" upgrade head
    echo "✓ database reset"

# Remove unreferenced ingestion runs older than the given number of days.
db-vacuum days="90":
    "{{ py }}" -m epiroute.cli db-vacuum --older-than-days {{ days }}

# Open a psql shell on the development database.
db-shell:
    docker compose exec postgres psql -U "${POSTGRES_USER:-epiroute}" -d "${POSTGRES_DB:-epiroute}"

# ---------------------------------------------------------------------------
# Development servers
# ---------------------------------------------------------------------------

# Run backend and frontend together (Ctrl-C stops both).
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT INT TERM
    just dev-backend & just dev-frontend & wait

# Run the FastAPI backend with autoreload on http://localhost:8000
dev-backend:
    cd "{{ backend }}" && "{{ venv }}/bin/uvicorn" epiroute.main:app --reload --host 127.0.0.1 --port 8000

# Run the Vite dev server on http://localhost:5173
dev-frontend:
    cd "{{ frontend }}" && npm run dev

# Start the backend detached, logging to logs/backend.log
start:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ root }}/logs"
    if [[ -f "{{ root }}/logs/backend.pid" ]] && kill -0 "$(cat "{{ root }}/logs/backend.pid")" 2>/dev/null; then
        echo "backend already running (pid $(cat "{{ root }}/logs/backend.pid"))"; exit 0
    fi
    cd "{{ backend }}"
    nohup "{{ venv }}/bin/uvicorn" epiroute.main:app --host 127.0.0.1 --port 8000 \
        >> "{{ root }}/logs/backend.log" 2>&1 &
    echo $! > "{{ root }}/logs/backend.pid"
    echo "✓ backend started (pid $(cat "{{ root }}/logs/backend.pid")) → logs/backend.log"

# Stop the detached backend started by `just start`.
stop:
    #!/usr/bin/env bash
    set -euo pipefail
    f="{{ root }}/logs/backend.pid"
    [[ -f "$f" ]] || { echo "no pid file; nothing to stop"; exit 0; }
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then kill "$pid"; echo "✓ stopped pid $pid"; else echo "pid $pid not running"; fi
    rm -f "$f"

# Report what is running: backend process, database, frontend build.
status:
    #!/usr/bin/env bash
    set -uo pipefail
    f="{{ root }}/logs/backend.pid"
    if [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; then echo "backend:  running (pid $(cat "$f"))";
    else echo "backend:  not running (via just start)"; fi
    docker compose ps --format '  postgres: {{{{.State}}}} {{{{.Ports}}}}' postgres 2>/dev/null || echo "postgres: compose unavailable"
    [[ -d "{{ frontend }}/dist" ]] && echo "frontend: build present in frontend/dist" || echo "frontend: no production build"

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

# Run every test suite that does not need external services.
test: test-backend test-frontend

# Run the backend unit + offline integration tests.
test-backend *args:
    cd "{{ backend }}" && "{{ venv }}/bin/pytest" {{ args }}

# Run backend tests that require a live PostgreSQL (`just db-up` first).
test-integration *args:
    cd "{{ backend }}" && "{{ venv }}/bin/pytest" -m integration {{ args }}

# Run the backend tests that call live external APIs (needs internet).
test-network *args:
    cd "{{ backend }}" && "{{ venv }}/bin/pytest" -m network {{ args }}

# Run the frontend unit tests.
test-frontend *args:
    cd "{{ frontend }}" && npm run test -- {{ args }}

# Backend coverage report.
coverage:
    cd "{{ backend }}" && "{{ venv }}/bin/pytest" --cov=epiroute --cov-report=term-missing --cov-report=html
    @echo "HTML report: backend/htmlcov/index.html"

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

# Lint backend and frontend.
lint: lint-backend lint-frontend

# Lint the Python sources with Ruff.
lint-backend:
    cd "{{ backend }}" && "{{ venv }}/bin/ruff" check src tests

# Lint the TypeScript sources with ESLint.
lint-frontend:
    cd "{{ frontend }}" && npm run lint

# Apply formatting and safe lint fixes to both languages.
format: format-backend format-frontend

# Format Python with Ruff and apply its safe fixes.
format-backend:
    cd "{{ backend }}" && "{{ venv }}/bin/ruff" format src tests
    cd "{{ backend }}" && "{{ venv }}/bin/ruff" check --fix src tests

# Format TypeScript with Prettier.
format-frontend:
    cd "{{ frontend }}" && npm run format

# Verify formatting without changing files (for CI).
format-check: format-check-backend format-check-frontend

format-check-backend:
    cd "{{ backend }}" && "{{ venv }}/bin/ruff" format --check src tests

format-check-frontend:
    cd "{{ frontend }}" && npm run format:check

# Static type checks for both languages.
typecheck: typecheck-backend typecheck-frontend

# Type-check the Python sources with mypy (strict).
typecheck-backend:
    cd "{{ backend }}" && "{{ venv }}/bin/mypy"

# Type-check the TypeScript sources with tsc --noEmit.
typecheck-frontend:
    cd "{{ frontend }}" && npm run typecheck

# Everything a change must pass before being committed.
check: format-check lint typecheck test

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

# Build the backend wheel and the production frontend bundle.
build: build-backend build-frontend

# Build the backend wheel.
build-backend:
    cd "{{ backend }}" && "{{ py }}" -m pip wheel --no-deps -w dist .

# Build the production frontend bundle into frontend/dist.
build-frontend:
    cd "{{ frontend }}" && npm run build

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

# Report which datasets are present, their age and their provenance.
data-check:
    "{{ py }}" -m epiroute.cli data-check

# Download the reference datasets into data/raw (skips files already present).
data-fetch *args:
    "{{ py }}" -m epiroute.cli data-fetch {{ args }}

# Re-download every reference dataset, replacing what is in data/raw.
data-refresh:
    "{{ py }}" -m epiroute.cli data-fetch --force

# Build the processed tables (countries, flows, routes) from data/raw.
data-build *args:
    "{{ py }}" -m epiroute.cli data-build {{ args }}

# Load the processed reference tables into PostgreSQL.
data-load:
    "{{ py }}" -m epiroute.cli data-load

# Validate the processed datasets against their documented invariants.
data-validate:
    "{{ py }}" -m epiroute.cli data-validate

# Fit the passenger-flow gravity model and write its held-out evaluation.
model-fit *args:
    "{{ py }}" -m epiroute.cli model-fit {{ args }}

# Print the stored gravity-model evaluation report.
model-report:
    "{{ py }}" -m epiroute.cli model-report

# Download historical first-report dates and write a 20-row audit.
labels-build:
    "{{ py }}" -m epiroute.cli labels-build

# Fit the next-country hazard and write data/processed/model_card.json.
train-model:
    "{{ py }}" -m epiroute.cli train-model

# Print the model card and exit non-zero when it is not validated.
validate-model:
    "{{ py }}" -m epiroute.cli validate-model

# Check processed passenger and population tables.
qa-data:
    "{{ py }}" -m epiroute.cli qa-data

# Run a WHO Disease Outbreak News ingestion pass.
data-ingest *args:
    "{{ py }}" -m epiroute.cli ingest {{ args }}

# Write an offline demonstration snapshot to data/snapshot.
snapshot-build:
    "{{ py }}" -m epiroute.cli snapshot-build

# Load a previously written snapshot into the database.
snapshot-load:
    "{{ py }}" -m epiroute.cli snapshot-load

# One command from an empty database to a demonstrable application.
bootstrap: db-up db-migrate data-fetch data-build data-load model-fit data-ingest
    @echo ""
    @echo "Bootstrap complete. Start the app with: just dev"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

# Write the OpenAPI schema to docs/openapi.json
api-docs:
    "{{ py }}" -m epiroute.cli openapi --output "{{ root }}/docs/openapi.json"
    @echo "✓ docs/openapi.json updated"

# Smoke-check a running API: /health plus the main read endpoints.
api-check base="http://127.0.0.1:8000":
    "{{ py }}" -m epiroute.cli api-check --base-url {{ base }}

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

# Short branch-aware working-tree status.
git-status:
    git status --short --branch

# Recent commit graph.
git-log n="20":
    git --no-pager log --oneline --graph --decorate -n {{ n }}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

# Remove build artefacts and caches. Downloaded data and the database are kept.
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf "{{ backend }}/dist" "{{ backend }}/htmlcov" "{{ backend }}/.pytest_cache" \
           "{{ backend }}/.ruff_cache" "{{ backend }}/.mypy_cache" "{{ backend }}/.coverage" \
           "{{ frontend }}/dist" "{{ frontend }}/.vite" "{{ root }}/logs"
    find "{{ backend }}" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    echo "✓ build artefacts and caches removed"

# DESTRUCTIVE: also remove downloaded data, processed tables and virtualenvs.
clean-all: clean
    #!/usr/bin/env bash
    set -euo pipefail
    echo "This removes data/raw, data/processed, data/cache, backend/.venv and frontend/node_modules."
    read -r -p "Type 'clean' to continue: " a
    [[ "$a" == "clean" ]] || { echo "aborted"; exit 1; }
    rm -rf "{{ data }}/raw"/* "{{ data }}/processed"/* "{{ data }}/cache"/* "{{ venv }}" "{{ frontend }}/node_modules"
    echo "✓ removed (re-create with: just setup)"
