"""
Rotas de CRUD para Alunos.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno, Matricula, Trimestre, Usuario
from routers.auth import get_optional_user, require_admin
from schemas import AlunoCreate, AlunoRead, AlunoUpdate

router = APIRouter(prefix="/api/alunos", tags=["Alunos"])


@router.get("/", response_model=list[AlunoRead])
async def listar_alunos(
    incluir_inativos: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[Usuario] = Depends(get_optional_user),
):
    if incluir_inativos:
        if not current_user or current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    q = select(Aluno).order_by(Aluno.nome)
    if not incluir_inativos:
        q = q.where(Aluno.ativo == True)
    return (await session.execute(q)).scalars().all()


@router.post("/", response_model=AlunoRead, status_code=status.HTTP_201_CREATED)
async def criar_aluno(body: AlunoCreate, session: AsyncSession = Depends(get_session)):
    aluno = Aluno(**body.model_dump())
    session.add(aluno)
    await session.commit()
    await session.refresh(aluno)
    return aluno


@router.put("/{aluno_id}", response_model=AlunoRead)
async def atualizar_aluno(
    aluno_id: int,
    body: AlunoUpdate,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    aluno = await session.get(Aluno, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")

    dados = body.model_dump(exclude_unset=True)
    novo_turma_id = dados.pop("turma_id", None)

    # Atualiza campos diretos do aluno
    for field, value in dados.items():
        setattr(aluno, field, value)

    # Se turma_id fornecido, migra a matrícula ativa no trimestre corrente
    if novo_turma_id is not None:
        trim_res = await session.execute(
            select(Trimestre)
            .where(Trimestre.ativo == True)
            .order_by(Trimestre.ano.desc(), Trimestre.numero.desc())
            .limit(1)
        )
        trimestre = trim_res.scalar_one_or_none()

        if trimestre:
            mat_res = await session.execute(
                select(Matricula)
                .where(
                    Matricula.aluno_id == aluno_id,
                    Matricula.trimestre_id == trimestre.id,
                    Matricula.ativo == True,
                )
                .limit(1)
            )
            matricula = mat_res.scalar_one_or_none()

            if matricula:
                matricula.turma_id = novo_turma_id
            else:
                # Aluno sem matrícula neste trimestre: cria uma nova
                session.add(Matricula(
                    aluno_id=aluno_id,
                    turma_id=novo_turma_id,
                    trimestre_id=trimestre.id,
                ))

    await session.commit()
    await session.refresh(aluno)
    return aluno


@router.delete("/{aluno_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_aluno(
    aluno_id: int,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Soft delete: inativa o aluno preservando histórico de chamadas e matrículas."""
    aluno = await session.get(Aluno, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    aluno.ativo = False
    await session.commit()
