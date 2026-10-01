#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DATABASE_URL="postgresql+asyncpg://firebreak:firebreak@localhost:5432/firebreak_db"
export FIREBREAK_PUBLIC_BASE_URL="http://localhost:8000"

echo "Starting local Postgres and Adminer..."
docker compose -f ../docker-compose.yml up -d db adminer

echo "Building Tailwind CSS..."
pnpm run css

echo "Starting Firebreak dev server..."
echo "  FastAPI: http://localhost:8000"
echo "  Adminer: http://localhost:8080"
echo "           PostgreSQL / db / firebreak / firebreak / firebreak_db"
echo "  CSS:     watching app/static/css/input.css"

set -m
pnpm run css:watch &
TW_PID=$!
set +m

trap "kill -- -$TW_PID 2>/dev/null" EXIT

uv run uvicorn app.main:app --reload --port 8000
