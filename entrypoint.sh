#!/bin/sh
# Sobe o app. Em Postgres aplica as migrations do Alembic antes; em SQLite
# (dev/instalações antigas) o app cria as tabelas sozinho.
set -e
case "$DATABASE_URL" in
  postgresql*)
    cd /app
    echo "Aplicando migrations (alembic upgrade head)..."
    alembic upgrade head
    cd /app/app
    ;;
esac
exec uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log
