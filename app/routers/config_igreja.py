"""
Configurações da Igreja — identidade visual da instalação.

- GET  /api/config          dados públicos (a tela de login precisa antes do login)
- PUT  /api/config          nome da igreja, nome do app e cor (admin)
- POST /api/config/logo     upload do logo; gera os ícones do app (admin)
- DELETE /api/config/logo   volta ao ícone padrão (admin)
- GET  /marca/{arquivo}     logo e ícones (com fallback para os padrões)
- GET  /manifest.json       manifesto do PWA com nome, cor e ícones da igreja
"""

import io
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import armazenamento
from database import get_session
from models import ConfiguracaoIgreja, Usuario
from routers.auth import require_admin

router = APIRouter(tags=["Configurações da Igreja"])

PADRAO_NOME_IGREJA = "Sistema EBD"
PADRAO_NOME_APP = "EBD"
PADRAO_COR = "#4f46e5"
FUNDO_ICONE = (255, 255, 255, 255)
TAMANHO_MAX_UPLOAD = 5 * 1024 * 1024

# arquivo -> (tamanho, tipo). "any": logo sobre transparente; "maskable"/"apple": fundo sólido
ICONES = {
    "icon-192.png":         (192, "any"),
    "icon-512.png":         (512, "any"),
    "maskable-192.png":     (192, "maskable"),
    "maskable-512.png":     (512, "maskable"),
    "apple-touch-icon.png": (180, "apple"),
}
ARQUIVOS_MARCA = {"logo.png", *ICONES}
_ICONES_PADRAO = Path(__file__).parent.parent / "static" / "icons"
_PADRAO_ESTATICO = {  # sem logo enviado, os ícones originais do sistema
    "icon-192.png": "icon-192.png", "maskable-192.png": "icon-192.png", "apple-touch-icon.png": "icon-192.png",
    "icon-512.png": "icon-512.png", "maskable-512.png": "icon-512.png",
}


# ── Schemas ───────────────────────────────────────────────────────────────────
class ConfigRead(BaseModel):
    nome_igreja: str
    nome_app: str
    cor_primaria: str
    logo_url: str | None
    versao: int


