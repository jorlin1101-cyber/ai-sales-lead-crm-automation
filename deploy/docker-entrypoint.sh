#!/bin/sh
set -eu

if [ -n "${CONVERSATION_DATABASE_URL:-}" ]; then
  alembic upgrade head
fi

exec uvicorn lead_cleaner.api.main:app --host 0.0.0.0 --port 8000
