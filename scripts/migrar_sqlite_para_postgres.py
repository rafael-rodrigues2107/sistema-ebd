"""Copia todos os dados de um banco SQLite do EBD para um Postgres já migrado (alembic upgrade head).

Uso (a partir da raiz do projeto, com o ambiente do app):

    python scripts/migrar_sqlite_para_postgres.py \
        --origem  sqlite+aiosqlite:///caminho/ebd.db \
        --destino postgresql+asyncpg://usuario:senha@host:5432/banco

- Só lê o SQLite (somente leitura e imutável); nunca altera a origem. Aponte para um backup
  ou rode com o app parado (o arquivo -wal é ignorado).
- Recusa rodar se alguma tabela do destino já tiver linhas (evita duplicar).
- Copia na ordem das chaves estrangeiras, tudo numa única transação: se algo falhar, nada fica.
- Acerta as sequências (próximo id) e confere contagens e somas antes de confirmar.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from sqlalchemy import func, insert, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from models import Base  # noqa: E402


def _origem_somente_leitura(url: str) -> str:
    """sqlite+aiosqlite:///x.db -> abre somente leitura e imutável (a origem nunca muda).

    `immutable=1` também permite ler arquivo em pasta montada como somente leitura e
    em modo WAL. Use sobre um BACKUP ou com o app parado: ele ignora o arquivo -wal.
    """
    prefixo = "sqlite+aiosqlite:///"
    if not url.startswith(prefixo):
        raise SystemExit("A origem precisa ser sqlite+aiosqlite:///caminho/arquivo.db")
    caminho = url[len(prefixo):]
    return f"sqlite+aiosqlite:///file:{caminho}?mode=ro&immutable=1&uri=true"


async def migrar(origem: str, destino: str) -> int:
    if not destino.startswith("postgresql"):
        raise SystemExit("O destino precisa ser postgresql+asyncpg://...")

    src = create_async_engine(_origem_somente_leitura(origem))
    dst = create_async_engine(destino)
    tabelas = Base.metadata.sorted_tables  # ordem segura para as chaves estrangeiras
    erros = []

    async with src.connect() as s, dst.begin() as d:
        # 1) o destino precisa estar vazio
        for t in tabelas:
            n = await d.scalar(select(func.count()).select_from(t))
            if n:
                raise SystemExit(f"Destino não está vazio: {t.name} tem {n} linhas. Nada foi copiado.")

        # 2) copia
        print(f"{'tabela':<22}{'origem':>8}{'destino':>9}")
        for t in tabelas:
            linhas = (await s.execute(select(t))).mappings().all()
            if linhas:
                await d.execute(insert(t), [dict(r) for r in linhas])
            n_dst = await d.scalar(select(func.count()).select_from(t))
            marca = "" if n_dst == len(linhas) else "  <-- DIFERENTE"
            if marca:
                erros.append(f"{t.name}: origem {len(linhas)} x destino {n_dst}")
            print(f"{t.name:<22}{len(linhas):>8}{n_dst:>9}{marca}")

            # 3) próxima sequência de id = maior id existente + 1
            if "id" in t.c and t.c.id.primary_key:
                await d.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"
                ))

        # 4) conferência de conteúdo: soma dos ids e das colunas numéricas por tabela
        for t in tabelas:
            if "id" not in t.c:
                continue
            soma_s = await s.scalar(select(func.coalesce(func.sum(t.c.id), 0)))
            soma_d = await d.scalar(select(func.coalesce(func.sum(t.c.id), 0)))
            if soma_s != soma_d:
                erros.append(f"{t.name}: soma dos ids difere ({soma_s} x {soma_d})")

        if erros:
            print("\nERROS — nada foi gravado no destino:")
            for e in erros:
                print("  -", e)
            raise SystemExit(1)  # a transação do destino é desfeita ao sair

    await src.dispose()
    await dst.dispose()
    print("\nOK: dados copiados e conferidos.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origem", required=True)
    ap.add_argument("--destino", required=True)
    args = ap.parse_args()
    sys.exit(asyncio.run(migrar(args.origem, args.destino)))
