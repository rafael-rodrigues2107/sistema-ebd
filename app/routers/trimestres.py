"""
Rotas para Trimestres e Domingos.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno, Domingo, Matricula, Trimestre, Turma, Usuario
from routers.auth import get_current_user, require_admin
from schemas import (
    DomingoCreate,
    DomingoRead,
    ProximoTrimestrePrevia,
    ProximoTrimestreTurma,
    TrimestreCreate,
    TrimestreRead,
)

router = APIRouter(prefix="/api/trimestres", tags=["Trimestres"], dependencies=[Depends(get_current_user)])

# Datas fixas de cada trimestre: numero -> (mes_inicio, dia_inicio, mes_fim, dia_fim)
_FAIXAS = {
    1: (1,  1,  3, 31),
    2: (4,  1,  6, 30),
    3: (7,  1,  9, 30),
    4: (10, 1, 12, 31),
}


def _datas_trimestre(ano: int, numero: int) -> tuple[date, date]:
    m_ini, d_ini, m_fim, d_fim = _FAIXAS[numero]
    return date(ano, m_ini, d_ini), date(ano, m_fim, d_fim)


def _domingos_no_periodo(inicio: date, fim: date) -> list[date]:
    """Retorna todas as datas que caem num domingo dentro do intervalo [inicio, fim]."""
    # weekday(): segunda=0 … domingo=6
    dias_ate_domingo = (6 - inicio.weekday()) % 7
    primeiro_domingo = inicio + timedelta(days=dias_ate_domingo)
    domingos = []
    d = primeiro_domingo
    while d <= fim:
        domingos.append(d)
        d += timedelta(weeks=1)
    return domingos


def _seguinte(ano: int, numero: int) -> tuple[int, int]:
    return (ano, numero + 1) if numero < 4 else (ano + 1, 1)


async def _verificar_duplicado(session: AsyncSession, ano: int, numero: int) -> None:
    duplicado = await session.execute(
        select(Trimestre).where(Trimestre.ano == ano, Trimestre.numero == numero)
    )
    if duplicado.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{ano} / {numero}º trimestre já está cadastrado.",
        )


async def _criar_com_domingos(session: AsyncSession, ano: int, numero: int, ativo: bool) -> Trimestre:
    """Cria o trimestre com todos os seus domingos (sem commit)."""
    data_inicio, data_fim = _datas_trimestre(ano, numero)
    trimestre = Trimestre(ano=ano, numero=numero, data_inicio=data_inicio, data_fim=data_fim, ativo=ativo)
    session.add(trimestre)
    await session.flush()  # garante trimestre.id antes de criar os domingos

    for numero_aula, data in enumerate(_domingos_no_periodo(data_inicio, data_fim), start=1):
        session.add(Domingo(trimestre_id=trimestre.id, data=data, numero=numero_aula))
    return trimestre


async def _plano_proximo(session: AsyncSession):
    """
    Próximo trimestre = o seguinte ao mais recente cadastrado.
    Matrículas vêm do trimestre mais recente que tenha alguma matrícula ativa
    (só alunos e turmas ativos).
    """
    ultimo = (await session.execute(
        select(Trimestre).order_by(Trimestre.ano.desc(), Trimestre.numero.desc()).limit(1)
    )).scalar_one_or_none()
    if not ultimo:
        raise HTTPException(400, "Nenhum trimestre cadastrado. Cadastre o primeiro manualmente.")
    ano, numero = _seguinte(ultimo.ano, ultimo.numero)

    origem = (await session.execute(
        select(Trimestre)
        .join(Matricula, Matricula.trimestre_id == Trimestre.id)
        .where(Matricula.ativo == True)
        .order_by(Trimestre.ano.desc(), Trimestre.numero.desc())
        .limit(1)
    )).scalar_one_or_none()

    matriculas = []
    if origem:
        matriculas = (await session.execute(
            select(Matricula.aluno_id, Matricula.turma_id, Turma.nome)
            .join(Aluno, Matricula.aluno_id == Aluno.id)
            .join(Turma, Matricula.turma_id == Turma.id)
            .where(
                Matricula.trimestre_id == origem.id,
                Matricula.ativo == True,
                Aluno.ativo == True,
                Turma.ativo == True,
            )
            .order_by(Turma.nome)
        )).all()
    return ano, numero, origem, matriculas


# ── Trimestres ─────────────────────────────────────────────────────────────

@router.get("/", response_model=list[TrimestreRead])
async def listar_trimestres(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Trimestre).order_by(Trimestre.ano.desc(), Trimestre.numero.desc())
    )
    return result.scalars().all()


async def trimestre_atual(session: AsyncSession) -> Trimestre | None:
    """
    O ativo que contém a data de hoje; sem nenhum em andamento, o ativo mais
    recente. Assim, gerar o próximo trimestre com antecedência não muda a
    chamada antes da hora.
    """
    hoje = date.today()
    base = select(Trimestre).where(Trimestre.ativo == True).order_by(
        Trimestre.ano.desc(), Trimestre.numero.desc()
    ).limit(1)
    trimestre = (await session.execute(
        base.where(Trimestre.data_inicio <= hoje, Trimestre.data_fim >= hoje)
    )).scalar_one_or_none()
    return trimestre or (await session.execute(base)).scalar_one_or_none()


@router.get("/ativo", response_model=TrimestreRead)
async def trimestre_ativo(session: AsyncSession = Depends(get_session)):
    """Trimestre padrão dos dropdowns (ver `trimestre_atual`)."""
    trimestre = await trimestre_atual(session)
    if not trimestre:
        raise HTTPException(status_code=404, detail="Nenhum trimestre ativo encontrado")
    return trimestre


@router.post("/", response_model=TrimestreRead, status_code=status.HTTP_201_CREATED)
async def criar_trimestre(
    body: TrimestreCreate,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await _verificar_duplicado(session, body.ano, body.numero)
    trimestre = await _criar_com_domingos(session, body.ano, body.numero, body.ativo)
    await session.commit()
    await session.refresh(trimestre)
    return trimestre


@router.get("/proximo", response_model=ProximoTrimestrePrevia)
async def previa_proximo_trimestre(
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Mostra o que será criado ao gerar o próximo trimestre (não grava nada)."""
    ano, numero, origem, matriculas = await _plano_proximo(session)
    data_inicio, data_fim = _datas_trimestre(ano, numero)

    por_turma: dict[str, int] = {}
    for m in matriculas:
        por_turma[m.nome] = por_turma.get(m.nome, 0) + 1

    return ProximoTrimestrePrevia(
        ano=ano,
        numero=numero,
        data_inicio=data_inicio,
        data_fim=data_fim,
        total_domingos=len(_domingos_no_periodo(data_inicio, data_fim)),
        origem=TrimestreRead.model_validate(origem) if origem else None,
        total_matriculas=len(matriculas),
        turmas=[ProximoTrimestreTurma(turma_nome=n, total=t) for n, t in por_turma.items()],
    )


