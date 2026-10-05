"""
Armazenamento de arquivos enviados (hoje: logo da igreja e ícones gerados).

Grava no disco, em `settings.uploads_dir` (volume persistente em produção).
Para usar um bucket (S3, R2, Supabase Storage) no futuro, basta reimplementar
estas três funções mantendo as assinaturas.
"""

from pathlib import Path

from config import settings


def _base() -> Path:
    base = Path(settings.uploads_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def caminho(nome: str) -> Path | None:
    """Caminho local do arquivo, ou None se não existir."""
    p = _base() / Path(nome).name  # .name impede sair da pasta (../)
    return p if p.is_file() else None


def salvar(nome: str, dados: bytes) -> None:
    p = _base() / Path(nome).name
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(dados)
    tmp.replace(p)  # troca atômica: quem estiver lendo nunca vê arquivo pela metade


def remover(nome: str) -> None:
    (_base() / Path(nome).name).unlink(missing_ok=True)
