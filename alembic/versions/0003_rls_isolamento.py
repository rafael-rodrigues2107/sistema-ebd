"""isolamento entre igrejas: RLS, padrão de igreja_id pela sessão, gatilhos de referência e resolução por host

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08

- Liga RLS (ENABLE + FORCE) nas 13 tabelas de dados: só enxergam/gravam linhas da igreja
  indicada em `app.igreja_id` (definido pelo app a cada transação). Sem a variável, nada passa.
- `igreja_id` passa a ter como padrão a igreja da sessão (some o padrão fixo 1 da fase 2).
- `igrejas`: o papel do app só lê a própria linha.
- Gatilhos impedem uma linha apontar para linha de OUTRA igreja (a FK simples não percebe isso).
- Função `igreja_por_host` (SECURITY DEFINER) resolve o Host antes de saber a igreja.

Superusuário (dono do banco, backups) ignora o RLS por definição. O app deve conectar com um papel
comum, criado por scripts/provisionar_papel_app.py.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABELAS = [
    "turmas", "trimestres", "alunos", "professores", "turmas_professores", "matriculas",
    "domingos", "chamadas", "fechamentos_domingo", "usuarios", "ofertas",
    "solicitacoes_troca", "configuracao_igreja",
]

IGREJA_ATUAL = "NULLIF(current_setting('app.igreja_id', true), '')::integer"

# (tabela filha, coluna, tabela pai): toda referência precisa ser para uma linha da MESMA igreja
REFERENCIAS = [
    ("turmas_professores", "turma_id", "turmas"),
    ("turmas_professores", "professor_id", "professores"),
    ("turmas_professores", "trimestre_id", "trimestres"),
    ("matriculas", "aluno_id", "alunos"),
    ("matriculas", "turma_id", "turmas"),
    ("matriculas", "trimestre_id", "trimestres"),
    ("domingos", "trimestre_id", "trimestres"),
    ("chamadas", "domingo_id", "domingos"),
    ("chamadas", "turma_id", "turmas"),
    ("chamadas", "aluno_id", "alunos"),
    ("fechamentos_domingo", "domingo_id", "domingos"),
    ("fechamentos_domingo", "turma_id", "turmas"),
    ("usuarios", "turma_id", "turmas"),
    ("ofertas", "domingo_id", "domingos"),
    ("ofertas", "turma_id", "turmas"),
    ("solicitacoes_troca", "aluno_id", "alunos"),
    ("solicitacoes_troca", "turma_origem_id", "turmas"),
    ("solicitacoes_troca", "turma_destino_id", "turmas"),
    ("solicitacoes_troca", "solicitante_id", "usuarios"),
    ("solicitacoes_troca", "decidido_por_id", "usuarios"),
]


def _nome_gatilho(tabela: str, coluna: str) -> str:
    return f"trg_mesma_igreja_{tabela}_{coluna}"


def upgrade() -> None:
    # ── resolução do tenant pelo Host (roda como dono; o papel do app só executa) ──
    op.execute(
        """
        CREATE FUNCTION igreja_por_host(h text, base text) RETURNS integer
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT CASE WHEN i.ativa THEN i.id ELSE 0 END
              FROM igrejas i
             WHERE lower(i.dominio_proprio) = lower(h)
                OR (base <> '' AND lower(h) = lower(i.subdominio) || '.' || lower(base))
             ORDER BY (lower(i.dominio_proprio) = lower(h)) DESC NULLS LAST
             LIMIT 1
        $$
        """
    )

    # ── gatilho genérico: a linha e o que ela referencia são da mesma igreja ──
    op.execute(
        """
        CREATE FUNCTION checar_mesma_igreja() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE
            coluna text := TG_ARGV[0];
            pai    text := TG_ARGV[1];
            valor  integer;
            igreja_do_pai integer;
        BEGIN
            EXECUTE format('SELECT ($1).%I', coluna) INTO valor USING NEW;
            IF valor IS NULL THEN
                RETURN NEW;
            END IF;
            EXECUTE format('SELECT igreja_id FROM %I WHERE id = $1', pai) INTO igreja_do_pai USING valor;
            IF igreja_do_pai IS DISTINCT FROM NEW.igreja_id THEN
                RAISE EXCEPTION 'referência entre igrejas diferentes: %.% -> %', TG_TABLE_NAME, coluna, pai
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    for tabela, coluna, pai in REFERENCIAS:
        op.execute(
            f"CREATE TRIGGER {_nome_gatilho(tabela, coluna)} "
            f"BEFORE INSERT OR UPDATE OF {coluna}, igreja_id ON {tabela} "
            f"FOR EACH ROW EXECUTE FUNCTION checar_mesma_igreja('{coluna}', '{pai}')"
        )

    # ── RLS + padrão do igreja_id vindo da sessão ──
    for t in TABELAS:
        op.execute(f"ALTER TABLE {t} ALTER COLUMN igreja_id SET DEFAULT {IGREJA_ATUAL}")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY isolamento_igreja ON {t} "
            f"USING (igreja_id = {IGREJA_ATUAL}) WITH CHECK (igreja_id = {IGREJA_ATUAL})"
        )

    # `igrejas`: o app só enxerga a própria igreja (escrever é coisa do dono, via ferramenta própria)
    op.execute("ALTER TABLE igrejas ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE igrejas FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY propria_igreja ON igrejas FOR SELECT USING (id = {IGREJA_ATUAL})")


def downgrade() -> None:
    op.execute("DROP POLICY propria_igreja ON igrejas")
    op.execute("ALTER TABLE igrejas NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE igrejas DISABLE ROW LEVEL SECURITY")
    for t in reversed(TABELAS):
        op.execute(f"DROP POLICY isolamento_igreja ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} ALTER COLUMN igreja_id SET DEFAULT 1")
    for tabela, coluna, _pai in REFERENCIAS:
        op.execute(f"DROP TRIGGER {_nome_gatilho(tabela, coluna)} ON {tabela}")
    op.execute("DROP FUNCTION checar_mesma_igreja()")
    op.execute("DROP FUNCTION igreja_por_host(text, text)")
