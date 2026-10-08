"""Isolamento entre igrejas (fase 3): RLS, papel sem bypass, referências cruzadas e Host -> igreja.

Só roda em Postgres (TEST_DATABASE_URL). Parte 1: direto no banco, com o papel comum do app.
Parte 2: pela API HTTP, com duas igrejas em domínios diferentes.
"""
import asyncio, os, secrets, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

if not _banco.PG:
    print("PULADO: defina TEST_DATABASE_URL=postgresql+asyncpg://... (este teste usa Postgres)")
    sys.exit(0)

import asyncpg
import bcrypt

URL_APP = _banco.url(Path(__file__).parent / "nao_usado.db")  # esquema + papel do app prontos; IGREJA_PADRAO_ID=1
DSN_DONO = _banco._dsn()
DSN_APP = _banco.dsn_app()

TABELAS = ["turmas", "trimestres", "alunos", "professores", "turmas_professores", "matriculas",
           "domingos", "chamadas", "fechamentos_domingo", "usuarios", "ofertas",
           "solicitacoes_troca", "configuracao_igreja"]
REFERENCIAS_ESPERADAS = 20
falhas = []


def check(desc, ok):
    print(f"{'OK  ' if ok else 'ERRO'} {desc}")
    if not ok:
        falhas.append(desc)


async def nega(coro, *tipos):
    """True se a operação foi recusada pelo banco com um dos erros dados."""
    try:
        await coro
        return False
    except tipos:
        return True


class _Savepoint:
    """Cada comando roda num savepoint: um erro esperado não aborta o resto da transação do teste."""

    def __init__(self, c):
        self._c = c

    def __getattr__(self, nome):
        if nome not in ("execute", "fetchval", "fetchrow", "fetch"):
            return getattr(self._c, nome)
        metodo = getattr(self._c, nome)

        async def com_savepoint(*a, **k):
            async with self._c.transaction():
                return await metodo(*a, **k)

        return com_savepoint


class Como:
    """Conexão do papel do app, numa transação, com a igreja definida (ou sem, se igreja=None)."""

    def __init__(self, igreja):
        self.igreja = igreja

    async def __aenter__(self):
        self.c = await asyncpg.connect(DSN_APP)
        self.tx = self.c.transaction()
        await self.tx.start()
        if self.igreja is not None:
            await self.c.execute("select set_config('app.igreja_id', $1, true)", str(self.igreja))
        return _Savepoint(self.c)

    async def __aexit__(self, *a):
        await self.tx.rollback()
        await self.c.close()


