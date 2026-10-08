"""
Armazenamento de arquivos enviados (hoje: logo da igreja e ícones gerados).

Grava no disco, em `settings.uploads_dir/<igreja_id>/` (volume persistente em produção): cada igreja
tem a sua pasta, escolhida pela igreja da requisição (tenant.igreja_do_contexto).
Para usar um bucket (S3, R2, Supabase Storage) no futuro, basta reimplementar
estas funções mantendo as assinaturas.
"""

import shutil
from pathlib import Path

from config import settings
from tenant import igreja_do_contexto

IGREJA_ORIGINAL = 1  # a igreja que já existia antes dos arquivos serem separados por pasta


def _raiz() -> Path:
    base = Path(settings.uploads_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _base() -> Path:
    base = _raiz() / str(igreja_do_contexto())
    base.mkdir(parents=True, exist_ok=True)
    return base


def migrar_arquivos_legados() -> int:
    """Antes da fase 4 os arquivos ficavam soltos na raiz (só existia uma igreja). Move para a pasta
    da igreja original. Idempotente: sem arquivos soltos, não faz nada."""
    raiz = _raiz()
    soltos = [p for p in raiz.iterdir() if p.is_file() and not p.name.endswith(".tmp")]
    if not soltos:
        return 0
    destino = raiz / str(IGREJA_ORIGINAL)
    destino.mkdir(parents=True, exist_ok=True)
    for p in soltos:
        shutil.move(str(p), str(destino / p.name))
    return len(soltos)


def caminho(nome: str) -> Path | None:
    """Caminho local do arquivo da igreja atual, ou None se não existir."""
    p = _base() / Path(nome).name  # .name impede sair da pasta (../)
    return p if p.is_file() else None


def salvar(nome: str, dados: bytes) -> None:
    p = _base() / Path(nome).name
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(dados)
    tmp.replace(p)  # troca atômica: quem estiver lendo nunca vê arquivo pela metade


def remover(nome: str) -> None:
    (_base() / Path(nome).name).unlink(missing_ok=True)
