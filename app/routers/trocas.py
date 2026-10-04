"""
Solicitações de troca de turma.

- Professor pede a troca de um aluno da própria turma (ex.: mudou de faixa etária).
- Admin aprova ou recusa. Ao aprovar, a matrícula muda de turma no trimestre
  atual e nos seguintes já gerados; o histórico de chamadas fica na turma antiga.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Aluno, Matricula, SolicitacaoTroca, Trimestre, Turma, Usuario
from routers.auth import get_current_user, require_admin
from routers.trimestres import trimestre_atual
from schemas import DecisaoTroca, SolicitacaoTrocaCreate, SolicitacaoTrocaRead

router = APIRouter(prefix="/api/trocas", tags=["Trocas de Turma"], dependencies=[Depends(get_current_user)])


async def mover_matriculas(
    session: AsyncSession,
    aluno_id: int,
    turma_destino_id: int,
    a_partir_de: Trimestre,
    turma_origem_id: int | None = None,
) -> int:
    """
    Passa as matrículas ativas do aluno para a turma de destino, do trimestre
    `a_partir_de` em diante (trimestres anteriores e chamadas ficam como estão).
    Com `turma_origem_id`, só mexe nas matrículas dessa turma. Retorna quantas mudou.
    """
    q = (
        select(Matricula)
        .join(Trimestre, Matricula.trimestre_id == Trimestre.id)
        .where(
            Matricula.aluno_id == aluno_id,
            Matricula.ativo == True,
            Matricula.turma_id != turma_destino_id,
            or_(
                Trimestre.ano > a_partir_de.ano,
                and_(Trimestre.ano == a_partir_de.ano, Trimestre.numero >= a_partir_de.numero),
            ),
        )
    )
    if turma_origem_id is not None:
        q = q.where(Matricula.turma_id == turma_origem_id)

    matriculas = (await session.execute(q)).scalars().all()
    for m in matriculas:
        # Já existe matrícula na turma de destino nesse trimestre? Reaproveita.
        existente = await session.scalar(
            select(Matricula).where(
                Matricula.aluno_id == m.aluno_id,
                Matricula.turma_id == turma_destino_id,
                Matricula.trimestre_id == m.trimestre_id,
            )
        )
        if existente:
            existente.ativo = True
            m.ativo = False
        else:
            m.turma_id = turma_destino_id
    return len(matriculas)


def _to_read(s: SolicitacaoTroca) -> SolicitacaoTrocaRead:
    return SolicitacaoTrocaRead(
        id=s.id,
        aluno_id=s.aluno_id,
        aluno_nome=s.aluno.nome,
        turma_origem_id=s.turma_origem_id,
        turma_origem_nome=s.turma_origem.nome,
        turma_destino_id=s.turma_destino_id,
        turma_destino_nome=s.turma_destino.nome,
        motivo=s.motivo,
        status=s.status,
        resposta=s.resposta,
        solicitante_nome=s.solicitante.nome if s.solicitante else None,
        decidido_por_nome=s.decidido_por.nome if s.decidido_por else None,
        created_at=s.created_at,
        decidido_em=s.decidido_em,
    )


async def _pendente(session: AsyncSession, troca_id: int) -> SolicitacaoTroca:
    troca = await session.get(SolicitacaoTroca, troca_id)
    if not troca:
        raise HTTPException(404, "Solicitação não encontrada")
    if troca.status != "pendente":
        raise HTTPException(409, f"Esta solicitação já foi {troca.status}.")
    return troca


@router.get("/", response_model=list[SolicitacaoTrocaRead])
async def listar_trocas(
    status_filtro: str | None = None,
    user: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Admin vê todas; professor vê só as que ele pediu. Pendentes primeiro."""
    q = select(SolicitacaoTroca).order_by(
        case((SolicitacaoTroca.status == "pendente", 0), else_=1),
        SolicitacaoTroca.created_at.desc(),
    ).limit(200)
    if status_filtro:
        q = q.where(SolicitacaoTroca.status == status_filtro)
    if user.role != "admin":
        q = q.where(SolicitacaoTroca.solicitante_id == user.id)
    return [_to_read(s) for s in (await session.execute(q)).scalars().all()]


