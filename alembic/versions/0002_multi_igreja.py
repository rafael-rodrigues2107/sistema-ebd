"""multi-igreja: tabela igrejas, igreja_id em todas as tabelas e unicidades por igreja

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08

Os dados existentes passam a pertencer à igreja 1. O padrão de `igreja_id` continua 1
(server_default) até a fase 3, que troca o padrão pela sessão do banco e liga o RLS.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABELAS = [
    "turmas", "trimestres", "alunos", "professores", "turmas_professores", "matriculas",
    "domingos", "chamadas", "fechamentos_domingo", "usuarios", "ofertas",
    "solicitacoes_troca", "configuracao_igreja",
]


def upgrade() -> None:
    op.create_table(
        "igrejas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("subdominio", sa.String(length=63), nullable=True, comment="igreja.minhaebd.cloud -> 'igreja'"),
        sa.Column("dominio_proprio", sa.String(length=253), nullable=True, comment="domínio próprio do cliente, se houver"),
        sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subdominio"),
        sa.UniqueConstraint("dominio_proprio"),
    )
    # A instalação existente vira a igreja 1 (nome vem da configuração, se já houver)
    op.execute(
        "INSERT INTO igrejas (id, nome) VALUES "
        "(1, COALESCE((SELECT nome_igreja FROM configuracao_igreja WHERE nome_igreja IS NOT NULL LIMIT 1), 'Igreja principal'))"
    )
    op.execute("SELECT setval(pg_get_serial_sequence('igrejas', 'id'), 1)")  # próxima igreja = 2

    for t in TABELAS:
        op.add_column(t, sa.Column("igreja_id", sa.Integer(), nullable=False, server_default="1"))
        op.create_foreign_key(f"fk_{t}_igreja", t, "igrejas", ["igreja_id"], ["id"])
        op.create_index(f"ix_{t}_igreja_id", t, ["igreja_id"])

    # Unicidade passa a valer dentro de cada igreja
    op.drop_constraint("turmas_nome_key", "turmas", type_="unique")
    op.create_unique_constraint("uq_turma_igreja_nome", "turmas", ["igreja_id", "nome"])
    op.drop_constraint("uq_trimestre_ano_numero", "trimestres", type_="unique")
    op.create_unique_constraint("uq_trimestre_igreja_ano_numero", "trimestres", ["igreja_id", "ano", "numero"])
    op.drop_constraint("usuarios_username_key", "usuarios", type_="unique")
    op.create_unique_constraint("uq_usuario_igreja_username", "usuarios", ["igreja_id", "username"])
    op.create_unique_constraint("uq_configuracao_igreja", "configuracao_igreja", ["igreja_id"])


def downgrade() -> None:
    # Falha (de propósito) se já houver nomes/usernames repetidos entre igrejas diferentes.
    op.drop_constraint("uq_configuracao_igreja", "configuracao_igreja", type_="unique")
    op.drop_constraint("uq_usuario_igreja_username", "usuarios", type_="unique")
    op.create_unique_constraint("usuarios_username_key", "usuarios", ["username"])
    op.drop_constraint("uq_trimestre_igreja_ano_numero", "trimestres", type_="unique")
    op.create_unique_constraint("uq_trimestre_ano_numero", "trimestres", ["ano", "numero"])
    op.drop_constraint("uq_turma_igreja_nome", "turmas", type_="unique")
    op.create_unique_constraint("turmas_nome_key", "turmas", ["nome"])

    for t in reversed(TABELAS):
        op.drop_index(f"ix_{t}_igreja_id", table_name=t)
        op.drop_constraint(f"fk_{t}_igreja", t, type_="foreignkey")
        op.drop_column(t, "igreja_id")
    op.drop_table("igrejas")
