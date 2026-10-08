# Sistema EBD

Sistema de chamada e gestão da Escola Bíblica Dominical: chamada pelos professores no celular (PWA com modo offline), cadastro, fechamento de domingo e dashboard.

## Stack
- Backend: FastAPI + SQLAlchemy async (`app/`), entrada em `app/main.py`, rotas em `app/routers/`
- Frontend: HTML estático em `app/static/` (servido pelo FastAPI; `/` é a tela de chamada)
- Banco: **PostgreSQL 16 em produção** (`DATABASE_URL`); SQLite só em desenvolvimento e testes (padrão em `app/config.py`)
- Migrations: Alembic (`alembic/`, `alembic.ini`). Em Postgres o `entrypoint.sh` roda `alembic upgrade head` ao subir o app;
  em SQLite o app cria as tabelas sozinho. Mudou um modelo? `alembic revision --autogenerate -m "descricao"` (com `DATABASE_URL`
  de um Postgres), revisar o arquivo gerado e commitar junto. Nunca alterar tabela à mão em produção.
- Login com perfis `admin` e `professor` (professor só vê a própria turma)

## Produção (VPS Hostinger)
- Site: https://minhaebd.cloud — servidor `root@72.61.62.199`, código em `/opt/sistema-ebd`
- Sobe com `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app`
- Containers: `sistema-ebd-app-1` (FastAPI), `sistema-ebd-db-1` (Postgres 16) e `sistema-ebd-nginx-1` (HTTPS).
  Depois de recriar o app, reiniciar o nginx (`docker compose ... restart nginx`) para ele pegar o endereço novo.
- Banco de produção: Postgres no volume `sistema-ebd_pg_ebd`, sem porta exposta (só a rede interna do compose).
  Desde 08/out/2026; antes era SQLite. O `/data/ebd.db` antigo (volume `sistema-ebd_ebd_data`) foi mantido só como último
  recurso e pode ser arquivado depois de ~30 dias. O volume `/data` guarda também os uploads (logo da igreja).
- `.env.prod` só existe no servidor (`SECRET_KEY`, `POSTGRES_PASSWORD`) — nunca versionar
- Certificado: certbot instalado no host (timer systemd, webroot no volume `sistema-ebd_certbot_www`);
  o hook `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx-ebd.sh` recarrega o nginx após renovar
- Primeiro admin: `seed_admin` só roda com o banco sem usuários e usa `ADMIN_INITIAL_PASSWORD` (ou gera senha aleatória
  e mostra uma vez no log). Não existe senha padrão.

### Backup
- `/usr/local/sbin/ebd-backup.sh` (fonte em `scripts/backup/ebd-backup.sh`), cron diário às 03:30, guarda 14 dias em
  `/var/backups/ebd/`. Detecta pelo `DATABASE_URL` do app se é Postgres (`.pgdump`, `pg_dump -Fc`) ou SQLite (`.db.gz`).
  Log em `/var/log/ebd-backup.log`.
