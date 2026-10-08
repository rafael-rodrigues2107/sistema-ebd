#!/bin/bash
# Backup diário do banco do EBD. Detecta sozinho se o app usa Postgres ou SQLite,
# então funciona antes e depois da virada sem trocar nada.
#   Postgres -> ebd-AAAAMMDD-HHMMSS.pgdump   (pg_dump -Fc: comprimido, permite restaurar tabela a tabela)
#   SQLite   -> ebd-AAAAMMDD-HHMMSS.db.gz    (API de backup do SQLite, segura com WAL)
# Instalação na VPS: ver docs/VIRADA_POSTGRES.md (cron diário às 03:30).
# Variáveis opcionais: DESTINO, APP_CONTAINER, DB_CONTAINER, DIAS, SQLITE_ORIGEM.
set -euo pipefail

DESTINO=${DESTINO:-/var/backups/ebd}
APP=${APP_CONTAINER:-sistema-ebd-app-1}
DB=${DB_CONTAINER:-sistema-ebd-db-1}
DIAS=${DIAS:-14}
SQLITE_ORIGEM=${SQLITE_ORIGEM:-/var/lib/docker/volumes/sistema-ebd_ebd_data/_data/ebd.db}

mkdir -p "$DESTINO"; chmod 700 "$DESTINO"
TS=$(date +%Y%m%d-%H%M%S)

URL=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$APP" 2>/dev/null | grep '^DATABASE_URL=' | cut -d= -f2- || true)

case "$URL" in
  postgresql*)
    ARQ="$DESTINO/ebd-$TS.pgdump"
    docker exec "$DB" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$ARQ.tmp"
    # confere: o dump tem conteúdo, o índice é legível e o banco de origem responde
    ITENS=$(docker exec -i "$DB" pg_restore --list < "$ARQ.tmp" | grep -c 'TABLE DATA' || true)
    ALUNOS=$(docker exec "$DB" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(*) from alunos"')
    if [ "$ITENS" -lt 1 ]; then rm -f "$ARQ.tmp"; echo "ERRO: dump sem dados de tabelas" >&2; exit 1; fi
    mv "$ARQ.tmp" "$ARQ"; chmod 600 "$ARQ"
    echo "backup ok (postgres): $ARQ (tabelas com dados=$ITENS, alunos=$ALUNOS)"
    ;;
  *)
    ARQ="$DESTINO/ebd-$TS.db"
    python3 - "$SQLITE_ORIGEM" "$ARQ" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
n = dst.execute("select count(*) from alunos").fetchone()[0]
dst.close(); src.close()
if ok != "ok":
    raise SystemExit(f"integrity_check falhou: {ok}")
print(f"backup ok (sqlite): {sys.argv[2]} (alunos={n})")
PY
    gzip -f "$ARQ"; chmod 600 "$ARQ.gz"
    ;;
esac

# mantém os últimos $DIAS dias (qualquer formato)
find "$DESTINO" -maxdepth 1 \( -name 'ebd-*.pgdump' -o -name 'ebd-*.db.gz' \) -mtime +"$DIAS" -delete
