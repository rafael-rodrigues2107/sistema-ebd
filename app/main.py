"""
FastAPI application — Sistema EBD (Escola Bíblica Dominical).

Entry point: uvicorn main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

import armazenamento
from config import settings
from database import init_db
from routers.alunos import router as alunos_router
from routers.auth import auth_router, usuarios_router
from routers.chamadas import router as chamadas_router
from routers.config_igreja import router as config_igreja_router
from routers.dashboard import router as dashboard_router
from routers.fechamento import router as fechamento_router
from routers.matriculas import router as matriculas_router
from routers.trimestres import router as trimestres_router
from routers.trocas import router as trocas_router
from routers.turmas import router as turmas_router
from seed import garantir_igreja_padrao, seed_admin
from tenant import SUSPENSA, resolver_igreja


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup / shutdown events."""
    # SQLite (dev/testes): cria as tabelas na hora. Postgres: o esquema vem do
    # Alembic (entrypoint.sh roda `alembic upgrade head` antes de subir o app).
    if settings.database_url.startswith("sqlite"):
        await init_db()
    armazenamento.migrar_arquivos_legados()
    await garantir_igreja_padrao()
    await seed_admin()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
    # Documentação automática da API só em desenvolvimento
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

@app.middleware("http")
async def identificar_igreja(request: Request, call_next):
    """Descobre a igreja pelo Host. Sem igreja não há dado nem página: 404 (ou 403 se suspensa)."""
    if request.url.path == "/healthz" or request.url.path.startswith("/interno/"):
        return await call_next(request)  # rotas de infraestrutura: não dependem da igreja
    igreja_id = await resolver_igreja(request.headers.get("host", ""))
    if igreja_id == SUSPENSA:
        return JSONResponse({"detail": "Esta igreja está com o acesso suspenso."}, status_code=403)
    if igreja_id is None:
        igreja_id = settings.igreja_padrao_id
    if igreja_id is None:
        return JSONResponse({"detail": "Igreja não encontrada."}, status_code=404)
    request.state.igreja_id = igreja_id
    return await call_next(request)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


@app.get("/interno/dominio-permitido", include_in_schema=False)
async def dominio_permitido(domain: str = ""):
    """O Caddy pergunta aqui antes de emitir certificado HTTPS para um domínio novo (on-demand TLS).
    200 só para domínio de igreja ATIVA. Só é alcançável pela rede interna do Docker: o Caddy bloqueia
    /interno/* para quem vem de fora."""
    igreja_id = await resolver_igreja(domain)
    if not igreja_id:  # None (desconhecido) ou 0 (suspensa)
        raise HTTPException(404)
    return {"ok": True}


# ── Routers da API ──
app.include_router(turmas_router)
app.include_router(trimestres_router)
app.include_router(chamadas_router)
app.include_router(alunos_router)
app.include_router(matriculas_router)
app.include_router(fechamento_router)
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(usuarios_router)
app.include_router(trocas_router)
app.include_router(config_igreja_router)

# ── Arquivos estáticos (frontend) ──
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/icons", StaticFiles(directory=str(static_dir / "icons")), name="icons")


@app.get("/")
async def raiz():
    return FileResponse(static_dir / "chamada.html")


@app.get("/cadastro.html")
async def cadastro():
    return FileResponse(static_dir / "cadastro.html")


@app.get("/fechamento.html")
async def fechamento():
    return FileResponse(static_dir / "fechamento.html")


@app.get("/dashboard.html")
async def dashboard():
    return FileResponse(static_dir / "dashboard.html")


@app.get("/login.html")
async def login_page():
    return FileResponse(static_dir / "login.html")


@app.get("/trocar-senha.html")
async def trocar_senha_page():
    return FileResponse(static_dir / "trocar-senha.html")


@app.get("/aluno.html")
async def aluno_page():
    return FileResponse(static_dir / "aluno.html")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(static_dir / "sw.js", media_type="application/javascript")
