"""
Módulo 5 — Métricas Calculadas.

Funções que consomem os modelos e devolvem indicadores agregados.
Nada aqui é armazenado; tudo é computado sob demanda a partir dos
registros de chamada e fechamento.
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Chamada, Domingo, FechamentoDomingo, Matricula, Trimestre


# ── Frequência do Aluno no Trimestre ────────────────────────────────────────
async def frequencia_aluno_trimestre(
    session: AsyncSession,
    aluno_id: int,
    trimestre_id: int,
) -> dict:
    """
    Calcula a frequência percentual de um aluno em um trimestre.

    Retorna:
        {
            "aluno_id": int,
            "trimestre_id": int,
            "total_domingos": int,       # total de domingos do trimestre
            "total_presencas": int,       # quantos domingos o aluno esteve presente
            "total_faltas": int,          # ausências (matriculado mas não presente)
            "frequencia_pct": float,      # percentual 0–100
        }
    """
    # Total de domingos do trimestre
    total_domingos_q = select(func.count(Domingo.id)).where(
        Domingo.trimestre_id == trimestre_id
    )
    total_domingos: int = (await session.execute(total_domingos_q)).scalar_one()

    if total_domingos == 0:
        return {
            "aluno_id": aluno_id,
            "trimestre_id": trimestre_id,
            "total_domingos": 0,
            "total_presencas": 0,
            "total_faltas": 0,
            "frequencia_pct": 0.0,
        }

    # Presenças do aluno nos domingos do trimestre
    presencas_q = (
        select(func.count(Chamada.id))
        .join(Domingo, Chamada.domingo_id == Domingo.id)
        .where(
            Chamada.aluno_id == aluno_id,
            Domingo.trimestre_id == trimestre_id,
            Chamada.presente == True,  # noqa: E712
        )
    )
    total_presencas: int = (await session.execute(presencas_q)).scalar_one()

    total_faltas = total_domingos - total_presencas
    frequencia_pct = round((total_presencas / total_domingos) * 100, 2)

    return {
        "aluno_id": aluno_id,
        "trimestre_id": trimestre_id,
        "total_domingos": total_domingos,
        "total_presencas": total_presencas,
        "total_faltas": total_faltas,
        "frequencia_pct": frequencia_pct,
    }


# ── Média Trimestral da Classe ─────────────────────────────────────────────
async def media_trimestral_classe(
    session: AsyncSession,
    turma_id: int,
    trimestre_id: int,
) -> dict:
    """
    Média de assistência da turma no trimestre.

    Fórmula:
        Σ (presentes + visitantes) de cada fechamento
        ─────────────────────────────────────────────
              total de domingos do trimestre

    Retorna:
        {
            "turma_id": int,
            "trimestre_id": int,
            "total_domingos": int,
            "soma_assistencia": int,     # Σ(presentes + visitantes)
            "media_assistencia": float,  # média por domingo
            "total_matriculados": int,
        }
    """
    # Total de domingos do trimestre
    total_domingos_q = select(func.count(Domingo.id)).where(
        Domingo.trimestre_id == trimestre_id
    )
    total_domingos: int = (await session.execute(total_domingos_q)).scalar_one()

    # Matriculados ativos na turma neste trimestre
    matriculados_q = select(func.count(Matricula.id)).where(
        Matricula.turma_id == turma_id,
        Matricula.trimestre_id == trimestre_id,
        Matricula.ativo == True,  # noqa: E712
    )
    total_matriculados: int = (await session.execute(matriculados_q)).scalar_one()

    if total_domingos == 0:
        return {
            "turma_id": turma_id,
            "trimestre_id": trimestre_id,
            "total_domingos": 0,
            "soma_assistencia": 0,
            "media_assistencia": 0.0,
            "total_matriculados": total_matriculados,
        }

    # Soma das assistências (presentes + visitantes) dos fechamentos
    soma_q = select(
        func.coalesce(
            func.sum(FechamentoDomingo.total_presentes + FechamentoDomingo.total_visitantes),
            0,
        )
    ).where(
        FechamentoDomingo.turma_id == turma_id,
        FechamentoDomingo.domingo_id.in_(
            select(Domingo.id).where(Domingo.trimestre_id == trimestre_id)
        ),
    )
    soma_assistencia: int = (await session.execute(soma_q)).scalar_one()

    media = round(soma_assistencia / total_domingos, 2)

    return {
        "turma_id": turma_id,
        "trimestre_id": trimestre_id,
        "total_domingos": total_domingos,
        "soma_assistencia": soma_assistencia,
        "media_assistencia": media,
        "total_matriculados": total_matriculados,
    }


# ── Dashboard Resumido (todas as turmas de um trimestre) ───────────────────
async def resumo_trimestre(
    session: AsyncSession,
    trimestre_id: int,
) -> list[dict]:
    """
    Retorna um resumo de todas as turmas no trimestre:
    matriculados, média de frequência, total de ofertas, etc.
    """
    from models import Oferta, Turma

    turmas_q = select(Turma).where(Turma.ativo == True)  # noqa: E712
    turmas = (await session.execute(turmas_q)).scalars().all()

    resultado = []
    for turma in turmas:
        metricas = await media_trimestral_classe(session, turma.id, trimestre_id)

        # Total de ofertas da turma no trimestre
        ofertas_q = select(func.coalesce(func.sum(Oferta.valor), 0)).where(
            Oferta.turma_id == turma.id,
            Oferta.domingo_id.in_(
                select(Domingo.id).where(Domingo.trimestre_id == trimestre_id)
            ),
        )
        total_ofertas: Decimal = (await session.execute(ofertas_q)).scalar_one()

        resultado.append({
            "turma_id": turma.id,
            "turma_nome": turma.nome,
            "total_matriculados": metricas["total_matriculados"],
            "media_assistencia": metricas["media_assistencia"],
            "total_domingos": metricas["total_domingos"],
            "total_ofertas": float(total_ofertas),
        })

    return resultado
