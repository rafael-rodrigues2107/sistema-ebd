# Sistema EBD

Sistema de chamada e gestão da Escola Bíblica Dominical: chamada pelos professores no celular (PWA com modo offline), cadastro, fechamento de domingo e dashboard.

## Stack
- Backend: FastAPI + SQLAlchemy async (`app/`), entrada em `app/main.py`, rotas em `app/routers/`
- Frontend: HTML estático em `app/static/` (servido pelo FastAPI; `/` é a tela de chamada)
- Banco: SQLite (`DATABASE_URL`, padrão em `app/config.py`)
- Login com perfis `admin` e `professor` (professor só vê a própria turma)

## Produção (VPS Hostinger)
- Site: https://minhaebd.cloud — servidor `root@72.61.62.199`, código em `/opt/sistema-ebd`
- Sobe com `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app`
- Containers: `sistema-ebd-app-1` (FastAPI) e `sistema-ebd-nginx-1` (HTTPS)
- Banco de produção: SQLite em `/data/ebd.db` (volume `sistema-ebd_ebd_data`)
- `.env.prod` só existe no servidor (SECRET_KEY) — nunca versionar
- Certificado: certbot instalado no host (timer systemd, webroot no volume `sistema-ebd_certbot_www`);
  o hook `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx-ebd.sh` recarrega o nginx após renovar
- A VPS também roda n8n, Baserow e Ollama (não fazem parte deste projeto); firewall (ufw) desligado

## Regras do domínio
- Ano dividido em 4 trimestres fixos (jan–mar, abr–jun, jul–set, out–dez). Criar trimestre via
  `POST /api/trimestres/` já gera os domingos.
- A chamada lista os alunos **matriculados na turma naquele trimestre** (`matriculas.trimestre_id`).
  Trimestre novo sem matrículas = chamada vazia.

## Ambiente local
- Projeto em `C:\dev\sistema-ebd` (fora do OneDrive de propósito)
- `git fetch` antes de começar: o GitHub já esteve à frente da cópia local
- No Windows, comandos SSH com heredoc: usar o Bash (o pipe do PowerShell insere BOM)
