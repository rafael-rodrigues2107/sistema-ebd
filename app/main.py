"""
FastAPI application — Sistema EBD (Escola Bíblica Dominical).

Entry point: uvicorn main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import settings
from database import init_db
from routers.chamadas import router as chamadas_router
from routers.trimestres import router as trimestres_router
from routers.turmas import router as turmas_router
from seed import seed as executar_seed


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup / shutdown events."""
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# ── Routers da API ──
app.include_router(turmas_router)
app.include_router(trimestres_router)
app.include_router(chamadas_router)

# ── Arquivos estáticos (frontend) ──
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.post("/api/seed", tags=["Seed"])
async def seed_endpoint():
    """Popula o banco com dados de exemplo (idempotente)."""
    await executar_seed()
    return {"ok": True, "message": "Seed executado com sucesso"}


@app.get("/")
async def raiz():
    """Redireciona para a tela de chamada."""
    return FileResponse(static_dir / "chamada.html")
