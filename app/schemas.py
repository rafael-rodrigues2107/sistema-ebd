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
    ativo: bool = True


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


class MatriculaDetalhadaRead(BaseModel):
    id: int
    aluno_id: int
    aluno_nome: str
    turma_id: int
    turma_nome: str
    trimestre_id: int
    data_matricula: date
    ativo: bool


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
# Autenticação e Usuários
# ═══════════════════════════════════════════════════════════════════════════
class LoginRequest(BaseModel):
    username: str
    senha: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    nome: str
    turma_id: Optional[int] = None


class UsuarioCreate(BaseModel):
    nome: str = Field(..., max_length=200)
    username: str = Field(..., max_length=100)
    senha: str = Field(..., min_length=4)
    role: str = Field(default="professor", pattern="^(admin|professor)$")
    turma_id: Optional[int] = None


class UsuarioRead(BaseModel):
    id: int
    nome: str
    username: str
    role: str
    turma_id: Optional[int]
    turma_nome: Optional[str]
    ativo: bool

    model_config = {"from_attributes": True}


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    username: Optional[str] = None
    senha: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|professor)$")
    turma_id: Optional[int] = None
    ativo: Optional[bool] = None


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard da Liderança
# ═══════════════════════════════════════════════════════════════════════════
class DomingoPresencaItem(BaseModel):
    domingo_numero: int
    domingo_data: date
    total_presentes: int
    total_chamadas: int


class TurmaRankingItem(BaseModel):
    turma_id: int
    turma_nome: str
    media_frequencia: float
    total_domingos_com_chamada: int


class AlunoSumidoItem(BaseModel):
    aluno_id: int
    aluno_nome: str
    telefone: Optional[str]
    turma_nome: str
    faltas_consecutivas: int


class TurmaOfertaItem(BaseModel):
    turma_id: int
    turma_nome: str
    total_ofertas: Decimal


class AlunoNota10Item(BaseModel):
    aluno_id: int
    aluno_nome: str
    turma_nome: str
    total_domingos: int


class DashboardRead(BaseModel):
    trimestre_id: int
    historico_presenca: list[DomingoPresencaItem]
    ranking_turmas: list[TurmaRankingItem]
    alunos_sumidos: list[AlunoSumidoItem]
    total_acumulado_ofertas: Decimal
    ranking_ofertas: list[TurmaOfertaItem]
    campeao_visitantes: Optional[str]
    alunos_nota_10: list[AlunoNota10Item]


# ═══════════════════════════════════════════════════════════════════════════
# Fechamento Consolidado do Dia
# ═══════════════════════════════════════════════════════════════════════════
class TurmaResumoFechamento(BaseModel):
    turma_id: int
    turma_nome: str
    total_matriculados: int
    total_presentes: int
    total_ausentes: int
    total_visitantes: int
    total_biblias: int
    total_revistas: int
    valor_ofertas: Decimal


class FechamentoDiaRead(BaseModel):
    domingo_id: int
    domingo_data: date
    domingo_numero: int
    trimestre_ano: int
    trimestre_numero: int
    total_matriculados_trimestre: int
    total_presentes: int
    total_visitantes: int
    total_biblias: int
    total_revistas: int
    total_ofertas: Decimal
    por_turma: list[TurmaResumoFechamento]


class ConfirmarFechamentoDiaCreate(BaseModel):
    domingo_id: int
    observacoes: Optional[str] = None


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
