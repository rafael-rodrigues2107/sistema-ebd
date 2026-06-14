"""
Rotas para o Fechamento Consolidado do Domingo (visão da Secretaria).
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Chamada, Domingo, FechamentoDomingo, Matricula, Trimestre, Turma
from schemas import ConfirmarFechamentoDiaCreate, FechamentoDiaRead, TurmaResumoFechamento

router = APIRouter(prefix="/api/fechamento", tags=["Fechamento"])


@router.get("/{domingo_id}", response_model=FechamentoDiaRead)
async def obter_fechamento_dia(
    domingo_id: int, session: AsyncSession = Depends(get_session)
):
    domingo = await session.get(Domingo, domingo_id)
    if not domingo:
        raise HTTPException(status_code=404, detail="Domingo não encontrado")

    trimestre = await session.get(Trimestre, domingo.trimestre_id)

    # Total de matriculas ativas no trimestre (número global do período)
    total_mat_trim = await session.scalar(
        select(func.count(Matricula.id)).where(
            Matricula.trimestre_id == domingo.trimestre_id,
            Matricula.ativo == True,
        )
    ) or 0

    # Contagens de chamadas agregadas por turma
    agg = (
        select(
            Turma.id.label("turma_id"),
            Turma.nome.label("turma_nome"),
            func.coalesce(
                func.sum(case((and_(Chamada.aluno_id.isnot(None), Chamada.presente == True), 1), else_=0)), 0
            ).label("presentes"),
            func.coalesce(
                func.sum(case((and_(Chamada.aluno_id.isnot(None), Chamada.trouxe_biblia == True), 1), else_=0)), 0
            ).label("biblias"),
            func.coalesce(
                func.sum(case((and_(Chamada.aluno_id.isnot(None), Chamada.trouxe_revista == True), 1), else_=0)), 0
            ).label("revistas"),
            func.count(case((Chamada.nome_visitante.isnot(None), 1))).label("visitantes"),
        )
        .join(Turma, Chamada.turma_id == Turma.id)
        .where(Chamada.domingo_id == domingo_id)
        .group_by(Turma.id, Turma.nome)
        .order_by(Turma.nome)
    )
    rows = (await session.execute(agg)).all()

    # Matriculados ativos por turma neste trimestre
    mat_q = await session.execute(
        select(Matricula.turma_id, func.count(Matricula.id))
        .where(Matricula.trimestre_id == domingo.trimestre_id, Matricula.ativo == True)
        .group_by(Matricula.turma_id)
    )
    mat_por_turma = {r[0]: r[1] for r in mat_q.all()}

    # Ofertas já registradas (de fechamentos anteriores por turma)
    fech_q = await session.execute(
        select(FechamentoDomingo).where(FechamentoDomingo.domingo_id == domingo_id)
    )
    fech_map = {f.turma_id: f for f in fech_q.scalars().all()}

    por_turma = []
    for row in rows:
        matriculados = mat_por_turma.get(row.turma_id, 0)
        fech = fech_map.get(row.turma_id)
        por_turma.append(TurmaResumoFechamento(
            turma_id=row.turma_id,
            turma_nome=row.turma_nome,
            total_matriculados=matriculados,
            total_presentes=row.presentes,
            total_ausentes=max(matriculados - row.presentes, 0),
            total_visitantes=row.visitantes,
            total_biblias=row.biblias,
            total_revistas=row.revistas,
            valor_ofertas=fech.valor_ofertas if fech else Decimal("0.00"),
        ))

    return FechamentoDiaRead(
        domingo_id=domingo.id,
        domingo_data=domingo.data,
        domingo_numero=domingo.numero,
        trimestre_ano=trimestre.ano,
        trimestre_numero=trimestre.numero,
        total_matriculados_trimestre=total_mat_trim,
        total_presentes=sum(t.total_presentes for t in por_turma),
        total_visitantes=sum(t.total_visitantes for t in por_turma),
        total_biblias=sum(t.total_biblias for t in por_turma),
        total_revistas=sum(t.total_revistas for t in por_turma),
        total_ofertas=sum((t.valor_ofertas for t in por_turma), Decimal("0.00")),
        por_turma=por_turma,
    )


@router.post("/", status_code=status.HTTP_200_OK)
async def confirmar_fechamento(
    body: ConfirmarFechamentoDiaCreate, session: AsyncSession = Depends(get_session)
):
    """Consolida os dados de chamada em FechamentoDomingo para cada turma (upsert)."""
    domingo = await session.get(Domingo, body.domingo_id)
    if not domingo:
        raise HTTPException(status_code=404, detail="Domingo não encontrado")

    agg = (
        select(
            Chamada.turma_id,
            func.coalesce(
                func.sum(case((and_(Chamada.aluno_id.isnot(None), Chamada.presente == True), 1), else_=0)), 0
            ).label("presentes"),
            func.count(case((Chamada.nome_visitante.isnot(None), 1))).label("visitantes"),
            func.coalesce(
                func.sum(case((and_(Chamada.aluno_id.isnot(None), Chamada.trouxe_biblia == True), 1), else_=0)), 0
            ).label("biblias"),
            func.coalesce(
                func.sum(case((and_(Chamada.aluno_id.isnot(None), Chamada.trouxe_revista == True), 1), else_=0)), 0
            ).label("revistas"),
        )
        .where(Chamada.domingo_id == body.domingo_id)
        .group_by(Chamada.turma_id)
    )
    rows = (await session.execute(agg)).all()

    if not rows:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma chamada registrada para este domingo.",
        )

    mat_q = await session.execute(
        select(Matricula.turma_id, func.count(Matricula.id))
        .where(Matricula.trimestre_id == domingo.trimestre_id, Matricula.ativo == True)
        .group_by(Matricula.turma_id)
    )
    mat_por_turma = {r[0]: r[1] for r in mat_q.all()}

    fech_q = await session.execute(
        select(FechamentoDomingo).where(FechamentoDomingo.domingo_id == body.domingo_id)
    )
    fech_map = {f.turma_id: f for f in fech_q.scalars().all()}

    for row in rows:
        matriculados = mat_por_turma.get(row.turma_id, 0)
        presentes = row.presentes
        fech = fech_map.get(row.turma_id)
        if fech:
            fech.total_matriculados = matriculados
            fech.total_presentes = presentes
            fech.total_visitantes = row.visitantes
            fech.total_ausentes = max(matriculados - presentes, 0)
            fech.total_biblias = row.biblias
            fech.total_revistas = row.revistas
            if body.observacoes is not None:
                fech.observacoes = body.observacoes
        else:
            session.add(FechamentoDomingo(
                domingo_id=body.domingo_id,
                turma_id=row.turma_id,
                total_matriculados=matriculados,
                total_presentes=presentes,
                total_visitantes=row.visitantes,
                total_ausentes=max(matriculados - presentes, 0),
                total_biblias=row.biblias,
                total_revistas=row.revistas,
                valor_ofertas=Decimal("0.00"),
                observacoes=body.observacoes,
            ))

    await session.commit()
    return {"ok": True, "turmas_fechadas": len(rows)}
