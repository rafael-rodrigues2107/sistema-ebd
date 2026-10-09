"""
Autenticação JWT e gerenciamento de usuários.
Token armazenado em cookie httpOnly (ebd_session) — não exposto no localStorage.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
import bcrypt as _bcrypt

from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_session
from models import Turma, Usuario
from schemas import (
    LoginRequest,
    TokenResponse,
    TrocarSenhaRequest,
    UsuarioCreate,
    UsuarioRead,
    UsuarioUpdate,
)

# ── Criptografia ──────────────────────────────────────────────────────────────
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8
COOKIE_NAME = "ebd_session"

_401 = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciais inválidas ou expiradas",
)
_403 = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores")


def hash_senha(senha: str) -> str:
    return _bcrypt.hashpw(senha.encode(), _bcrypt.gensalt(rounds=12)).decode()


def verificar_senha(senha: str, hash_: str) -> bool:
    try:
        return _bcrypt.checkpw(senha.encode(), hash_.encode())
    except Exception:
        return False


def criar_token(user_id: int, role: str, igreja_id: Optional[int] = None) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    claims = {"sub": str(user_id), "role": role, "exp": expire}
    if igreja_id is not None:
        claims["ig"] = igreja_id  # igreja que emitiu o token (conferida a cada requisição)
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)


def _extrair_token(request: Request) -> Optional[str]:
    """Lê token do cookie httpOnly ou, como fallback, do header Authorization."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token or None


# ── Dependências de autenticação ──────────────────────────────────────────────
async def usuario_da_sessao(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Usuario:
    """Usuário do token, mesmo com troca de senha pendente (só /me, /logout e /trocar-senha usam isto)."""
    token = _extrair_token(request)
    if not token:
        raise _401
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise _401
    except JWTError:
        raise _401
    # Token de outra igreja nunca vale (o RLS já esconderia o usuário; aqui é a segunda trava).
    # Tokens emitidos antes da fase 4 não têm "ig" e continuam valendo até expirarem (8 h).
    igreja_do_token = payload.get("ig")
    if igreja_do_token is not None and igreja_do_token != getattr(request.state, "igreja_id", None):
        raise _401
    user = await session.get(Usuario, int(user_id))
    if not user or not user.ativo:
        raise _401
    return user


SENHA_TEMPORARIA = "Troca de senha obrigatória"


async def get_current_user(user: Usuario = Depends(usuario_da_sessao)) -> Usuario:
    """Usuário autenticado e liberado. Com senha temporária pendente, tudo fora da troca de senha dá 403."""
    if user.trocar_senha:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SENHA_TEMPORARIA)
    return user


async def require_admin(user: Usuario = Depends(get_current_user)) -> Usuario:
    if user.role != "admin":
        raise _403
    return user


def _to_read(u: Usuario) -> UsuarioRead:
    return UsuarioRead(
        id=u.id,
        nome=u.nome,
        username=u.username,
        role=u.role,
        turma_id=u.turma_id,
        turma_nome=u.turma.nome if u.turma else None,
        ativo=u.ativo,
    )


def _set_auth_cookie(response: Response, token: str, is_secure: bool) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=TOKEN_EXPIRE_HOURS * 3600,
        secure=is_secure,
        path="/",
    )


# ── Routers ───────────────────────────────────────────────────────────────────
auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])
usuarios_router = APIRouter(prefix="/api/usuarios", tags=["Usuários"])


# ── Auth ──────────────────────────────────────────────────────────────────────

@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    igreja_id = getattr(request.state, "igreja_id", None)
    result = await session.execute(
        select(Usuario).where(Usuario.username == body.username, Usuario.igreja_id == igreja_id)
    )  # filtro explícito além do RLS: o login é a consulta mais sensível
    user = result.scalar_one_or_none()
    if not user or not verificar_senha(body.senha, user.senha_hash) or not user.ativo:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")

    token = criar_token(user.id, user.role, getattr(request.state, "igreja_id", None))
    is_secure = request.url.scheme == "https"
    _set_auth_cookie(response, token, is_secure)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        nome=user.nome,
        turma_id=user.turma_id,
        trocar_senha=user.trocar_senha,
    )


@auth_router.post("/trocar-senha")
async def trocar_senha(
    body: TrocarSenhaRequest,
    user: Usuario = Depends(usuario_da_sessao),
    session: AsyncSession = Depends(get_session),
):
    if not verificar_senha(body.senha_atual, user.senha_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    if body.senha_nova == body.senha_atual:
        raise HTTPException(status_code=400, detail="A nova senha deve ser diferente da atual")
    user.senha_hash = hash_senha(body.senha_nova)
    user.trocar_senha = False
    await session.commit()
    return {"ok": True}


@auth_router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@auth_router.get("/me")
async def me(user: Usuario = Depends(usuario_da_sessao)):
    return {
        "id": user.id,
        "nome": user.nome,
        "username": user.username,
        "role": user.role,
        "turma_id": user.turma_id,
        "trocar_senha": user.trocar_senha,
    }


# ── Usuários (admin) ──────────────────────────────────────────────────────────

@usuarios_router.get("/", response_model=list[UsuarioRead])
async def listar_usuarios(
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Usuario).order_by(Usuario.nome))
    return [_to_read(u) for u in result.scalars().all()]


@usuarios_router.post("/", response_model=UsuarioRead, status_code=status.HTTP_201_CREATED)
async def criar_usuario(
    body: UsuarioCreate,
    _admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    dup = await session.execute(select(Usuario).where(Usuario.username == body.username))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username já está em uso")

    user = Usuario(
        nome=body.nome,
        username=body.username,
        senha_hash=hash_senha(body.senha),
        role=body.role,
        turma_id=body.turma_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _to_read(user)


@usuarios_router.put("/{usuario_id}", response_model=UsuarioRead)
async def atualizar_usuario(
    usuario_id: int,
    body: UsuarioUpdate,
    admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(Usuario, usuario_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    dados = body.model_dump(exclude_unset=True)

    if "username" in dados:
        dup = await session.execute(
            select(Usuario).where(Usuario.username == dados["username"], Usuario.id != usuario_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username já está em uso")
        user.username = dados["username"]

    if "nome"     in dados: user.nome      = dados["nome"]
    if "senha"    in dados: user.senha_hash = hash_senha(dados["senha"])
    if "role"     in dados: user.role      = dados["role"]
    if "turma_id" in dados: user.turma_id  = dados["turma_id"]
    if "ativo"    in dados: user.ativo     = dados["ativo"]

    await session.commit()
    await session.refresh(user)
    return _to_read(user)


@usuarios_router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_usuario(
    usuario_id: int,
    admin: Usuario = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if usuario_id == admin.id:
        raise HTTPException(status_code=400, detail="Não é possível remover seu próprio usuário")

    user = await session.get(Usuario, usuario_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if user.role == "admin":
        count = await session.scalar(
            select(func.count(Usuario.id)).where(Usuario.role == "admin", Usuario.ativo == True)
        )
        if (count or 0) <= 1:
            raise HTTPException(status_code=400, detail="Não é possível remover o único administrador")

    await session.delete(user)
    await session.commit()
