Vamos continuar o Sistema EBD (C:\dev\sistema-ebd). Leia o CLAUDE.md primeiro e rode `git fetch` + `git status`.

## Onde paramos
Estávamos implementando a tela "Configurações da Igreja" (nome da igreja, nome curto do app, cor principal e
upload do logo, com os ícones do app gerados a partir do logo). Nada disso foi commitado ainda. Último commit: 22b40c6.

### Já feito (não commitado)
- requirements.txt: + python-multipart e pillow (ainda NÃO instalados no .venv local)
- app/config.py: novo `uploads_dir` (padrão ./uploads; em produção deve ser /data/uploads)
- app/armazenamento.py: salvar/caminho/remover arquivos no disco (trocável por bucket no futuro)
- app/models.py: modelo ConfiguracaoIgreja (linha única id=1: nome_igreja, nome_app, cor_primaria, logo_versao)
- app/routers/config_igreja.py: GET /api/config (público), PUT /api/config (admin, valida cor #rrggbb e
  contraste com texto branco), POST/DELETE /api/config/logo (admin; Pillow gera logo.png, icon-192/512,
  maskable-192/512 e apple-touch-icon; fundo vira a cor principal se o logo for claro),
  GET /marca/{arquivo} (com fallback para os ícones padrão) e GET /manifest.json dinâmico
- app/main.py: registra o router novo; REMOVIDA a rota POST /api/seed (estava aberta sem login — falha de
  segurança; o seed segue disponível via `python seed.py`); /docs, /redoc e /openapi.json só com DEBUG;
  removida a rota do manifest estático

### Falta fazer
1. `git rm app/static/manifest.json`; adicionar `UPLOADS_DIR: /data/uploads` no serviço app do
   docker-compose.prod.yml; `.venv/Scripts/python -m pip install -r requirements.txt`.
2. Frontend — script compartilhado app/static/marca.js (carregar antes do script de cada página):
   busca /api/config, guarda em localStorage (offline e sem "piscar"), aplica nome/logo/cor:
   - navbar `.nav-brand span` e `.nav-logo` (hoje "EBD" + ⛪) em chamada, cadastro, aluno, dashboard, fechamento
   - login.html: `.brand-icon` (⛪), h1 "Sistema EBD", rodapé "Sistema EBD · v1.0"
   - `<title>` (sufixo "— Sistema EBD"), meta theme-color, links de ícone → /marca/apple-touch-icon.png e /marca/icon-192.png
   - cor: variáveis --primary, --primary-dark, --primary-light (derivar) + nova --primary-rgb;
     trocar os `rgba(79,70,229,x)` por `rgba(var(--primary-rgb),x)`, e os #4f46e5 fixos
     (chamada.html ~linha 799 impressão; fechamento.html ~122-123 impressão; dashboard.html ~320-330 gráfico via JS)
   - fechamento.html: cabeçalho de impressão "⛪ Escola Bíblica Dominical" e rodapé "Sistema EBD" → nome da igreja
3. Cadastros: nova aba "Igreja" (só admin) com nome, nome do app (máx. 15), seletor de cor, upload do logo
   com prévia de como fica o ícone, e botão "remover logo".
4. app/static/sw.js: /manifest.json, /marca/* e /api/config em network-first (hoje cairiam no cache-first);
   subir CACHE para 'ebd-v4'; incluir /static/marca.js?v=1 no precache.
5. Testes: os roteiros estão em testes/ (copiados da sessão anterior). Rodar com
   `DEBUG=false PYTHONIOENCODING=utf-8 .venv/Scripts/python testes/<arquivo>.py` — teste_rotas,
   teste_trimestre, teste_trocas. Criar testes/teste_config.py: upload PNG/JPG/WEBP, arquivo inválido,
   arquivo > 5 MB, cor clara recusada, permissões (professor 403, sem login 401; GET /api/config público),
   conteúdo do manifest e fallback dos ícones sem logo. Também testar no navegador: testes/servidor_teste.py
   sobe o app na porta 8765 com banco temporário (admin/admin123 só nesse banco local); criar
   .claude/launch.json apontando para ele e apagar ao terminar. Conferir no celular (375px) e no tablet.
6. Commit e me PERGUNTAR antes de publicar. No deploy: backup do banco antes, `git pull` + rebuild
   na VPS, conferir que /data/uploads persiste depois de recriar o container.

## Outras pendências (depois das Configurações)
- Limpeza na VPS: containers certbot sem uso (o renovador é o certbot do host) e o container parado
  sistema-ebd-db-1 (PostgreSQL antigo). Manter o volume sistema-ebd_pgdata por mais um tempo.
- Firewall desligado e Ollama (porta 11434) aberto para a internet — conversar com cuidado, porque n8n e Baserow
  rodam na mesma VPS.
- Opção "Trocar minha senha" para os professores (hoje só o admin troca).
- Lembretes para o Rafael: trocar a senha de admin; conferir o aluno "Samuel Macedo" (parece cadastro de
  teste, ele também é professor da Geração Life); gerar o 1º trimestre de 2027 até o fim de dezembro.
- Decidir se a pasta testes/ entra no git.

Regras: confirmar comigo antes de publicar ou mexer na produção; comandos SSH pelo Bash (não pelo PowerShell).
Quando esta lista estiver concluída, apagar este arquivo (PROXIMA_SESSAO.md).
