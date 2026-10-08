#!/bin/bash
# Testa que um backup .pgdump realmente restaura: sobe um Postgres descartável, restaura
# o arquivo e mostra a contagem de linhas das principais tabelas. Não toca na produção.
# Uso: testar-restauracao-postgres.sh /var/backups/ebd/ebd-AAAAMMDD-HHMMSS.pgdump
# Rode uma vez por mês: um backup que nunca foi restaurado é só uma esperança.
set -euo pipefail
ARQ=${1:?uso: $0 caminho/do/backup.pgdump}
[ -s "$ARQ" ] || { echo "arquivo não existe ou está vazio: $ARQ" >&2; exit 1; }
C=ebd-restauracao-teste
trap 'docker rm -f $C >/dev/null 2>&1 || true' EXIT
docker rm -f $C >/dev/null 2>&1 || true
docker run -d --name $C -e POSTGRES_USER=ebd -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=ebd postgres:16-alpine >/dev/null
for i in $(seq 1 30); do docker exec $C pg_isready -U ebd -d ebd >/dev/null 2>&1 && break; sleep 1; done
docker exec -i $C pg_restore -U ebd -d ebd --no-owner --exit-on-error < "$ARQ"
echo "restaurado. contagem por tabela:"
for t in alunos turmas trimestres domingos matriculas chamadas fechamentos_domingo usuarios; do
  printf '  %-22s %s\n' "$t" "$(docker exec $C psql -U ebd -d ebd -tAc "select count(*) from $t")"
done
echo "OK: o backup restaura."
