"""
Schemas Pydantic — validação de requests e responses da API.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# Turma
# ═══════════════════════════════════════════════════════════════════════════
class TurmaCreate(BaseModel):
    nome: str = Field(..., max_length=120, examples=["Adultos"])
    faixa_etaria: str = Field(..., max_length=60, examples=["Adultos"])
    descricao: Optional[str] = None


class TurmaRead(BaseModel):
    id: int
    nome: str
    faixa_etaria: str
    descricao: Optional[str] = None
    ativo: bool

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Trimestre
# ═══════════════════════════════════════════════════════════════════════════
class TrimestreCreate(BaseModel):
    ano: int = Field(..., ge=2020, le=2100)
    numero: int = Field(..., ge=1, le=4)
    data_inicio: date
    data_fim: date


class TrimestreRead(BaseModel):
    id: int
    ano: int
    numero: int
    data_inicio: date
    data_fim: date
    ativo: bool

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Domingo
# ═══════════════════════════════════════════════════════════════════════════
class DomingoCreate(BaseModel):
    data: date
    numero: int = Field(..., ge=1)
    tema_licao: Optional[str] = None


class DomingoRead(BaseModel):
    id: int
    trimestre_id: int
    data: date
    numero: int
    tema_licao: Optional[str] = None

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Aluno
# ═══════════════════════════════════════════════════════════════════════════
class AlunoCreate(BaseModel):
    nome: str = Field(..., max_length=200)
    data_nascimento: Optional[date] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    endereco: Optional[str] = None


class AlunoRead(BaseModel):
    id: int
    nome: str
    telefone: Optional[str] = None
    ativo: bool

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Matrícula
# ═══════════════════════════════════════════════════════════════════════════
class MatriculaCreate(BaseModel):
    aluno_id: int
    turma_id: int
    trimestre_id: int


class MatriculaRead(BaseModel):
    id: int
    aluno_id: int
    turma_id: int
    trimestre_id: int
    ativo: bool

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Chamada (request / response)
# ═══════════════════════════════════════════════════════════════════════════
class ChamadaAlunoItem(BaseModel):
    """Presença de um aluno matriculado."""
    aluno_id: int
    presente: bool = False
    trouxe_biblia: bool = False
    trouxe_revista: bool = False


class ChamadaVisitanteItem(BaseModel):
    """Registro de um visitante."""
    nome: str = Field(..., max_length=200)
    presente: bool = True


class ChamadaRead(BaseModel):
    id: int
    domingo_id: int
    turma_id: int
    aluno_id: Optional[int] = None
    nome_visitante: Optional[str] = None
    presente: bool
    trouxe_biblia: bool
    trouxe_revista: bool

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Fechamento Domingo
# ═══════════════════════════════════════════════════════════════════════════
class FechamentoCreate(BaseModel):
    total_matriculados: int = 0
    total_presentes: int = 0
    total_visitantes: int = 0
    total_ausentes: int = 0
    total_biblias: int = 0
    total_revistas: int = 0
    valor_ofertas: Decimal = Field(default=0, max_digits=10, decimal_places=2)
    observacoes: Optional[str] = None


class FechamentoRead(BaseModel):
    id: int
    domingo_id: int
    turma_id: int
    total_matriculados: int
    total_presentes: int
    total_visitantes: int
    total_ausentes: int
    total_biblias: int
    total_revistas: int
    valor_ofertas: Decimal
    observacoes: Optional[str] = None

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Payload composto — Salvar Chamada Completa
# ═══════════════════════════════════════════════════════════════════════════
class SaveChamadaRequest(BaseModel):
    """Corpo do POST para salvar a chamada completa de um domingo."""
    trimestre_id: int
    domingo_id: int
    chamadas: list[ChamadaAlunoItem] = []
    visitantes: list[ChamadaVisitanteItem] = []
    fechamento: FechamentoCreate


# ═══════════════════════════════════════════════════════════════════════════
# Resposta do Painel (GET)
# ═══════════════════════════════════════════════════════════════════════════
class AlunoPainelItem(BaseModel):
    """Item de aluno retornado no painel de chamada."""
    matricula_id: int
    aluno_id: int
    nome: str
    presente: Optional[bool] = None
    trouxe_biblia: Optional[bool] = None
    trouxe_revista: Optional[bool] = None
    chamada_id: Optional[int] = None


class VisitantePainelItem(BaseModel):
    """Visitante já registrado na chamada."""
    chamada_id: int
    nome: str
    presente: bool


class PainelResponse(BaseModel):
    """Resposta completa do endpoint GET /turmas/{id}/painel."""
    turma: TurmaRead
    trimestre: TrimestreRead
    domingo: DomingoRead
    alunos: list[AlunoPainelItem]
    visitantes: list[VisitantePainelItem] = []
    fechamento: Optional[FechamentoRead] = None
