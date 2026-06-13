"""
Rotas para Trimestres e Domingos.
"""

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
    trimestre = Trimestre(**body.model_dump())
    session.add(trimestre)
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
    # Verifica se o trimestre existe
    trimestre = await session.get(Trimestre, trimestre_id)
    if not trimestre:
        raise HTTPException(status_code=404, detail="Trimestre não encontrado")

    domingo = Domingo(trimestre_id=trimestre_id, **body.model_dump())
    session.add(domingo)
    await session.commit()
    await session.refresh(domingo)
    return domingo
