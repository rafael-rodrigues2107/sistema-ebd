"""Estrutura multi-igreja (fase 2): duas igrejas convivem no mesmo banco e as unicidades valem por igreja.

Só roda em Postgres (TEST_DATABASE_URL), pois exercita a migration 0002 do Alembic.
Isolamento por RLS (quem enxerga o quê) é da fase 3 e terá teste próprio.
"""
import asyncio, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

if not _banco.PG:
    print("PULADO: defina TEST_DATABASE_URL=postgresql+asyncpg://... (este teste usa Postgres)")
    sys.exit(0)

import asyncpg

_banco.url(Path(__file__).parent / "nao_usado.db")  # zera o schema e aplica as migrations
DSN = _banco.PG.replace("postgresql+asyncpg", "postgresql", 1)

TABELAS = ["turmas", "trimestres", "alunos", "professores", "turmas_professores", "matriculas",
           "domingos", "chamadas", "fechamentos_domingo", "usuarios", "ofertas",
           "solicitacoes_troca", "configuracao_igreja"]
falhas = []


def check(desc, ok):
    print(f"{'OK  ' if ok else 'ERRO'} {desc}")
    if not ok:
        falhas.append(desc)


async def deve_falhar(c, sql, *args):
    """Executa e devolve True se o banco recusou por violação de unicidade/chave."""
    try:
        async with c.transaction():
            await c.execute(sql, *args)
        return False
    except (asyncpg.UniqueViolationError, asyncpg.ForeignKeyViolationError):
        return True


async def main():
    c = await asyncpg.connect(DSN)

    # ── Estrutura: toda tabela de dados tem igreja_id NOT NULL com chave para igrejas ──
    for t in TABELAS:
        col = await c.fetchrow(
            "select is_nullable from information_schema.columns where table_name=$1 and column_name='igreja_id'", t)
        fk = await c.fetchval(
            """select count(*) from information_schema.table_constraints tc
               join information_schema.key_column_usage k using (constraint_name, table_name)
               join information_schema.constraint_column_usage u using (constraint_name)
               where tc.table_name=$1 and tc.constraint_type='FOREIGN KEY'
                 and k.column_name='igreja_id' and u.table_name='igrejas'""", t)
        check(f"{t}: igreja_id NOT NULL com FK para igrejas", bool(col) and col["is_nullable"] == "NO" and fk == 1)

    # ── A igreja 1 existe e a segunda recebe o id 2 ──
    check("igreja 1 existe (criada pela migration)", await c.fetchval("select count(*) from igrejas where id=1") == 1)
    i2 = await c.fetchval("insert into igrejas (nome, subdominio) values ('Igreja B', 'igrejab') returning id")
    check("segunda igreja recebe id 2", i2 == 2)
    check("subdomínio repetido é recusado",
          await deve_falhar(c, "insert into igrejas (nome, subdominio) values ('Outra', 'igrejab')"))

    # ── Dados padrão caem na igreja 1 (comportamento atual preservado) ──
    await c.execute("insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at) values ('Jovens','Jovens',true,now(),now())")
    check("insert sem igreja_id vai para a igreja 1",
          await c.fetchval("select igreja_id from turmas where nome='Jovens'") == 1)

    # ── Mesmos nomes em igrejas diferentes: permitido ──
    await c.execute("insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at, igreja_id) values ('Jovens','Jovens',true,now(),now(),2)")
    check("mesma turma 'Jovens' em duas igrejas: ok", await c.fetchval("select count(*) from turmas where nome='Jovens'") == 2)
    await c.execute("insert into trimestres (ano, numero, data_inicio, data_fim, ativo, created_at) values (2026,4,'2026-10-01','2026-12-31',true,now())")
    await c.execute("insert into trimestres (ano, numero, data_inicio, data_fim, ativo, created_at, igreja_id) values (2026,4,'2026-10-01','2026-12-31',true,now(),2)")
    check("mesmo trimestre 2026/4 em duas igrejas: ok", await c.fetchval("select count(*) from trimestres where ano=2026 and numero=4") == 2)
    await c.execute("insert into usuarios (nome, username, senha_hash, role, ativo, created_at) values ('A','maria','x','admin',true,now())")
    await c.execute("insert into usuarios (nome, username, senha_hash, role, ativo, created_at, igreja_id) values ('B','maria','x','admin',true,now(),2)")
    check("mesmo username 'maria' em duas igrejas: ok", await c.fetchval("select count(*) from usuarios where username='maria'") == 2)

    # ── Dentro da mesma igreja continua proibido repetir ──
    check("turma repetida na MESMA igreja é recusada",
          await deve_falhar(c, "insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at, igreja_id) values ('Jovens','Jovens',true,now(),now(),2)"))
    check("trimestre repetido na MESMA igreja é recusado",
          await deve_falhar(c, "insert into trimestres (ano, numero, data_inicio, data_fim, ativo, created_at) values (2026,4,'2026-10-01','2026-12-31',true,now())"))
    check("username repetido na MESMA igreja é recusado",
          await deve_falhar(c, "insert into usuarios (nome, username, senha_hash, role, ativo, created_at) values ('C','maria','x','admin',true,now())"))

    # ── Configuração: uma por igreja ──
    await c.execute("insert into configuracao_igreja (id, nome_igreja, updated_at) values (1,'A',now())")
    await c.execute("insert into configuracao_igreja (id, nome_igreja, updated_at, igreja_id) values (2,'B',now(),2)")
    check("uma configuração por igreja (duas igrejas, duas linhas)", await c.fetchval("select count(*) from configuracao_igreja") == 2)
    check("segunda configuração da MESMA igreja é recusada",
          await deve_falhar(c, "insert into configuracao_igreja (id, nome_igreja, updated_at, igreja_id) values (3,'B2',now(),2)"))

    # ── Integridade: igreja inexistente e igreja com dados não podem ser tratadas à toa ──
    check("igreja_id inexistente é recusado",
          await deve_falhar(c, "insert into turmas (nome, faixa_etaria, ativo, created_at, updated_at, igreja_id) values ('X','x',true,now(),now(),99)"))
    check("apagar igreja que tem dados é recusado",
          await deve_falhar(c, "delete from igrejas where id=2"))
    await c.close()


asyncio.run(main())
print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\nFALHARAM {len(falhas)}: {falhas}")
sys.exit(1 if falhas else 0)
