"""Qual igreja (tenant) está atendendo a requisição.

A igreja vem do domínio (cabeçalho Host): `dominio_proprio` exato ou `<subdominio>.<DOMINIO_BASE>`.
Em instalações de uma igreja só (e nos testes), IGREJA_PADRAO_ID vale para hosts desconhecidos.
O resultado fica numa ContextVar para o padrão de `igreja_id` nos modelos e para o `set_config` do
Postgres que liga o RLS (ver database.py).
"""
import time
from contextvars import ContextVar
from typing import Optional

from sqlalchemy import text

from config import settings

igreja_atual: ContextVar[Optional[int]] = ContextVar("igreja_atual", default=None)

SUSPENSA = 0  # host reconhecido, mas a igreja está inativa

_cache: dict[str, tuple[float, Optional[int]]] = {}
_TTL = 30.0
_MAX_CACHE = 1000


def igreja_do_contexto() -> int:
    """Padrão do `igreja_id` ao gravar: a igreja da requisição em andamento."""
    valor = igreja_atual.get()
    if valor is None:
        raise RuntimeError("Nenhuma igreja definida para esta operação (use sessao_da_igreja ou uma rota com tenant).")
    return valor


def normalizar_host(host: str) -> str:
    h = (host or "").strip().lower().split(":")[0].rstrip(".")
    return h[4:] if h.startswith("www.") else h


def limpar_cache() -> None:
    _cache.clear()


async def resolver_igreja(host: str) -> Optional[int]:
    """id da igreja do host; SUSPENSA (0) se inativa; None se o host não é de nenhuma igreja."""
    from database import engine  # import tardio: database importa este módulo

    h = normalizar_host(host)
    agora = time.monotonic()
    hit = _cache.get(h)
    if hit and agora - hit[0] < _TTL:
        return hit[1]

    base = settings.dominio_base.strip().lower()
    async with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            valor = await conn.scalar(text("SELECT igreja_por_host(:h, :b)"), {"h": h, "b": base})
        else:
            linha = (await conn.execute(
                text(
                    "SELECT id, ativa FROM igrejas "
                    "WHERE lower(dominio_proprio) = :h OR (:b <> '' AND :h = lower(subdominio) || '.' || :b) "
                    "ORDER BY (lower(dominio_proprio) = :h) DESC LIMIT 1"
                ),
                {"h": h, "b": base},
            )).first()
            valor = None if linha is None else (linha[0] if linha[1] else SUSPENSA)

    if len(_cache) >= _MAX_CACHE:
        _cache.clear()  # evita crescer sem limite com Hosts aleatórios
    _cache[h] = (agora, valor)
    return valor
