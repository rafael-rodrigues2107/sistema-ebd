"""
Rotas de CRUD para Alunos.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno
from schemas import AlunoCreate, AlunoRead

router = APIRouter(prefix="/api/alunos", tags=["Alunos"])


@router.get("/", response_model=list[AlunoRead])
async def listar_alunos(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Aluno).where(Aluno.ativo == True).order_by(Aluno.nome)
    )
    return result.scalars().all()


@router.post("/", response_model=AlunoRead, status_code=status.HTTP_201_CREATED)
async def criar_aluno(body: AlunoCreate, session: AsyncSession = Depends(get_session)):
    aluno = Aluno(**body.model_dump())
    session.add(aluno)
    await session.commit()
    await session.refresh(aluno)
    return aluno
