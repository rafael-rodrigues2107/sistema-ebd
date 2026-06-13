"""
Modelos de banco de dados — Sistema EBD (Escola Bíblica Dominical).

Stack: SQLAlchemy 2.0 (async) com DeclarativeBase.
Banco: PostgreSQL (produção) / SQLite (MVP local).

Relações principais:
  Turma  1──N  Matricula
  Aluno  1──N  Matricula
  Trimestre 1──N  Matricula
  Trimestre 1──N  Domingo
  Domingo 1──N  Chamada
  Domingo 1──N  FechamentoDomingo
  Domingo 1──N  Oferta
  Turma  N──N  Professor  (via turmas_professores)
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Base ────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ═════════════════════════════════════════════════════════════════════════════
# 1. Turma (Classe)
# ═════════════════════════════════════════════════════════════════════════════
class Turma(Base):
    __tablename__ = "turmas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    faixa_etaria: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="Adultos, Jovens, Adolescentes, Juniores, Primários, Maternal, etc."
    )
    descricao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ──
    matriculas: Mapped[list["Matricula"]] = relationship(back_populates="turma", lazy="selectin")
    turmas_professores: Mapped[list["TurmaProfessor"]] = relationship(back_populates="turma", lazy="selectin")
    chamadas: Mapped[list["Chamada"]] = relationship(back_populates="turma", lazy="selectin")
    fechamentos: Mapped[list["FechamentoDomingo"]] = relationship(back_populates="turma", lazy="selectin")
    ofertas: Mapped[list["Oferta"]] = relationship(back_populates="turma", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Turma id={self.id} nome='{self.nome}'>"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Trimestre
# ═════════════════════════════════════════════════════════════════════════════
class Trimestre(Base):
    __tablename__ = "trimestres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ano: Mapped[int] = mapped_column(Integer, nullable=False)
    numero: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="1 a 4 (trimestres do ano)"
    )
    data_inicio: Mapped[date] = mapped_column(nullable=False)
    data_fim: Mapped[date] = mapped_column(nullable=False)
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ano", "numero", name="uq_trimestre_ano_numero"),
        CheckConstraint("numero BETWEEN 1 AND 4", name="ck_trimestre_numero"),
    )

    # ── Relationships ──
    matriculas: Mapped[list["Matricula"]] = relationship(back_populates="trimestre", lazy="selectin")
    domingos: Mapped[list["Domingo"]] = relationship(back_populates="trimestre", lazy="selectin")
    turmas_professores: Mapped[list["TurmaProfessor"]] = relationship(back_populates="trimestre", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Trimestre id={self.id} {self.ano}/{self.numero}>"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Aluno
# ═════════════════════════════════════════════════════════════════════════════
class Aluno(Base):
    __tablename__ = "alunos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    data_nascimento: Mapped[Optional[date]] = mapped_column(nullable=True)
    telefone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    endereco: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ──
    matriculas: Mapped[list["Matricula"]] = relationship(back_populates="aluno", lazy="selectin")
    chamadas: Mapped[list["Chamada"]] = relationship(back_populates="aluno", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Aluno id={self.id} nome='{self.nome}'>"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Professor
# ═════════════════════════════════════════════════════════════════════════════
class Professor(Base):
    __tablename__ = "professores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    telefone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ──
    turmas_professores: Mapped[list["TurmaProfessor"]] = relationship(back_populates="professor", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Professor id={self.id} nome='{self.nome}'>"


# ═════════════════════════════════════════════════════════════════════════════
# 5. TurmaProfessor (N:N com atributos)
# ═════════════════════════════════════════════════════════════════════════════
class TurmaProfessor(Base):
    """Associação N:N entre Turma e Professor, contextualizada por Trimestre."""

    __tablename__ = "turmas_professores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False)
    professor_id: Mapped[int] = mapped_column(ForeignKey("professores.id", ondelete="CASCADE"), nullable=False)
    trimestre_id: Mapped[int] = mapped_column(ForeignKey("trimestres.id", ondelete="CASCADE"), nullable=False)
    funcao: Mapped[str] = mapped_column(
        String(60), nullable=False, default="Professor Titular",
        comment="Professor Titular, Auxiliar, Secretário(a), etc."
    )

    __table_args__ = (
        UniqueConstraint("turma_id", "professor_id", "trimestre_id", name="uq_turma_prof_trim"),
    )

    # ── Relationships ──
    turma: Mapped["Turma"] = relationship(back_populates="turmas_professores")
    professor: Mapped["Professor"] = relationship(back_populates="turmas_professores")
    trimestre: Mapped["Trimestre"] = relationship(back_populates="turmas_professores")

    def __repr__(self) -> str:
        return f"<TurmaProfessor turma={self.turma_id} prof={self.professor_id} trim={self.trimestre_id}>"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Matrícula
# ═════════════════════════════════════════════════════════════════════════════
class Matricula(Base):
    """Aluno matriculado em uma Turma durante um Trimestre."""

    __tablename__ = "matriculas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id", ondelete="CASCADE"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False)
    trimestre_id: Mapped[int] = mapped_column(ForeignKey("trimestres.id", ondelete="CASCADE"), nullable=False)
    data_matricula: Mapped[date] = mapped_column(default=date.today)
    ativo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        UniqueConstraint("aluno_id", "turma_id", "trimestre_id", name="uq_matricula_aluno_turma_trim"),
    )

    # ── Relationships ──
    aluno: Mapped["Aluno"] = relationship(back_populates="matriculas")
    turma: Mapped["Turma"] = relationship(back_populates="matriculas")
    trimestre: Mapped["Trimestre"] = relationship(back_populates="matriculas")

    def __repr__(self) -> str:
        return f"<Matricula aluno={self.aluno_id} turma={self.turma_id} trim={self.trimestre_id}>"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Domingo
# ═════════════════════════════════════════════════════════════════════════════
class Domingo(Base):
    """Cada domingo letivo dentro de um trimestre (≈13 por trimestre)."""

    __tablename__ = "domingos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trimestre_id: Mapped[int] = mapped_column(ForeignKey("trimestres.id", ondelete="CASCADE"), nullable=False)
    data: Mapped[date] = mapped_column(nullable=False)
    numero: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Número sequencial do domingo dentro do trimestre (1º, 2º, …)"
    )
    tema_licao: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        UniqueConstraint("trimestre_id", "data", name="uq_domingo_trim_data"),
        UniqueConstraint("trimestre_id", "numero", name="uq_domingo_trim_numero"),
    )

    # ── Relationships ──
    trimestre: Mapped["Trimestre"] = relationship(back_populates="domingos")
    chamadas: Mapped[list["Chamada"]] = relationship(back_populates="domingo", lazy="selectin")
    fechamentos: Mapped[list["FechamentoDomingo"]] = relationship(back_populates="domingo", lazy="selectin")
    ofertas: Mapped[list["Oferta"]] = relationship(back_populates="domingo", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Domingo id={self.id} data={self.data} nº{self.numero}>"


# ═════════════════════════════════════════════════════════════════════════════
# 8. Chamada (Frequência individual)
# ═════════════════════════════════════════════════════════════════════════════
class Chamada(Base):
    """
    Registro de presença individual por domingo.

    - Para aluno matriculado: `aluno_id` preenchido, `nome_visitante` nulo.
    - Para visitante: `aluno_id` nulo, `nome_visitante` preenchido.
    """

    __tablename__ = "chamadas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domingo_id: Mapped[int] = mapped_column(ForeignKey("domingos.id", ondelete="CASCADE"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False)
    aluno_id: Mapped[Optional[int]] = mapped_column(ForeignKey("alunos.id", ondelete="SET NULL"), nullable=True)
    nome_visitante: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    presente: Mapped[bool] = mapped_column(default=False)
    trouxe_biblia: Mapped[bool] = mapped_column(default=False)
    trouxe_revista: Mapped[bool] = mapped_column(default=False)
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Garante unicidade para aluno matriculado (evita duplicata)
        UniqueConstraint("domingo_id", "turma_id", "aluno_id", name="uq_chamada_aluno"),
        # Garante que visitante não tenha aluno_id e vice-versa
        CheckConstraint(
            "(aluno_id IS NOT NULL AND nome_visitante IS NULL) OR "
            "(aluno_id IS NULL AND nome_visitante IS NOT NULL)",
            name="ck_chamada_aluno_ou_visitante",
        ),
    )

    # ── Relationships ──
    domingo: Mapped["Domingo"] = relationship(back_populates="chamadas")
    turma: Mapped["Turma"] = relationship(back_populates="chamadas")
    aluno: Mapped[Optional["Aluno"]] = relationship(back_populates="chamadas")

    def __repr__(self) -> str:
        pessoa = f"aluno={self.aluno_id}" if self.aluno_id else f"visitante='{self.nome_visitante}'"
        status = "P" if self.presente else "F"
        return f"<Chamada dom={self.domingo_id} {pessoa} {status}>"


# ═════════════════════════════════════════════════════════════════════════════
# 9. Fechamento do Domingo (Módulo 4 — Métricas da Classe)
# ═════════════════════════════════════════════════════════════════════════════
class FechamentoDomingo(Base):
    """
    Métricas consolidadas de uma turma ao final de cada domingo.

    Preenchido pelo secretário/professor. Serve como registro oficial
    e permite auditoria cruzada com os dados de chamada.
    """

    __tablename__ = "fechamentos_domingo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domingo_id: Mapped[int] = mapped_column(ForeignKey("domingos.id", ondelete="CASCADE"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False)

    # ── Contagens ──
    total_matriculados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_presentes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_visitantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_ausentes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # assistencia_total = presentes + visitantes (calculado na query ou via property)

    # ── Materiais ──
    total_biblias: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_revistas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Financeiro ──
    valor_ofertas: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)

    # ── Observações ──
    observacoes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("domingo_id", "turma_id", name="uq_fechamento_dom_turma"),
    )

    # ── Relationships ──
    domingo: Mapped["Domingo"] = relationship(back_populates="fechamentos")
    turma: Mapped["Turma"] = relationship(back_populates="fechamentos")

    @property
    def assistencia_total(self) -> int:
        """Presentes + Visitantes."""
        return self.total_presentes + self.total_visitantes

    def __repr__(self) -> str:
        return (
            f"<Fechamento dom={self.domingo_id} turma={self.turma_id} "
            f"P={self.total_presentes} V={self.total_visitantes} A={self.total_ausentes}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 10. Oferta (registro individual de ofertas/dízimos)
# ═════════════════════════════════════════════════════════════════════════════
class Oferta(Base):
    """Registro de ofertas e dízimos por turma em cada domingo."""

    __tablename__ = "ofertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domingo_id: Mapped[int] = mapped_column(ForeignKey("domingos.id", ondelete="CASCADE"), nullable=False)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tipo: Mapped[str] = mapped_column(
        String(40), nullable=False, default="Oferta",
        comment="Dízimo, Oferta, Missionária, etc."
    )
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # ── Relationships ──
    domingo: Mapped["Domingo"] = relationship(back_populates="ofertas")
    turma: Mapped["Turma"] = relationship(back_populates="ofertas")

    def __repr__(self) -> str:
        return f"<Oferta dom={self.domingo_id} turma={self.turma_id} R$ {self.valor}>"
