"""
Rotas para o Dashboard da Liderança.
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno, Chamada, Domingo, Matricula, Trimestre, Turma
from schemas import AlunoSumidoItem, DashboardRead, DomingoPresencaItem, TurmaRankingItem

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/dados", response_model=DashboardRead)
async def obter_dados_dashboard(
    trimestre_id: int, session: AsyncSession = Depends(get_session)
):
    if not await session.get(Trimestre, trimestre_id):
        raise HTTPException(status_code=404, detail="Trimestre não encontrado")

    # ── 1. Histórico de presença domingo a domingo ────────────────────────
    # Apenas domingos que já tiveram chamada de aluno registrada (INNER JOIN)
    hist_rows = (await session.execute(
        select(
            Domingo.numero,
            Domingo.data,
            func.sum(case((Chamada.presente == True, 1), else_=0)).label("total_presentes"),
            func.count(Chamada.id).label("total_chamadas"),
        )
        .join(Chamada, and_(Chamada.domingo_id == Domingo.id, Chamada.aluno_id.isnot(None)))
        .where(Domingo.trimestre_id == trimestre_id)
        .group_by(Domingo.id, Domingo.numero, Domingo.data)
        .order_by(Domingo.numero)
    )).all()

    historico = [
        DomingoPresencaItem(
            domingo_numero=r.numero,
            domingo_data=r.data,
            total_presentes=r.total_presentes,
            total_chamadas=r.total_chamadas,
        )
        for r in hist_rows
    ]

    # ── 2. Ranking de turmas por percentual médio de frequência ───────────
    # Subquery: IDs dos domingos deste trimestre
    dom_ids_sub = select(Domingo.id).where(Domingo.trimestre_id == trimestre_id)

    pres_rows = (await session.execute(
        select(
            Chamada.turma_id,
            Chamada.domingo_id,
            func.sum(case((Chamada.presente == True, 1), else_=0)).label("presentes"),
            func.count(Chamada.id).label("total"),
        )
        .where(Chamada.domingo_id.in_(dom_ids_sub), Chamada.aluno_id.isnot(None))
        .group_by(Chamada.turma_id, Chamada.domingo_id)
    )).all()

    # Matriculados ativos por turma
    mat_por_turma = {
        r[0]: r[1]
        for r in (await session.execute(
            select(Matricula.turma_id, func.count(Matricula.id))
            .where(Matricula.trimestre_id == trimestre_id, Matricula.ativo == True)
            .group_by(Matricula.turma_id)
        )).all()
    }

    # Nomes de turmas
    turma_ids = {r.turma_id for r in pres_rows}
    turma_map = {
        r.id: r.nome
        for r in (await session.execute(
            select(Turma.id, Turma.nome).where(Turma.id.in_(list(turma_ids)))
        )).all()
    } if turma_ids else {}

    turma_pcts: dict[int, list[float]] = defaultdict(list)
    for r in pres_rows:
        base = mat_por_turma.get(r.turma_id) or r.total or 1
        turma_pcts[r.turma_id].append(r.presentes / base * 100)

    ranking = sorted(
        [
            TurmaRankingItem(
                turma_id=tid,
                turma_nome=turma_map.get(tid, f"Turma {tid}"),
                media_frequencia=round(sum(pcts) / len(pcts), 1),
                total_domingos_com_chamada=len(pcts),
            )
            for tid, pcts in turma_pcts.items()
        ],
        key=lambda x: x.media_frequencia,
        reverse=True,
    )

    # ── 3. Alunos sumidos (3+ faltas consecutivas a partir do domingo mais recente) ──
    dom_ids_recentes = [
        r[0]
        for r in (await session.execute(
            select(Domingo.id)
            .where(
                Domingo.trimestre_id == trimestre_id,
                Domingo.id.in_(
                    select(Chamada.domingo_id)
                    .where(Chamada.aluno_id.isnot(None))
                    .distinct()
                ),
            )
            .order_by(Domingo.data.desc())
        )).all()
    ]

    alunos_sumidos: list[AlunoSumidoItem] = []

    if len(dom_ids_recentes) >= 3:
        mat_rows = (await session.execute(
            select(
                Matricula.aluno_id,
                Aluno.nome.label("aluno_nome"),
                Aluno.telefone,
                Turma.nome.label("turma_nome"),
            )
            .join(Aluno, Matricula.aluno_id == Aluno.id)
            .join(Turma, Matricula.turma_id == Turma.id)
            .where(Matricula.trimestre_id == trimestre_id, Matricula.ativo == True)
            .order_by(Aluno.nome)
        )).all()

        # Presença: True se aluno compareceu em QUALQUER turma naquele domingo
        presencas: dict[tuple[int, int], bool] = {}
        for c in (await session.execute(
            select(Chamada.aluno_id, Chamada.domingo_id, Chamada.presente)
            .where(Chamada.domingo_id.in_(dom_ids_recentes), Chamada.aluno_id.isnot(None))
        )).all():
            key = (c.aluno_id, c.domingo_id)
            presencas[key] = presencas.get(key, False) or c.presente

        # Agrupa turmas por aluno
        turmas_por_aluno: dict[int, list[str]] = defaultdict(list)
        aluno_info: dict[int, tuple[str, str | None]] = {}
        for m in mat_rows:
            turmas_por_aluno[m.aluno_id].append(m.turma_nome)
            if m.aluno_id not in aluno_info:
                aluno_info[m.aluno_id] = (m.aluno_nome, m.telefone)

        for aid, (nome, telefone) in aluno_info.items():
            faltas = 0
            for did in dom_ids_recentes:
                if presencas.get((aid, did), False):
                    break
                faltas += 1
            if faltas >= 3:
                alunos_sumidos.append(AlunoSumidoItem(
                    aluno_id=aid,
                    aluno_nome=nome,
                    telefone=telefone,
                    turma_nome=", ".join(turmas_por_aluno[aid]),
                    faltas_consecutivas=faltas,
                ))

        alunos_sumidos.sort(key=lambda x: x.faltas_consecutivas, reverse=True)

    return DashboardRead(
        trimestre_id=trimestre_id,
        historico_presenca=historico,
        ranking_turmas=ranking,
        alunos_sumidos=alunos_sumidos,
    )