class ConfigUpdate(BaseModel):
    nome_igreja: str = Field(..., min_length=1, max_length=120)
    nome_app: str = Field(..., min_length=1, max_length=15)
    cor_primaria: str

    @field_validator("nome_igreja", "nome_app")
    @classmethod
    def _limpa(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("não pode ficar vazio")
        return v

    @field_validator("cor_primaria")
    @classmethod
    def _cor(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", v):
            raise ValueError("use o formato #rrggbb")
        if _contraste_com_branco(v) < 3:
            raise ValueError("cor muito clara: o texto branco dos botões ficaria ilegível. Escolha um tom mais escuro")
        return v


# ── Auxiliares ────────────────────────────────────────────────────────────────
def _contraste_com_branco(cor: str) -> float:
    def canal(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
    lum = 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)
    return 1.05 / (lum + 0.05)


async def _obter(session: AsyncSession) -> ConfiguracaoIgreja | None:
    return (await session.execute(select(ConfiguracaoIgreja).limit(1))).scalar_one_or_none()


def _to_read(cfg: ConfiguracaoIgreja | None) -> ConfigRead:
    versao = (cfg.logo_versao if cfg else None) or 0
    return ConfigRead(
        nome_igreja=(cfg and cfg.nome_igreja) or PADRAO_NOME_IGREJA,
        nome_app=(cfg and cfg.nome_app) or PADRAO_NOME_APP,
        cor_primaria=(cfg and cfg.cor_primaria) or PADRAO_COR,
        logo_url=f"/marca/logo.png?v={versao}" if versao else None,
        versao=versao,
    )


def _logo_e_claro(img: Image.Image) -> bool:
    """Logo quase todo branco/claro sumiria no fundo branco do ícone."""
    pequeno = img.resize((64, 64))
    pixels = [(r, g, b) for r, g, b, a in pequeno.getdata() if a > 128]
    if not pixels:
        return False
    lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels) / len(pixels)
    return lum > 215


def _encaixar(logo: Image.Image, lado: int, fracao: float, fundo: tuple[int, int, int, int]) -> Image.Image:
    """Logo centralizado num quadrado `lado`×`lado`, ocupando até `fracao` do lado."""
    copia = logo.copy()
    copia.thumbnail((int(lado * fracao), int(lado * fracao)), Image.LANCZOS)
    quadro = Image.new("RGBA", (lado, lado), fundo)
    quadro.alpha_composite(copia, ((lado - copia.width) // 2, (lado - copia.height) // 2))
    return quadro


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _gerar_arquivos(dados: bytes, cor_primaria: str) -> dict[str, bytes]:
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "Arquivo não é uma imagem válida. Envie PNG, JPG ou WEBP.")
    if img.format not in ("PNG", "JPEG", "WEBP"):
        raise HTTPException(400, "Formato não aceito. Envie PNG, JPG ou WEBP.")

    img = ImageOps.exif_transpose(img).convert("RGBA")  # fotos de celular vêm deitadas
    caixa = img.getchannel("A").getbbox()               # corta bordas transparentes
    if caixa:
        img = img.crop(caixa)
    if min(img.size) < 64:
        raise HTTPException(400, "Imagem muito pequena. Use um logo com pelo menos 256×256 pixels.")

    r, g, b = (int(cor_primaria[i:i + 2], 16) for i in (1, 3, 5))
    fundo = (r, g, b, 255) if _logo_e_claro(img) else FUNDO_ICONE

    logo = img.copy()
    logo.thumbnail((512, 512), Image.LANCZOS)
    arquivos = {"logo.png": _png(logo)}
    for nome, (lado, tipo) in ICONES.items():
        if tipo == "any":
            quadro = _encaixar(img, lado, 0.92, (0, 0, 0, 0))
        elif tipo == "maskable":
            quadro = _encaixar(img, lado, 0.62, fundo)   # zona segura dos ícones redondos
        else:
            quadro = _encaixar(img, lado, 0.78, fundo).convert("RGB")  # iPhone não aceita transparência
        arquivos[nome] = _png(quadro)
    return arquivos


# ── Rotas ─────────────────────────────────────────────────────────────────────
@router.get("/api/config", response_model=ConfigRead)
async def obter_config(session: AsyncSession = Depends(get_session)):
    return _to_read(await _obter(session))


@router.put("/api/config", response_model=ConfigRead)
async def salvar_config(
    body: ConfigUpdate,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    cfg = await _obter(session) or ConfiguracaoIgreja()
    cfg.nome_igreja = body.nome_igreja
    cfg.nome_app = body.nome_app
    cfg.cor_primaria = body.cor_primaria
    session.add(cfg)
    await session.commit()
    return _to_read(cfg)


@router.post("/api/config/logo", response_model=ConfigRead)
async def enviar_logo(
    arquivo: UploadFile = File(...),
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    dados = await arquivo.read(TAMANHO_MAX_UPLOAD + 1)
    if len(dados) > TAMANHO_MAX_UPLOAD:
        raise HTTPException(413, "Imagem maior que 5 MB. Envie um arquivo menor.")

    cfg = await _obter(session) or ConfiguracaoIgreja()
    for nome, conteudo in _gerar_arquivos(dados, cfg.cor_primaria or PADRAO_COR).items():
        armazenamento.salvar(nome, conteudo)

    cfg.logo_versao = int(time.time())
    session.add(cfg)
    await session.commit()
    return _to_read(cfg)


@router.delete("/api/config/logo", response_model=ConfigRead)
async def remover_logo(
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    cfg = await _obter(session)
    if cfg and cfg.logo_versao:
        cfg.logo_versao = None
        await session.commit()
        for nome in ARQUIVOS_MARCA:
            armazenamento.remover(nome)
    return _to_read(cfg)


@router.get("/marca/{arquivo}", include_in_schema=False)
async def arquivo_marca(arquivo: str, session: AsyncSession = Depends(get_session)):
    if arquivo not in ARQUIVOS_MARCA:
        raise HTTPException(404)
    cfg = await _obter(session)
    sem_cache = {"Cache-Control": "no-cache"}  # sempre revalida: logo novo aparece logo
    if cfg and cfg.logo_versao and (p := armazenamento.caminho(arquivo)):
        return FileResponse(p, media_type="image/png", headers=sem_cache)
    if arquivo in _PADRAO_ESTATICO:
        return FileResponse(_ICONES_PADRAO / _PADRAO_ESTATICO[arquivo], media_type="image/png", headers=sem_cache)
    raise HTTPException(404)


@router.get("/manifest.json", include_in_schema=False)
async def manifest(session: AsyncSession = Depends(get_session)):
    c = _to_read(await _obter(session))
    v = f"?v={c.versao}"
    return JSONResponse(
        {
            "name": c.nome_igreja,
            "short_name": c.nome_app,
            "description": "Escola Bíblica Dominical — chamada e gestão de turmas",
            "start_url": "/",
            "display": "standalone",
            "orientation": "portrait-primary",
            "background_color": "#f1f5f9",
            "theme_color": c.cor_primaria,
            "lang": "pt-BR",
            "icons": [
                {"src": f"/marca/icon-192.png{v}", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": f"/marca/icon-512.png{v}", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": f"/marca/maskable-192.png{v}", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
                {"src": f"/marca/maskable-512.png{v}", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
            "categories": ["education", "productivity"],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )
