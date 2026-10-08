# Roteiro da virada: SQLite → Postgres em produção

Só executar depois de: testes verdes em Postgres, ensaio da migração com cópia real OK e
esta branch aprovada/mesclada. Fazer fora do horário da EBD (não domingo de manhã).
Tempo previsto de parada: 5 a 10 minutos.

## Antes (sem parar nada)
1. Backup do dia existe e foi baixado para o PC (`C:\dev\backup-ebd`).
2. No servidor, criar a senha do Postgres e guardar no `.env.prod` (nunca versionar):
   `echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" >> /opt/sistema-ebd/.env.prod`
3. `cd /opt/sistema-ebd && git pull` (traz o compose novo, Alembic, scripts). **Não** subir ainda.
4. Remover o container parado do Postgres antigo, se ainda existir (`docker rm sistema-ebd-db-1`).
   O volume antigo `sistema-ebd_pgdata` não é usado (o novo é `pg_ebd`).

## Virada
1. Parar só o app (o nginx fica; os usuários veem erro 502 por alguns minutos):
   `docker compose -f docker-compose.prod.yml --env-file .env.prod stop app`
2. Backup final consistente: `/usr/local/sbin/ebd-backup.sh` (anota o nome do arquivo gerado).
3. Subir só o Postgres e aplicar o esquema:
   `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d db`
   `docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps app sh -c "cd /app && alembic upgrade head"`
   (com `DATABASE_URL` de Postgres; o `app` já vem configurado no compose).
4. Copiar os dados do backup final (descompactado) para o Postgres:
   `python scripts/migrar_sqlite_para_postgres.py --origem sqlite+aiosqlite:////caminho/ebd.db --destino postgresql+asyncpg://...`
   Rodar de dentro de um container do app (`docker compose run --rm --no-deps -v /var/backups/ebd:/b:ro app ...`).
   Precisa terminar com `OK: dados copiados e conferidos.` e contagens iguais.
5. Subir o app: `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app`
6. Verificar: `https://minhaebd.cloud` abre, login de um admin, chamada de uma turma carrega,
   `docker logs sistema-ebd-app-1` sem erros.
   O seed do admin só roda com o banco sem usuários; como os dados foram copiados, não cria nada.

## Voltar atrás (se algo falhar nos passos 3 a 6)
O SQLite em `/data/ebd.db` não é alterado em nenhum momento.
1. `docker compose ... stop app`
2. `git checkout <commit-anterior-ao-postgres>` (ou reverter o compose para `DATABASE_URL: sqlite+aiosqlite:////data/ebd.db`)
3. `docker compose ... up -d --build app`
Perda de dados: nenhuma, porque ninguém escreveu no Postgres e o SQLite ficou parado.
Se já houve uso no Postgres antes de decidir voltar, as chamadas feitas nesse intervalo ficam só no Postgres.

## Depois (nos dias seguintes)
- Trocar o backup diário: `/usr/local/sbin/ebd-backup.sh` hoje copia o SQLite; passa a usar
  `docker exec sistema-ebd-db-1 pg_dump -U ebd ebd | gzip > /var/backups/ebd/ebd-<data>.sql.gz`
  (manter os últimos 14 dias; ajustar também `C:\dev\backup-ebd\baixar-backup.ps1` para `ebd-*.sql.gz`).
  **Fazer isso no mesmo dia da virada**, senão o backup fica parado.
- Testar uma restauração do `pg_dump` em banco vazio.
- Manter `/data/ebd.db` por 30 dias como último recurso; depois arquivar e remover.
- Atualizar o CLAUDE.md (banco de produção: Postgres, não mais SQLite).
