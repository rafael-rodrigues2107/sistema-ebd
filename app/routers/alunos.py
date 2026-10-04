"""
Rotas de CRUD para Alunos.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno, Chamada, Domingo, Matricula, Trimestre, Turma, Usuario
from routers.auth import get_optional_user, require_admin
from schemas import AlunoCreate, AlunoHistoricoResponse, AlunoRead, AlunoUpdate, DomingoHistoricoItem, TrimestreRead

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

    for field, value in dados.items():
        setattr(aluno, field, value)

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


@router.get("/{aluno_id}/historico", response_model=AlunoHistoricoResponse)
async def historico_aluno(
    aluno_id: int,
    trimestre_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Retorna o histórico de presença de um aluno em um trimestre."""
    aluno = await session.get(Aluno, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")

    trimestre = await session.get(Trimestre, trimestre_id)
    if not trimestre:
        raise HTTPException(status_code=404, detail="Trimestre não encontrado")

    # Todos os domingos do trimestre
    domingos = (
        await session.execute(
            select(Domingo)
            .where(Domingo.trimestre_id == trimestre_id)
            .order_by(Domingo.numero)
        )
    ).scalars().all()

    # Chamadas do aluno neste trimestre
    chamadas_rows = (
        await session.execute(
            select(Chamada, Turma.nome.label("turma_nome"))
            .join(Domingo, Chamada.domingo_id == Domingo.id)
            .join(Turma, Chamada.turma_id == Turma.id)
            .where(
                Chamada.aluno_id == aluno_id,
                Domingo.trimestre_id == trimestre_id,
            )
        )
    ).all()
    chamadas_map = {row.Chamada.domingo_id: row for row in chamadas_rows}

    # Turma padrão da matrícula ativa neste trimestre
    matricula_row = (
        await session.execute(
            select(Matricula, Turma.nome.label("turma_nome"))
            .join(Turma, Matricula.turma_id == Turma.id)
            .where(
                Matricula.aluno_id == aluno_id,
                Matricula.trimestre_id == trimestre_id,
                Matricula.ativo == True,
            )
            .limit(1)
        )
    ).first()
    turma_nome_default = matricula_row.turma_nome if matricula_row else None

    items: list[DomingoHistoricoItem] = []
    for d in domingos:
        row = chamadas_map.get(d.id)
        if row:
            c = row.Chamada
            items.append(DomingoHistoricoItem(
                domingo_id=d.id,
                data=d.data,
                numero=d.numero,
                tema_licao=d.tema_licao,
                turma_nome=row.turma_nome,
                presente=c.presente,
                trouxe_biblia=c.trouxe_biblia,
                trouxe_revista=c.trouxe_revista,
            ))
        else:
            items.append(DomingoHistoricoItem(
                domingo_id=d.id,
                data=d.data,
                numero=d.numero,
                tema_licao=d.tema_licao,
                turma_nome=turma_nome_default,
                presente=None,
                trouxe_biblia=None,
                trouxe_revista=None,
            ))

    total_registrados = sum(1 for i in items if i.presente is not None)
    total_presentes = sum(1 for i in items if i.presente is True)
    pct = round(total_presentes / total_registrados * 100, 1) if total_registrados > 0 else 0.0

    return AlunoHistoricoResponse(
        aluno=AlunoRead.model_validate(aluno),
        trimestre=TrimestreRead.model_validate(trimestre),
        domingos=items,
        total_domingos=total_registrados,
        total_presentes=total_presentes,
        percentual_presenca=pct,
    )