async def parte1():
    sup = await asyncpg.connect(DSN_DONO)

    # ── dados de duas igrejas, gravados pelo dono (ignora o RLS) ──
    await sup.execute("update igrejas set dominio_proprio='igreja1.test' where id=1")
    await sup.execute("insert into igrejas (id, nome, subdominio, dominio_proprio) values (2,'Igreja B','igrejab','igrejab.test')")
    await sup.execute("insert into igrejas (id, nome, subdominio, dominio_proprio, ativa) values (3,'Igreja C','igrejac','igrejac.test',false)")
    ids = {}
    for ig in (1, 2):
        ids[ig] = {
            "turma": await sup.fetchval("insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at, igreja_id) values ('Jovens','Jovens',true,now(),now(),$1) returning id", ig),
            "aluno": await sup.fetchval("insert into alunos (nome, ativo, created_at, updated_at, igreja_id) values ('Aluno',true,now(),now(),$1) returning id", ig),
            "tri": await sup.fetchval("insert into trimestres (ano, numero, data_inicio, data_fim, ativo, created_at, igreja_id) values (2026,4,'2026-10-01','2026-12-31',true,now(),$1) returning id", ig),
        }
        ids[ig]["dom"] = await sup.fetchval("insert into domingos (trimestre_id, data, numero, igreja_id) values ($1,'2026-10-04',1,$2) returning id", ids[ig]["tri"], ig)
        ids[ig]["mat"] = await sup.fetchval("insert into matriculas (aluno_id, turma_id, trimestre_id, data_matricula, ativo, igreja_id) values ($1,$2,$3,'2026-10-01',true,$4) returning id", ids[ig]["aluno"], ids[ig]["turma"], ids[ig]["tri"], ig)
        await sup.execute("insert into usuarios (nome, username, senha_hash, role, ativo, created_at, igreja_id) values ('U','u','x','admin',true,now(),$1)", ig)

    # ── o papel do app é comum e não é dono de nada ──
    r = await sup.fetchrow("select rolsuper, rolbypassrls, rolcreaterole, rolcreatedb from pg_roles where rolname=$1", _banco.PAPEL_APP)
    check("papel do app: sem superusuário, sem bypass de RLS, sem criar papel/banco",
          not any([r["rolsuper"], r["rolbypassrls"], r["rolcreaterole"], r["rolcreatedb"]]))
    donos = {x["tableowner"] for x in await sup.fetch("select tableowner from pg_tables where schemaname='public'")}
    check("o papel do app não é dono de nenhuma tabela", _banco.PAPEL_APP not in donos)

    # ── toda tabela de dados está com RLS ligado, forçado e com política (teste que protege tabelas futuras) ──
    todas = [x["relname"] for x in await sup.fetch(
        "select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "where n.nspname='public' and c.relkind='r' and c.relname <> 'alembic_version'")]
    sem = []
    for t in todas:
        info = await sup.fetchrow("select relrowsecurity, relforcerowsecurity from pg_class where relname=$1", t)
        pol = await sup.fetchval("select count(*) from pg_policies where tablename=$1", t)
        if not (info["relrowsecurity"] and info["relforcerowsecurity"] and pol >= 1):
            sem.append(t)
    check(f"todas as {len(todas)} tabelas têm RLS ligado, forçado e política (sem proteção: {sem or 'nenhuma'})", not sem)
    check("alembic_version não é acessível ao app",
          await sup.fetchval("select has_table_privilege($1,'alembic_version','SELECT')", _banco.PAPEL_APP) is False)
    n_gat = await sup.fetchval("select count(*) from pg_trigger where tgname like 'trg_mesma_igreja_%'")
    check(f"{REFERENCIAS_ESPERADAS} gatilhos de referência entre igrejas instalados", n_gat == REFERENCIAS_ESPERADAS)

    # ── igreja 1 enxerga só o que é dela ──
    async with Como(1) as c:
        for t in ("turmas", "alunos", "trimestres", "domingos", "matriculas", "usuarios"):
            n_total = await c.fetchval(f"select count(*) from {t}")
            n_outra = await c.fetchval(f"select count(*) from {t} where igreja_id = 2")
            check(f"igreja 1 em {t}: vê só as suas ({n_total}), nenhuma da igreja 2", n_total == 1 and n_outra == 0)
        check("igreja 1 não lê a turma da igreja 2 nem pelo id", await c.fetchval("select count(*) from turmas where id=$1", ids[2]["turma"]) == 0)
        check("UPDATE em linha de outra igreja não altera nada", (await c.execute("update turmas set nome='HACK' where id=$1", ids[2]["turma"])) == "UPDATE 0")
        check("DELETE em linha de outra igreja não apaga nada", (await c.execute("delete from alunos where id=$1", ids[2]["aluno"])) == "DELETE 0")
        check("INSERT com igreja_id de outra igreja é recusado",
              await nega(c.execute("insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at, igreja_id) values ('X','x',true,now(),now(),2)"), asyncpg.InsufficientPrivilegeError))
    async with Como(1) as c:
        await c.execute("insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at) values ('Sem igreja','x',true,now(),now())")
        check("INSERT sem igreja_id usa a igreja da sessão", await c.fetchval("select igreja_id from turmas where nome='Sem igreja'") == 1)
    async with Como(1) as c:
        check("mudar o igreja_id de uma linha própria para outra igreja é recusado",
              await nega(c.execute("update turmas set igreja_id=2 where id=$1", ids[1]["turma"]), asyncpg.InsufficientPrivilegeError))

    # ── sem igreja definida, nada passa ──
    async with Como(None) as c:
        check("sem app.igreja_id: nenhuma linha visível", await c.fetchval("select count(*) from turmas") == 0 and await c.fetchval("select count(*) from alunos") == 0)
        check("sem app.igreja_id: não grava",
              await nega(c.execute("insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at) values ('X','x',true,now(),now())"),
                         asyncpg.NotNullViolationError, asyncpg.InsufficientPrivilegeError))
    # a variável vale só dentro da transação: não vaza para a próxima nesta mesma conexão (pool)
    c = await asyncpg.connect(DSN_APP)
    async with c.transaction():
        await c.execute("select set_config('app.igreja_id','1',true)")
        dentro = await c.fetchval("select count(*) from turmas")
    fora = await c.fetchval("select count(*) from turmas")
    await c.close()
    check("a igreja da transação não vaza para a transação seguinte", dentro >= 1 and fora == 0)

    # ── igrejas: o app lê só a própria e não escreve ──
    async with Como(1) as c:
        check("tabela igrejas: igreja 1 vê só a própria linha", await c.fetchval("select count(*) from igrejas") == 1)
        check("app não consegue criar igreja", await nega(c.execute("insert into igrejas (nome) values ('Pirata')"), asyncpg.InsufficientPrivilegeError))
        check("app não consegue alterar igreja", await nega(c.execute("update igrejas set nome='X' where id=1"), asyncpg.InsufficientPrivilegeError))
        check("app não consegue apagar igreja", await nega(c.execute("delete from igrejas where id=1"), asyncpg.InsufficientPrivilegeError))
    # ── resolução por Host (sem saber a igreja ainda) ──
    async with Como(None) as c:
        res = {h: await c.fetchval("select igreja_por_host($1, 'minhaebd.cloud')", h)
               for h in ("igreja1.test", "IGREJAB.test", "igrejab.minhaebd.cloud", "igrejac.test", "igrejac.minhaebd.cloud", "desconhecida.test", "")}
    check("Host -> igreja: domínio próprio (igreja1.test=1, IGREJAB.test=2) e subdomínio (igrejab.minhaebd.cloud=2)",
          res["igreja1.test"] == 1 and res["IGREJAB.test"] == 2 and res["igrejab.minhaebd.cloud"] == 2)
    check("Host de igreja inativa = 0 (suspensa); host desconhecido e vazio = NULL",
          res["igrejac.test"] == 0 and res["igrejac.minhaebd.cloud"] == 0 and res["desconhecida.test"] is None and res[""] is None)

    # ── referência entre igrejas: o gatilho barra ──
    async with Como(1) as c:
        check("matrícula da igreja 1 com aluno da igreja 2 é recusada",
              await nega(c.execute("insert into matriculas (aluno_id, turma_id, trimestre_id, data_matricula, ativo) values ($1,$2,$3,'2026-10-01',true)",
                                   ids[2]["aluno"], ids[1]["turma"], ids[1]["tri"]), asyncpg.ForeignKeyViolationError))
        check("domingo da igreja 1 num trimestre da igreja 2 é recusado",
              await nega(c.execute("insert into domingos (trimestre_id, data, numero) values ($1,'2026-10-11',2)", ids[2]["tri"]), asyncpg.ForeignKeyViolationError))
        check("mudar a matrícula própria para o aluno de outra igreja é recusado",
              await nega(c.execute("update matriculas set aluno_id=$1 where id=$2", ids[2]["aluno"], ids[1]["mat"]), asyncpg.ForeignKeyViolationError))
    check("o gatilho vale até para o dono do banco (backup/restauração não passam por cima)",
          await nega(sup.execute("insert into matriculas (aluno_id, turma_id, trimestre_id, data_matricula, ativo, igreja_id) values ($1,$2,$3,'2026-10-01',true,1)",
                                 ids[2]["aluno"], ids[1]["turma"], ids[1]["tri"]), asyncpg.ForeignKeyViolationError))
    async with Como(1) as c:
        await c.execute("insert into alunos (nome, ativo, created_at, updated_at) values ('Outro',true,now(),now())")
        novo = await c.fetchval("select id from alunos where nome='Outro'")
        await c.execute("insert into matriculas (aluno_id, turma_id, trimestre_id, data_matricula, ativo) values ($1,$2,$3,'2026-10-01',true)", novo, ids[1]["turma"], ids[1]["tri"])
        check("referência dentro da mesma igreja continua funcionando", await c.fetchval("select count(*) from matriculas where aluno_id=$1", novo) == 1)

    # ── o dono (backup) enxerga tudo ──
    check("o dono do banco enxerga as duas igrejas (necessário para o pg_dump)",
          await sup.fetchval("select count(distinct igreja_id) from turmas") >= 2)
    await sup.close()


async def parte2():
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    os.chdir(str(Path(__file__).resolve().parent.parent / "app"))
    os.environ.update(DEBUG="false", SECRET_KEY=secrets.token_hex(16), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DATABASE_URL=URL_APP)
    from config import settings
    from main import app
    import tenant

    senha = "senha-de-teste-" + secrets.token_hex(4)
    hash_ = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()
    sup = await asyncpg.connect(DSN_DONO)
    await sup.execute("delete from usuarios")  # parte 1 deixou usuários de teste; recomeça limpo
    await sup.execute("update igrejas set ativa=true where id in (1,2)")
    for ig in (1, 2):
        await sup.execute("insert into usuarios (nome, username, senha_hash, role, ativo, created_at, igreja_id) values ('Admin','admin',$1,'admin',true,now(),$2)", hash_, ig)
    await sup.execute("delete from alunos; delete from turmas; delete from matriculas")
    tenant.limpar_cache()

    def cliente(host):
        # erro interno vira resposta 500 (em vez de levantar no teste): alguns "não pode" do app ainda são 500
        return TestClient(app, base_url=f"http://{host}", raise_server_exceptions=False)

    def login(cli):
        r = cli.post("/api/auth/login", json={"username": "admin", "senha": senha})
        assert r.status_code == 200, (r.status_code, r.text)
        return cli

    with cliente("igreja1.test") as c1, cliente("igrejab.test") as c2:
        login(c1); login(c2)
        check("o mesmo usuário 'admin' existe nas duas igrejas e cada um entra na sua", True)

        t1 = c1.post("/api/turmas/", json={"nome": "Jovens", "faixa_etaria": "Jovens"})
        a1 = c1.post("/api/alunos/", json={"nome": "Aluno da igreja 1"})
        check("igreja 1 cria turma e aluno pela API", t1.status_code in (200, 201) and a1.status_code in (200, 201))
        check("igreja 2 não vê a turma nem o aluno da igreja 1 (lista vazia)",
              c2.get("/api/turmas/").json() == [] and c2.get("/api/alunos/").json() == [])
        t2 = c2.post("/api/turmas/", json={"nome": "Jovens", "faixa_etaria": "Jovens"})
        check("igreja 2 pode ter uma turma com o mesmo nome 'Jovens'", t2.status_code in (200, 201))
        check("cada igreja vê exatamente 1 turma",
              len(c1.get("/api/turmas/").json()) == 1 and len(c2.get("/api/turmas/").json()) == 1)
        check("igreja 1 continua sem poder repetir a própria turma",
              c1.post("/api/turmas/", json={"nome": "Jovens", "faixa_etaria": "Jovens"}).status_code >= 400)

        # ataque: usar dados/identificadores de uma igreja na outra
        id_aluno1 = a1.json()["id"]
        r = c2.delete(f"/api/alunos/{id_aluno1}")
        existe = await sup.fetchval("select count(*) from alunos where id=$1 and ativo", id_aluno1)
        check("igreja 2 não consegue apagar/inativar aluno da igreja 1 (id adivinhado)", r.status_code in (403, 404) and existe == 1)
        r = c2.post("/api/matriculas/", json={"aluno_id": id_aluno1, "turma_id": t2.json()["id"], "trimestre_id": 1})
        check("igreja 2 não consegue matricular aluno da igreja 1", r.status_code >= 400)

        # token de uma igreja não vale na outra
        token1 = c1.cookies.get("access_token")
        outro = cliente("igrejab.test")
        r = outro.get("/api/auth/me", headers={"Authorization": f"Bearer {token1}"})
        check("token da igreja 1 usado no domínio da igreja 2 não autentica", r.status_code == 401)

    # ── Host -> igreja ──
    with cliente("www.igrejab.test") as c:
        check("www.<domínio> cai na mesma igreja do domínio", c.get("/login.html").status_code == 200 and c.get("/api/turmas/").status_code == 401)
    settings.igreja_padrao_id = None
    tenant.limpar_cache()
    with cliente("desconhecida.test") as c:
        check("Host desconhecido (sem igreja padrão): 404", c.get("/login.html").status_code == 404 and c.get("/api/turmas/").status_code == 404)
        check("/healthz responde em qualquer host (saúde do container)", c.get("/healthz").status_code == 200)
    with cliente("igrejac.test") as c:
        check("igreja inativa (suspensa): 403", c.get("/login.html").status_code == 403)
    settings.igreja_padrao_id = 1
    tenant.limpar_cache()
    with cliente("desconhecida.test") as c:
        check("instalação de uma igreja só (igreja padrão definida): host desconhecido cai nela", c.get("/login.html").status_code == 200)
    await sup.close()


async def main():
    await parte1()
    await parte2()


asyncio.run(main())
print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\nFALHARAM {len(falhas)}: {falhas}")
sys.exit(1 if falhas else 0)
