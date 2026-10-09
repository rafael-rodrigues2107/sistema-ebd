"""usuarios.trocar_senha: senha temporária (criada/redefinida pelo dono) obriga a troca no primeiro login

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("trocar_senha", sa.Boolean(), nullable=False, server_default=sa.false(),
                  comment="senha temporária: o usuário só pode trocar a senha até fazê-lo"),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "trocar_senha")
