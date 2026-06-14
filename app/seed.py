"""
Script de seed — popula o banco com dados de exemplo para teste do MVP.

Uso:
    python seed.py                # dentro do container (WORKDIR=/app/app)
    docker compose exec app python seed.py
"""

import asyncio
from datetime import date, timedelta

import bcrypt as _bcrypt
from sqlalchemy import select

from database import _async_session_factory
from models import Aluno, Domingo, Matricula, Trimestre, Turma, Usuario

# ── Dados de exemplo ───────────────────────────────────────────────────────

TRIMESTRE = {
    "ano": 2026,
    "numero": 2,
    "data_inicio": date(2026, 4, 5),
    "data_fim": date(2026, 6, 28),
    "ativo": True,
}

TURMAS = [
    {"nome": "Adultos", "faixa_etaria": "Adultos", "descricao": "Classe dos adultos"},
    {"nome": "Jovens", "faixa_etaria": "Jovens", "descricao": "Classe dos jovens (18–30 anos)"},
    {"nome": "Adolescentes", "faixa_etaria": "Adolescentes", "descricao": "Classe dos adolescentes (13–17 anos)"},
    {"nome": "Juniores", "faixa_etaria": "Juniores", "descricao": "Classe infantil (9–12 anos)"},
]

# Alunos por turma
ALUNOS = {
    "Adultos": [
        "João Silva", "Maria Oliveira", "Pedro Santos", "Ana Costa",
        "Carlos Pereira", "Lúcia Ferreira", "José Almeida", "Marta Ribeiro",
        "Paulo Nunes", "Carla Souza", "Antônio Lima", "Fernanda Cardoso",
    ],
    "Jovens": [
        "Lucas Andrade", "Juliana Martins", "Rafael Barbosa", "Camila Rocha",
        "Gabriel Dias", "Amanda Teixeira", "Bruno Azevedo", "Larissa Campos",
    ],
    "Adolescentes": [
        "Mateus Vieira", "Isabela Freitas", "Tiago Moreira", "Sophia Neves",
        "Daniel Pires", "Beatriz Macedo", "Felipe Correia", "Manuela Farias",
    ],
    "Juniores": [
        "Davi Henrique", "Clara Monteiro", "Samuel Tavares", "Liz Nogueira",
        "Noah Mendes", "Heloísa Duarte", "Miguel Barros", "Luiza Peixoto",
    ],
}


def gerar_domingos(data_inicio: date, data_fim: date) -> list[date]:
    """Retorna todas as datas de domingo entre data_inicio e data_fim."""
    domingos = []
    d = data_inicio
    while d <= data_fim:
        if d.weekday() == 6:  # 0=segunda, 6=domingo
            domingos.append(d)
        d += timedelta(days=1)
    return domingos


# ── Main ───────────────────────────────────────────────────────────────────

async def seed():
    async with _async_session_factory() as session:
        print("🌱 Iniciando seed…")

        # ── 1. Trimestre ──
        existente = await session.execute(
            select(Trimestre).where(
                Trimestre.ano == TRIMESTRE["ano"],
                Trimestre.numero == TRIMESTRE["numero"],
            )
        )
        if existente.scalar_one_or_none():
            print("  ⏭  Trimestre já existe — pulando.")
        else:
            trimestre = Trimestre(**TRIMESTRE)
            session.add(trimestre)
            await session.flush()
            print(f"  ✅ Trimestre: {trimestre.ano}/{trimestre.numero}º")

        # Recarrega para garantir
        result = await session.execute(
            select(Trimestre).where(
                Trimestre.ano == TRIMESTRE["ano"],
                Trimestre.numero == TRIMESTRE["numero"],
            )
        )
        trimestre = result.scalar_one()

        # ── 2. Domingos ──
        existentes = await session.execute(
            select(Domingo).where(Domingo.trimestre_id == trimestre.id)
        )
        qtd_existentes = len(existentes.scalars().all())
        if qtd_existentes > 0:
            print(f"  ⏭  {qtd_existentes} domingos já existem — pulando.")
        else:
            datas = gerar_domingos(trimestre.data_inicio, trimestre.data_fim)
            for i, data in enumerate(datas, start=1):
                domingo = Domingo(
                    trimestre_id=trimestre.id,
                    data=data,
                    numero=i,
                    tema_licao=f"Lição {i} — Tema do {i}º Domingo",
                )
                session.add(domingo)
            await session.flush()
            print(f"  ✅ {len(datas)} domingos criados (de {datas[0]} a {datas[-1]})")

        # ── 3. Turmas ──
        turmas_obj = {}
        for t in TURMAS:
            existente = await session.execute(
                select(Turma).where(Turma.nome == t["nome"])
            )
            turma = existente.scalar_one_or_none()
            if turma:
                print(f"  ⏭  Turma '{t['nome']}' já existe.")
            else:
                turma = Turma(**t)
                session.add(turma)
                await session.flush()
                print(f"  ✅ Turma: {turma.nome}")
            turmas_obj[t["nome"]] = turma

        await session.flush()

        # ── 4. Alunos e Matrículas ──
        total_criados = 0
        for turma_nome, nomes in ALUNOS.items():
            turma = turmas_obj[turma_nome]
            for nome in nomes:
                # Verifica se aluno já existe
                existente_aluno = await session.execute(
                    select(Aluno).where(Aluno.nome == nome)
                )
                aluno = existente_aluno.scalar_one_or_none()
                if not aluno:
                    aluno = Aluno(nome=nome)
                    session.add(aluno)
                    await session.flush()

                # Verifica se matrícula já existe
                existente_mat = await session.execute(
                    select(Matricula).where(
                        Matricula.aluno_id == aluno.id,
                        Matricula.turma_id == turma.id,
                        Matricula.trimestre_id == trimestre.id,
                    )
                )
                if existente_mat.scalar_one_or_none():
                    continue

                matricula = Matricula(
                    aluno_id=aluno.id,
                    turma_id=turma.id,
                    trimestre_id=trimestre.id,
                )
                session.add(matricula)
                total_criados += 1

        await session.commit()
        print(f"  ✅ {total_criados} matrículas criadas/verificadas.")
        print("🏁 Seed concluído com sucesso!")


async def seed_admin() -> None:
    """Cria o usuário administrador padrão se nenhum usuário existir."""
    async with _async_session_factory() as session:
        total = await session.scalar(select(Usuario).limit(1))
        if total is not None:
            return
        admin = Usuario(
            nome="Administrador",
            username="admin",
            senha_hash=_bcrypt.hashpw(b"admin123", _bcrypt.gensalt()).decode(),
            role="admin",
        )
        session.add(admin)
        await session.commit()
        print("✅ Admin padrão criado — username: admin / senha: admin123")


if __name__ == "__main__":
    asyncio.run(seed())
