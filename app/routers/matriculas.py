"""
Rotas de CRUD para Matrículas (vínculo Aluno ↔ Turma ↔ Trimestre).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_session
from models import Aluno, Matricula, Turma
from schemas import MatriculaCreate, MatriculaDetalhadaRead

router = APIRouter(prefix="/api/matriculas", tags=["Matrículas"])


@router.get("/", response_model=list[MatriculaDetalhadaRead])
async def listar_matriculas(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Matricula)
        .options(selectinload(Matricula.aluno), selectinload(Matricula.turma))
        .where(Matricula.ativo == True)
        .order_by(Matricula.id)
    )
    matriculas = result.scalars().all()
    return [
        MatriculaDetalhadaRead(
            id=m.id,
            aluno_id=m.aluno_id,
            aluno_nome=m.aluno.nome,
            turma_id=m.turma_id,
            turma_nome=m.turma.nome,
            trimestre_id=m.trimestre_id,
            data_matricula=m.data_matricula,
            ativo=m.ativo,
        )
        for m in matriculas
    ]


@router.post("/", response_model=MatriculaDetalhadaRead, status_code=status.HTTP_201_CREATED)
async def criar_matricula(body: MatriculaCreate, session: AsyncSession = Depends(get_session)):
    duplicada = (await session.execute(
        select(Matricula).where(
            Matricula.aluno_id == body.aluno_id,
            Matricula.turma_id == body.turma_id,
            Matricula.trimestre_id == body.trimestre_id,
        )
    )).scalar_one_or_none()
    if duplicada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aluno já matriculado nesta turma para este trimestre",
        )

    aluno = await session.get(Aluno, body.aluno_id)
    if not aluno:
        raise HTTPException(404, "Aluno não encontrado")

    turma = await session.get(Turma, body.turma_id)
    if not turma:
        raise HTTPException(404, "Turma não encontrada")

    matricula = Matricula(**body.model_dump())
    session.add(matricula)
    await session.commit()
    await session.refresh(matricula)

    return MatriculaDetalhadaRead(
        id=matricula.id,
        aluno_id=matricula.aluno_id,
        aluno_nome=aluno.nome,
        turma_id=matricula.turma_id,
        turma_nome=turma.nome,
        trimestre_id=matricula.trimestre_id,
        data_matricula=matricula.data_matricula,
        ativo=matricula.ativo,
    )
