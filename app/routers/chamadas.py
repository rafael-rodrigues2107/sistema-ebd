"""
Rotas do Módulo de Chamada e Frequência.

- GET  /api/turmas/{turma_id}/painel — dados completos para montar a tela
- POST /api/turmas/{turma_id}/chamada — salva presenças + fechamento
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_session
from models import (
    Aluno,
    Chamada,
    Domingo,
    FechamentoDomingo,
    Matricula,
    Trimestre,
    Turma,
)
from schemas import (
    AlunoPainelItem,
    FechamentoRead,
    PainelResponse,
    SaveChamadaRequest,
    VisitantePainelItem,
)

router = APIRouter(prefix="/api/turmas", tags=["Chamada"])


# ── GET Painel ─────────────────────────────────────────────────────────────
@router.get("/{turma_id}/painel", response_model=PainelResponse)
async def painel_chamada(
    turma_id: int,
    trimestre_id: int,
    domingo_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Retorna todos os dados necessários para montar a tela de chamada."""

    # Valida existência da turma / trimestre / domingo
    turma = await session.get(Turma, turma_id)
    if not turma:
        raise HTTPException(404, "Turma não encontrada")

    trimestre = await session.get(Trimestre, trimestre_id)
    if not trimestre:
        raise HTTPException(404, "Trimestre não encontrado")

    domingo = await session.get(Domingo, domingo_id)
    if not domingo or domingo.trimestre_id != trimestre_id:
        raise HTTPException(404, "Domingo não encontrado no trimestre informado")

    # ── Alunos matriculados na turma neste trimestre ──
    matriculas_q = (
        select(Matricula, Aluno)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(
            Matricula.turma_id == turma_id,
            Matricula.trimestre_id == trimestre_id,
            Matricula.ativo == True,
            Aluno.ativo == True,
        )
        .order_by(Aluno.nome)
    )
    matriculas_result = await session.execute(matriculas_q)
    matriculas_rows = matriculas_result.all()  # list of (Matricula, Aluno)

    # ── Chamadas já existentes para este domingo/turma ──
    chamadas_q = (
        select(Chamada)
        .where(
            Chamada.domingo_id == domingo_id,
            Chamada.turma_id == turma_id,
        )
    )
    chamadas_result = await session.execute(chamadas_q)
    chamadas_existentes = {c.aluno_id: c for c in chamadas_result.scalars().all() if c.aluno_id is not None}

    # ── Monta lista de alunos com status de chamada ──
    alunos: list[AlunoPainelItem] = []
    for matricula, aluno in matriculas_rows:
        chamada = chamadas_existentes.get(aluno.id)
        alunos.append(
            AlunoPainelItem(
                matricula_id=matricula.id,
                aluno_id=aluno.id,
                nome=aluno.nome,
                presente=chamada.presente if chamada else None,
                trouxe_biblia=chamada.trouxe_biblia if chamada else None,
                trouxe_revista=chamada.trouxe_revista if chamada else None,
                chamada_id=chamada.id if chamada else None,
            )
        )

    # ── Visitantes já registrados ──
    visitantes_q = (
        select(Chamada)
        .where(
            Chamada.domingo_id == domingo_id,
            Chamada.turma_id == turma_id,
            Chamada.aluno_id == None,  # noqa: E711
        )
    )
    visitantes_result = await session.execute(visitantes_q)
    visitantes = [
        VisitantePainelItem(
            chamada_id=v.id,
            nome=v.nome_visitante,
            presente=v.presente,
        )
        for v in visitantes_result.scalars().all()
    ]

    # ── Fechamento existente ──
    fechamento_q = select(FechamentoDomingo).where(
        FechamentoDomingo.domingo_id == domingo_id,
        FechamentoDomingo.turma_id == turma_id,
    )
    fechamento = (await session.execute(fechamento_q)).scalar_one_or_none()
    fechamento_read = (
        FechamentoRead.model_validate(fechamento) if fechamento else None
    )

    return PainelResponse(
        turma=turma,
        trimestre=trimestre,
        domingo=domingo,
        alunos=alunos,
        visitantes=visitantes,
        fechamento=fechamento_read,
    )


# ── POST Salvar Chamada ────────────────────────────────────────────────────
@router.post("/{turma_id}/chamada", status_code=200)
async def salvar_chamada(
    turma_id: int,
    body: SaveChamadaRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Salva (ou atualiza) a chamada completa de um domingo:
    presenças de alunos, visitantes e fechamento.
    """

    # Validações
    turma = await session.get(Turma, turma_id)
    if not turma:
        raise HTTPException(404, "Turma não encontrada")

    domingo = await session.get(Domingo, body.domingo_id)
    if not domingo or domingo.trimestre_id != body.trimestre_id:
        raise HTTPException(404, "Domingo não encontrado no trimestre informado")

    # ── 1. Upsert das chamadas de alunos ──
    for item in body.chamadas:
        # Busca registro existente
        existente_q = select(Chamada).where(
            Chamada.domingo_id == body.domingo_id,
            Chamada.turma_id == turma_id,
            Chamada.aluno_id == item.aluno_id,
        )
        existente = (await session.execute(existente_q)).scalar_one_or_none()

        if existente:
            existente.presente = item.presente
            existente.trouxe_biblia = item.trouxe_biblia
            existente.trouxe_revista = item.trouxe_revista
        else:
            chamada = Chamada(
                domingo_id=body.domingo_id,
                turma_id=turma_id,
                aluno_id=item.aluno_id,
                presente=item.presente,
                trouxe_biblia=item.trouxe_biblia,
                trouxe_revista=item.trouxe_revista,
            )
            session.add(chamada)

    # ── 2. Upsert de visitantes ──
    # Remove visitantes antigos e recria (mais simples que upsert por nome)
    delete_visitantes_q = select(Chamada).where(
        Chamada.domingo_id == body.domingo_id,
        Chamada.turma_id == turma_id,
        Chamada.aluno_id == None,  # noqa: E711
    )
    visitantes_antigos = (await session.execute(delete_visitantes_q)).scalars().all()
    for v in visitantes_antigos:
        await session.delete(v)

    for item in body.visitantes:
        visitante = Chamada(
            domingo_id=body.domingo_id,
            turma_id=turma_id,
            nome_visitante=item.nome,
            presente=item.presente,
        )
        session.add(visitante)

    # ── 3. Upsert do fechamento ──
    fechamento_q = select(FechamentoDomingo).where(
        FechamentoDomingo.domingo_id == body.domingo_id,
        FechamentoDomingo.turma_id == turma_id,
    )
    fechamento = (await session.execute(fechamento_q)).scalar_one_or_none()

    if fechamento:
        for field, value in body.fechamento.model_dump().items():
            setattr(fechamento, field, value)
    else:
        fechamento = FechamentoDomingo(
            domingo_id=body.domingo_id,
            turma_id=turma_id,
            **body.fechamento.model_dump(),
        )
        session.add(fechamento)

    await session.commit()

    return {"ok": True, "message": "Chamada salva com sucesso"}
