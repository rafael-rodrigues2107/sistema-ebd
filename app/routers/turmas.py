"""
Rotas de CRUD para Turmas (Classes da EBD).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Turma
from schemas import TurmaCreate, TurmaRead

router = APIRouter(prefix="/api/turmas", tags=["Turmas"])


@router.get("/", response_model=list[TurmaRead])
async def listar_turmas(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Turma).where(Turma.ativo == True).order_by(Turma.nome)
    )
    return result.scalars().all()


@router.get("/{turma_id}", response_model=TurmaRead)
async def obter_turma(turma_id: int, session: AsyncSession = Depends(get_session)):
    turma = await session.get(Turma, turma_id)
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    return turma


@router.post("/", response_model=TurmaRead, status_code=status.HTTP_201_CREATED)
async def criar_turma(body: TurmaCreate, session: AsyncSession = Depends(get_session)):
    turma = Turma(**body.model_dump())
    session.add(turma)
    await session.commit()
    await session.refresh(turma)
    return turma


@router.put("/{turma_id}", response_model=TurmaRead)
async def atualizar_turma(
    turma_id: int, body: TurmaCreate, session: AsyncSession = Depends(get_session)
):
    turma = await session.get(Turma, turma_id)
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(turma, field, value)
    await session.commit()
    await session.refresh(turma)
    return turma
