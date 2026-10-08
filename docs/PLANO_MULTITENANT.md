# Plano: EBD multi-igreja (1 VPS, 1 Postgres, isolamento por igreja)

Objetivo: várias igrejas no mesmo sistema, na mesma VPS, sem uma ver os dados da outra.
Estado de hoje: 1 app FastAPI + SQLite, 1 igreja, ~3.500 linhas, 13 tabelas, 11 routers,
cerca de 150 pontos de consulta ao banco, `create_all` no startup (sem migrations).

## Decisões de arquitetura

| Tema | Decisão | Motivo |
|---|---|---|
| Banco | PostgreSQL 16 (gratuito), container na própria VPS | `asyncpg` já está no `requirements.txt` |
| Isolamento | Coluna `igreja_id` em toda tabela + **RLS (Row Level Security)** no Postgres | O banco bloqueia o vazamento mesmo se uma query esquecer o filtro |
| Como o RLS sabe a igreja | A cada requisição: `SET LOCAL app.igreja_id = N` na transação | Evita editar ~150 queries: o filtro vem do banco |
| Inserts | `igreja_id` com `DEFAULT current_setting('app.igreja_id')::int` | Os routers não precisam passar o valor |
| Papel do banco | O app conecta com um usuário **sem** `BYPASSRLS` e que não é dono das tabelas | Dono e superusuário ignoram o RLS, então isso é obrigatório |
| Descobrir a igreja | Subdomínio: `igreja.minhaebd.cloud` (curinga `*.minhaebd.cloud`) | Fácil de vender, e permite domínio próprio depois |
| Login | O token JWT passa a levar `igreja_id`; o login só valida usuário dentro da igreja do subdomínio | Um token de uma igreja não vale em outra |
| Arquivos (logos) | `/data/uploads/<igreja_id>/...` | Isola o upload por igreja |
| Painel do dono | Papel `superadmin` (você), fora do RLS, para criar e suspender igrejas | Cadastro de cliente sem mexer no servidor |

## O que muda no código (pontos críticos encontrados)

1. `models.py`: adicionar `igreja_id` em todas as tabelas; nova tabela `igrejas` (id, nome, subdominio, ativa).
2. **Unicidades globais viram por igreja:** `turmas.nome` e `usuarios.username` são `unique` no banco inteiro, e passam a `UNIQUE (igreja_id, ...)`. Os demais `UniqueConstraint` também ganham `igreja_id`.
3. `ConfiguracaoIgreja` hoje é "linha única id=1": passa a ser uma linha por igreja (`UNIQUE igreja_id`). O mesmo vale para `/api/config`, `/manifest.json` e `/marca/...` (nome, cor e ícones do PWA por igreja).
4. `database.py`: `get_session` precisa abrir a transação e executar o `SET LOCAL` com a igreja da requisição. Remover o `pool_size` específico do SQLite e o PRAGMA.
5. `auth.py`: JWT com `igreja_id`; `get_current_user` confere se a igreja do token é a do subdomínio.
6. `seed.py`: hoje cria o usuário **admin / admin123**. Em multi-igreja isso vira "criar admin da nova igreja com senha aleatória/convite". Ver risco de segurança abaixo.
7. `armazenamento.py` e `config_igreja.py`: caminho com `igreja_id`.
8. `sw.js` e o cache do PWA: o cache precisa ser por origem (subdomínio já resolve isso).
9. Trocar `init_db()/create_all` por **Alembic** (já está no `requirements.txt`, mas não há migrations).
10. Testes (`testes/`) usam SQLite: precisam rodar contra Postgres (container de teste) e ganhar o teste de isolamento.

## Fases, com critério de pronto e estimativa

Estimativas para uma pessoa com o Claude; sem contar a validação no dia a dia da igreja.

| Fase | Entrega | Pronto quando | Esforço |
|---|---|---|---|
| 0. Segurança da VPS | Backup diário do `ebd.db` (cópia fora da VPS), ufw 22/80/443, fail2ban, atualizações automáticas de segurança, monitor externo | Restauração de backup testada; alerta chega ao celular | 0,5 a 1 dia |
| 1. Postgres no lugar do SQLite (1 igreja ainda) | Container Postgres, Alembic com a migration inicial, app rodando em Postgres, testes verdes | Site em produção igual ao de hoje, com dados migrados | 1 a 2 dias |
| 2. Estrutura multi-igreja | Tabela `igrejas`, `igreja_id` em tudo, unicidades por igreja, dados atuais viram a "igreja 1" | Migration aplicada em cópia do banco real sem perda | 1 a 2 dias |
| 3. RLS e sessão por igreja | Políticas RLS em todas as tabelas, papel de banco sem bypass, `SET LOCAL` por requisição, defaults de `igreja_id` | **Teste de isolamento passa:** 2 igrejas, todos os endpoints, nenhuma lê ou escreve na outra | 2 a 3 dias |
| 4. Subdomínio, login e marca por igreja | Resolução por Host, JWT com `igreja_id`, config/ícones/manifest/uploads por igreja, certificado curinga | Duas igrejas com cores e logos próprios em subdomínios diferentes | 2 dias |
| 5. Painel do dono | Superadmin: criar igreja (gera subdomínio e admin com convite), suspender, listar uso | Criar uma igreja nova em minutos, sem tocar no servidor | 1 a 2 dias |
| 6. Operação e LGPD | Backup por igreja e restauração individual, exportar e apagar dados de uma igreja, termos e política de privacidade | Restaurar uma igreja sem afetar as outras | 1 a 2 dias |

Total: cerca de 9 a 14 dias de trabalho. A fase 0 deve ser feita antes de qualquer coisa.

## Migração dos dados reais (fase 1 e 2)

1. Backup do `/data/ebd.db` (já existe cópia em `C:\dev\backup-ebd\ebd-backup-20261007.db`).
2. Ensaiar a migração **em cópia**, com um script SQLite → Postgres, na máquina local.
3. Conferir contagens por tabela e amostras (alunos, chamadas, fechamentos) antes e depois.
4. Virada em horário sem chamada (não no domingo de manhã): parar app, migrar, subir, testar, e manter o SQLite antigo como plano de volta por alguns dias.

## Riscos e como mitigar

| Risco | Mitigação |
|---|---|
| Esquecer RLS numa tabela nova | Teste automático que falha se alguma tabela com `igreja_id` não tiver política RLS (o DP Fácil tem teste parecido) |
| App conectando como dono do banco (RLS ignorado) | Teste que confere o papel de conexão e tenta ler dados de outra igreja |
| `SET LOCAL` fora de transação | Sempre dentro de `get_session`; teste de uma requisição sem igreja deve retornar zero linhas |
| Usuário `admin/admin123` criado pelo seed | **Verificar hoje** se a produção ainda usa essa senha e trocá-la. Em multi-igreja, nunca criar senha fixa |
| `SECRET_KEY` comum a todas as igrejas | Aceitável com `igreja_id` assinado no token; manter o segredo só no `.env.prod` |
| Uma igreja pesada afetando as outras | Limites de requisição por igreja no nginx; monitorar uso; plano premium com instalação própria |
| Perda de dados | Backup diário automático fora da VPS e teste de restauração mensal |

## Fora do escopo agora

Cobrança automática (Stripe/Pix), domínio próprio por igreja, app nativo, e-mail/WhatsApp.
Entram depois, quando houver as primeiras igrejas pagantes.

## Próximo passo sugerido

Fase 0 (segurança da VPS e backup) e, em paralelo, a verificação da senha do `admin`.
Depois disso, a fase 1 em uma branch separada, sem tocar na produção até o ensaio de migração passar.