- Cópia fora da VPS: tarefa agendada do Windows "EBD - Copia noturna do backup" (04:00) roda
  `C:\dev\backup-ebd\baixar-backup.ps1` e guarda 30 dias em `C:\dev\backup-ebd\`. Só roda com o PC ligado.
- Testar a restauração uma vez por mês: `bash scripts/backup/testar-restauracao-postgres.sh /var/backups/ebd/<arquivo>.pgdump`
  (os scripts `.sh` não têm bit de execução no Git do Windows; rodar com `bash`).

### Segurança da VPS
- Incidente em 05/out/2026: o Ollama (container) estava publicado em `0.0.0.0:11434` sem firewall, foi explorado (RCE) e
  rodou um minerador; a Hostinger suspendeu a VPS por malware e o site ficou ~2 dias fora do ar. n8n, Baserow, OpenClaw e
  Ollama foram removidos. **Regra: nunca publicar porta de serviço auxiliar para a internet.** Só 22, 80 e 443 ficam abertas.
- Firewall (ufw) ativo liberando 22/80/443. O ufw não barra portas publicadas pelo Docker; por isso há também o serviço
  systemd `ebd-fecha-portas` (regras em `DOCKER-USER`) bloqueando 5678, 8080, 58954 e 11434.
- fail2ban ativo no SSH; SSH só com chave (`/etc/ssh/sshd_config.d/00-seguranca.conf`); atualizações automáticas de segurança.
- Scanner de malware da Hostinger (Monarx) instalado no host. Falta um monitor externo de disponibilidade (ex.: UptimeRobot).
- Não há mais n8n/Baserow/OpenClaw na VPS. O subdomínio `dp.minhaebd.cloud` **não** é desta VPS (aponta para outro IP).

## Regras do domínio
- Ano dividido em 4 trimestres fixos (jan–mar, abr–jun, jul–set, out–dez). Criar trimestre via
  `POST /api/trimestres/` já gera os domingos.
- A chamada lista os alunos **matriculados na turma naquele trimestre** (`matriculas.trimestre_id`).
  Trimestre novo sem matrículas = chamada vazia.
- Virada de trimestre: botão "Gerar Próximo Trimestre" (Cadastros → Trimestres, `POST /api/trimestres/proximo`)
  cria o seguinte ao mais recente, com domingos, e copia as matrículas ativas do último trimestre que tem matrículas.
- `GET /api/trimestres/ativo` (padrão da chamada) prefere o trimestre que contém a data de hoje,
  então gerar o próximo com antecedência não muda a chamada antes da hora.
- Troca de turma: professor pede na chamada (botão ⇄), admin aprova em Cadastros → Solicitações
  (`/api/trocas`). Aprovar ou editar a turma direto na aba Alunos usa `mover_matriculas`: muda do
  trimestre atual em diante; trimestres anteriores e chamadas antigas ficam na turma antiga.

## Direção do produto
- Objetivo: vender para outras igrejas. Hoje é **uma instalação por igreja** (próprio domínio, banco e container) — ainda
  não é multi-tenant. Evitar soluções que amarrem o código a uma igreja só.
- Já existe a tela "Configurações da Igreja" (nome, nome curto do app, logo com upload e cor principal), com ícones do PWA
  gerados a partir do logo e arquivos guardados no volume `/data`.
- Próximo: multi-igreja numa única VPS e um único Postgres (coluna `igreja_id` + RLS, subdomínio por igreja).
  Plano e fases em `docs/PLANO_MULTITENANT.md`. Fases 0 (segurança) e 1 (Postgres) estão em produção. A fase 2 (tabela `igrejas`,
  `igreja_id` em todas as tabelas, unicidades por igreja; migration `0002`) está no código, **mas só vale em produção depois do
  deploy** (passos no plano). Por enquanto o app age como uma igreja só: todo dado novo cai na igreja 1. Falta RLS (fase 3).
  A virada SQLite → Postgres está documentada em `docs/VIRADA_POSTGRES.md`.

## Ambiente local
- Projeto em `C:\dev\sistema-ebd` (fora do OneDrive de propósito)
- `git fetch` antes de começar: o GitHub já esteve à frente da cópia local
- No Windows, comandos SSH com heredoc: usar o Bash (o pipe do PowerShell insere BOM)
- Testes: roteiros em `testes/` (`DEBUG=false PYTHONIOENCODING=utf-8 python testes/<arquivo>.py`), por padrão em SQLite
  temporário. Com `TEST_DATABASE_URL=postgresql+asyncpg://...` rodam em Postgres (o schema `public` desse banco é apagado a
  cada execução; usar um banco de teste) e aplicam as migrations do Alembic. `testes/teste_multigreja.py` só roda em Postgres.
- O Docker Desktop não abre neste PC: validar builds de imagem na VPS, em pasta e containers separados da produção.
- O PR é aberto pelo navegador (não há `gh` instalado); o login do GitHub precisa estar feito no painel do navegador do app.