@router.post("/", response_model=SolicitacaoTrocaRead, status_code=status.HTTP_201_CREATED)
async def solicitar_troca(
    body: SolicitacaoTrocaCreate,
    user: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    aluno = await session.get(Aluno, body.aluno_id)
    if not aluno or not aluno.ativo:
        raise HTTPException(404, "Aluno não encontrado")

    trimestre = await trimestre_atual(session)
    if not trimestre:
        raise HTTPException(400, "Nenhum trimestre ativo")
    matricula = await session.scalar(
        select(Matricula).where(
            Matricula.aluno_id == aluno.id,
            Matricula.trimestre_id == trimestre.id,
            Matricula.ativo == True,
        ).limit(1)
    )
    if not matricula:
        raise HTTPException(400, "O aluno não está matriculado em nenhuma turma no trimestre atual")

    if user.role == "professor" and matricula.turma_id != user.turma_id:
        raise HTTPException(403, "Professores só podem pedir troca de alunos da própria turma")

    destino = await session.get(Turma, body.turma_destino_id)
    if not destino or not destino.ativo:
        raise HTTPException(404, "Turma de destino não encontrada")
    if destino.id == matricula.turma_id:
        raise HTTPException(400, "O aluno já está nesta turma")

    ja_existe = await session.scalar(
        select(SolicitacaoTroca.id).where(
            SolicitacaoTroca.aluno_id == aluno.id,
            SolicitacaoTroca.status == "pendente",
        )
    )
    if ja_existe:
        raise HTTPException(409, f"{aluno.nome} já tem uma troca de turma aguardando aprovação")

    troca = SolicitacaoTroca(
        aluno_id=aluno.id,
        turma_origem_id=matricula.turma_id,
        turma_destino_id=destino.id,
        motivo=(body.motivo or "").strip() or None,
        solicitante_id=user.id,
    )
    session.add(troca)
    await session.commit()
    await session.refresh(troca)
    return _to_read(troca)


@router.post("/{troca_id}/aprovar", response_model=SolicitacaoTrocaRead)
async def aprovar_troca(
    troca_id: int,
    body: DecisaoTroca,
    admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    troca = await _pendente(session, troca_id)
    atual = await trimestre_atual(session)
    if not atual:
        raise HTTPException(400, "Nenhum trimestre ativo")

    movidas = await mover_matriculas(
        session, troca.aluno_id, troca.turma_destino_id, atual, turma_origem_id=troca.turma_origem_id
    )
    if not movidas:
        raise HTTPException(
            409,
            f"{troca.aluno.nome} não está mais na turma {troca.turma_origem.nome}. "
            "Recuse esta solicitação ou ajuste a turma na aba Alunos.",
        )

    troca.status = "aprovada"
    troca.resposta = (body.resposta or "").strip() or None
    troca.decidido_por_id = admin.id
    troca.decidido_em = datetime.utcnow()
    await session.commit()
    await session.refresh(troca)
    return _to_read(troca)


@router.post("/{troca_id}/recusar", response_model=SolicitacaoTrocaRead)
async def recusar_troca(
    troca_id: int,
    body: DecisaoTroca,
    admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    troca = await _pendente(session, troca_id)
    troca.status = "recusada"
    troca.resposta = (body.resposta or "").strip() or None
    troca.decidido_por_id = admin.id
    troca.decidido_em = datetime.utcnow()
    await session.commit()
    await session.refresh(troca)
    return _to_read(troca)


@router.post("/{troca_id}/cancelar", response_model=SolicitacaoTrocaRead)
async def cancelar_troca(
    troca_id: int,
    user: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Quem pediu (ou um admin) pode desistir enquanto estiver pendente."""
    troca = await _pendente(session, troca_id)
    if user.role != "admin" and troca.solicitante_id != user.id:
        raise HTTPException(403, "Só quem fez o pedido pode cancelá-lo")
    troca.status = "cancelada"
    troca.decidido_por_id = user.id
    troca.decidido_em = datetime.utcnow()
    await session.commit()
    await session.refresh(troca)
    return _to_read(troca)