@router.post("/proximo", response_model=TrimestreRead, status_code=status.HTTP_201_CREATED)
async def gerar_proximo_trimestre(
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Cria o próximo trimestre com domingos e copia as matrículas ativas."""
    ano, numero, origem, matriculas = await _plano_proximo(session)
    await _verificar_duplicado(session, ano, numero)

    trimestre = await _criar_com_domingos(session, ano, numero, ativo=True)
    for m in matriculas:
        session.add(Matricula(
            aluno_id=m.aluno_id,
            turma_id=m.turma_id,
            trimestre_id=trimestre.id,
            data_matricula=trimestre.data_inicio,
        ))

    await session.commit()
    await session.refresh(trimestre)
    return trimestre


# ── Domingos ───────────────────────────────────────────────────────────────

@router.get("/{trimestre_id}/domingos", response_model=list[DomingoRead])
async def listar_domingos(
    trimestre_id: int, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(Domingo)
        .where(Domingo.trimestre_id == trimestre_id)
        .order_by(Domingo.numero)
    )
    return result.scalars().all()


@router.post(
    "/{trimestre_id}/domingos",
    response_model=DomingoRead,
    status_code=status.HTTP_201_CREATED,
)
async def criar_domingo(
    trimestre_id: int,
    body: DomingoCreate,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    trimestre = await session.get(Trimestre, trimestre_id)
    if not trimestre:
        raise HTTPException(status_code=404, detail="Trimestre não encontrado")

    domingo = Domingo(trimestre_id=trimestre_id, **body.model_dump())
    session.add(domingo)
    await session.commit()
    await session.refresh(domingo)
    return domingo
