"""
Rotas para o Dashboard da Liderança.
"""

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno, Chamada, Domingo, FechamentoDomingo, Matricula, Trimestre, Turma, Usuario
from routers.auth import require_admin
from schemas import (
    AlunoNota10Item,
    AlunoSumidoItem,
    DashboardRead,
    DomingoPresencaItem,
    TurmaOfertaItem,
    TurmaRankingItem,
)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/dados", response_model=DashboardRead)
async def obter_dados_dashboard(
    trimestre_id: int,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if not await session.get(Trimestre, trimestre_id):
        raise HTTPException(status_code=404, detail="Trimestre não encontrado")

    # Subquery reutilizada: IDs dos domingos deste trimestre
    dom_ids_sub = select(Domingo.id).where(Domingo.trimestre_id == trimestre_id)

    # ── 1. Histórico de presença domingo a domingo ────────────────────────
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
            total_presentes=int(r.total_presentes or 0),
            total_chamadas=int(r.total_chamadas or 0),
        )
        for r in hist_rows
    ]

    # ── 2. Ranking de frequência por turma ───────────────────────────────
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

    mat_por_turma = {
        r[0]: r[1]
        for r in (await session.execute(
            select(Matricula.turma_id, func.count(Matricula.id))
            .where(Matricula.trimestre_id == trimestre_id, Matricula.ativo == True)
            .group_by(Matricula.turma_id)
        )).all()
    }

    # Mapa de turmas (expandido ao longo das consultas)
    turma_ids_freq = {r.turma_id for r in pres_rows}
    turma_map: dict[int, str] = {}
    if turma_ids_freq:
        turma_map = {
            r.id: r.nome
            for r in (await session.execute(
                select(Turma.id, Turma.nome).where(Turma.id.in_(list(turma_ids_freq)))
            )).all()
        }

    turma_pcts: dict[int, list[float]] = defaultdict(list)
    for r in pres_rows:
        presentes = int(r.presentes or 0)
        base = mat_por_turma.get(r.turma_id) or int(r.total or 0) or 1
        turma_pcts[r.turma_id].append(presentes / base * 100)

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

    # ── 3. Ranking de ofertas e total acumulado ───────────────────────────
    oferta_rows = (await session.execute(
        select(
            FechamentoDomingo.turma_id,
            func.coalesce(func.sum(FechamentoDomingo.valor_ofertas), 0).label("total_ofertas"),
        )
        .where(FechamentoDomingo.domingo_id.in_(dom_ids_sub))
        .group_by(FechamentoDomingo.turma_id)
        .order_by(func.sum(FechamentoDomingo.valor_ofertas).desc())
    )).all()

    # Carrega nomes de turmas ausentes do mapa atual
    oferta_turma_ids = {r.turma_id for r in oferta_rows} - set(turma_map)
    if oferta_turma_ids:
        turma_map.update({
            r.id: r.nome
            for r in (await session.execute(
                select(Turma.id, Turma.nome).where(Turma.id.in_(list(oferta_turma_ids)))
            )).all()
        })

    ranking_ofertas = [
        TurmaOfertaItem(
            turma_id=r.turma_id,
            turma_nome=turma_map.get(r.turma_id, f"Turma {r.turma_id}"),
            total_ofertas=Decimal(str(r.total_ofertas or 0)),
        )
        for r in oferta_rows
    ]
    total_acumulado_ofertas = sum(
        (item.total_ofertas for item in ranking_ofertas), Decimal("0.00")
    )

    # ── 4. Campeã de visitantes ───────────────────────────────────────────
    vis_row = (await session.execute(
        select(Chamada.turma_id, func.count(Chamada.id).label("total_vis"))
        .where(Chamada.domingo_id.in_(dom_ids_sub), Chamada.nome_visitante.isnot(None))
        .group_by(Chamada.turma_id)
        .order_by(func.count(Chamada.id).desc())
        .limit(1)
    )).first()

    campeao_visitantes: str | None = None
    if vis_row:
        tid_v = vis_row.turma_id
        if tid_v not in turma_map:
            t = await session.get(Turma, tid_v)
            turma_map[tid_v] = t.nome if t else f"Turma {tid_v}"
        campeao_visitantes = turma_map[tid_v]

    # ── 5. Alunos sumidos e nota 10 ───────────────────────────────────────
    # Domingos com chamadas de alunos, ordenados desc (mais recentes primeiro)
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
    alunos_nota_10: list[AlunoNota10Item] = []

    if dom_ids_recentes:
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

        # presencas[(aluno_id, domingo_id)] = True se presente em QUALQUER turma
        presencas: dict[tuple[int, int], bool] = {}
        for c in (await session.execute(
            select(Chamada.aluno_id, Chamada.domingo_id, Chamada.presente)
            .where(Chamada.domingo_id.in_(dom_ids_recentes), Chamada.aluno_id.isnot(None))
        )).all():
            key = (c.aluno_id, c.domingo_id)
            presencas[key] = presencas.get(key, False) or c.presente

        turmas_por_aluno: dict[int, list[str]] = defaultdict(list)
        aluno_info: dict[int, tuple[str, str | None]] = {}
        for m in mat_rows:
            turmas_por_aluno[m.aluno_id].append(m.turma_nome)
            if m.aluno_id not in aluno_info:
                aluno_info[m.aluno_id] = (m.aluno_nome, m.telefone)

        for aid, (nome, telefone) in aluno_info.items():
            # Domingos em que este aluno tem chamada registrada
            doms_do_aluno = [did for did in dom_ids_recentes if (aid, did) in presencas]

            # Nota 10: presente em TODOS os domingos onde foi registrado
            if doms_do_aluno and all(presencas[(aid, did)] for did in doms_do_aluno):
                alunos_nota_10.append(AlunoNota10Item(
                    aluno_id=aid,
                    aluno_nome=nome,
                    turma_nome=", ".join(turmas_por_aluno[aid]),
                    total_domingos=len(doms_do_aluno),
                ))

            # Sumidos: 3+ faltas consecutivas a partir do domingo mais recente
            if len(dom_ids_recentes) >= 3:
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

        alunos_nota_10.sort(key=lambda x: x.aluno_nome)
        alunos_sumidos.sort(key=lambda x: x.faltas_consecutivas, reverse=True)

    return DashboardRead(
        trimestre_id=trimestre_id,
        historico_presenca=historico,
        ranking_turmas=ranking,
        alunos_sumidos=alunos_sumidos,
        total_acumulado_ofertas=total_acumulado_ofertas,
        ranking_ofertas=ranking_ofertas,
        campeao_visitantes=campeao_visitantes,
        alunos_nota_10=alunos_nota_10,
    )
