"""Fase 5b: senha temporária (usuarios.trocar_senha) obriga a troca antes de qualquer outra coisa.

Roda em SQLite e em Postgres. A redefinição pela CLI do dono é testada em teste_igrejas_dono.py.
"""
import os, secrets, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

DB = Path(__file__).parent / f"teste_senha_{secrets.token_hex(3)}.db"
os.environ.update(DATABASE_URL=_banco.url(DB), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DEBUG="false",
                  SECRET_KEY=secrets.token_hex(16))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.chdir(str(Path(__file__).resolve().parent.parent / "app"))

from fastapi.testclient import TestClient
from main import app

falhas = []


def check(desc, ok):
    print(f"{'OK  ' if ok else 'ERRO'} {desc}")
    if not ok:
        falhas.append(desc)


NOVA = "NovaSenha-123"
try:
    with TestClient(app) as adm:
        adm.post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN})
        check("usuário normal: login sem troca obrigatória",
              adm.post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN}).json()["trocar_senha"] is False)
        check("usuário normal acessa a API", adm.get("/api/alunos/").status_code == 200)

        _banco.sql(DB, "update usuarios set trocar_senha=? where username=?", (True, "admin"))
        check("com o flag ligado, a sessão já aberta é barrada (403, Troca de senha obrigatória)",
              (lambda r: r.status_code == 403 and r.json()["detail"] == "Troca de senha obrigatória")(adm.get("/api/alunos/")))
        check("usuários e config também (403)", adm.get("/api/usuarios/").status_code == 403)
        check("/me e logout continuam funcionando", adm.get("/api/auth/me").status_code == 200 and adm.post("/api/auth/logout").status_code == 200)

        r = adm.post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN})
        check("login com senha temporária funciona e avisa", r.status_code == 200 and r.json()["trocar_senha"] is True)
        check("sem login não dá para trocar senha",
              TestClient(app).post("/api/auth/trocar-senha", json={"senha_atual": "x", "senha_nova": NOVA}).status_code == 401)
        check("senha atual errada: 400",
              adm.post("/api/auth/trocar-senha", json={"senha_atual": "errada", "senha_nova": NOVA}).status_code == 400)
        check("senha nova curta: 422",
              adm.post("/api/auth/trocar-senha", json={"senha_atual": _banco.SENHA_ADMIN, "senha_nova": "1234567"}).status_code == 422)
        check("senha nova igual à atual: 400",
              adm.post("/api/auth/trocar-senha", json={"senha_atual": _banco.SENHA_ADMIN, "senha_nova": _banco.SENHA_ADMIN}).status_code == 400)
        check("ainda barrado depois das tentativas falhas", adm.get("/api/alunos/").status_code == 403)
        check("troca OK", adm.post("/api/auth/trocar-senha", json={"senha_atual": _banco.SENHA_ADMIN, "senha_nova": NOVA}).status_code == 200)
        check("liberado: API volta a funcionar com a mesma sessão", adm.get("/api/alunos/").status_code == 200)
        check("a senha antiga não vale mais",
              TestClient(app).post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN}).status_code == 401)
        r = TestClient(app).post("/api/auth/login", json={"username": "admin", "senha": NOVA})
        check("a nova senha vale e não exige nova troca", r.status_code == 200 and r.json()["trocar_senha"] is False)
        check("a página de troca existe", TestClient(app).get("/trocar-senha.html").status_code == 200)
finally:
    try:
        DB.unlink(missing_ok=True)
    except OSError:  # Windows: o SQLite ainda segura o arquivo
        pass

print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\nFALHARAM {len(falhas)}: {falhas}")
sys.exit(1 if falhas else 0)
