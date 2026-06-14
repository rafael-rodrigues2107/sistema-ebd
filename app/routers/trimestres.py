"""
Rotas para Trimestres e Domingos.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Domingo, Trimestre
from schemas import (
    DomingoCreate,
    DomingoRead,
    TrimestreCreate,
    TrimestreRead,
)

router = APIRouter(prefix="/api/trimestres", tags=["Trimestres"])

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


# ── Trimestres ─────────────────────────────────────────────────────────────

@router.get("/", response_model=list[TrimestreRead])
async def listar_trimestres(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Trimestre).order_by(Trimestre.ano.desc(), Trimestre.numero.desc())
    )
    return result.scalars().all()


@router.get("/ativo", response_model=TrimestreRead)
async def trimestre_ativo(session: AsyncSession = Depends(get_session)):
    """Retorna o trimestre ativo mais recente (útil para dropdowns)."""
    result = await session.execute(
        select(Trimestre)
        .where(Trimestre.ativo == True)
        .order_by(Trimestre.ano.desc(), Trimestre.numero.desc())
        .limit(1)
    )
    trimestre = result.scalar_one_or_none()
    if not trimestre:
        raise HTTPException(status_code=404, detail="Nenhum trimestre ativo encontrado")
    return trimestre


@router.post("/", response_model=TrimestreRead, status_code=status.HTTP_201_CREATED)
async def criar_trimestre(
    body: TrimestreCreate, session: AsyncSession = Depends(get_session)
):
    # Rejeita duplicata
    duplicado = await session.execute(
        select(Trimestre).where(
            Trimestre.ano == body.ano,
            Trimestre.numero == body.numero,
        )
    )
    if duplicado.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.ano} / {body.numero}º trimestre já está cadastrado.",
        )

    data_inicio, data_fim = _datas_trimestre(body.ano, body.numero)

    trimestre = Trimestre(
        ano=body.ano,
        numero=body.numero,
        data_inicio=data_inicio,
        data_fim=data_fim,
        ativo=body.ativo,
    )
    session.add(trimestre)
    await session.flush()  # garante trimestre.id antes do commit

    # Gera automaticamente todos os domingos do trimestre
    datas_domingos = _domingos_no_periodo(data_inicio, data_fim)
    for numero_aula, data in enumerate(datas_domingos, start=1):
        session.add(Domingo(
            trimestre_id=trimestre.id,
            data=data,
            numero=numero_aula,
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
