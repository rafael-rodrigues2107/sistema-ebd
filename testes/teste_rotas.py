"""Teste local da proteção de rotas — banco SQLite temporário no scratchpad."""
import os, secrets, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

SCRATCH = Path(__file__).parent
DB = SCRATCH / "teste_rotas.db"
if DB.exists():
    DB.unlink()
os.environ["DATABASE_URL"] = _banco.url(DB)
os.environ["ADMIN_INITIAL_PASSWORD"] = _banco.SENHA_ADMIN
os.environ["SECRET_KEY"] = secrets.token_hex(16)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.chdir(str(Path(__file__).resolve().parent.parent / "app"))

from fastapi.testclient import TestClient
from main import app

falhas = []
def check(desc, resp, esperado):
    ok = resp.status_code == esperado
    if not ok:
        falhas.append(desc)
    print(f"{'OK ' if ok else 'ERRO'} {resp.status_code} (esperado {esperado})  {desc}")

with TestClient(app) as anon, TestClient(app) as adm, TestClient(app) as prof:
    # ── Preparação como admin (admin padrão criado pelo seed_admin em banco vazio)
    assert adm.post("/api/auth/login", json={"username": "admin", "senha": "admin123"}).status_code == 200
    ta = adm.post("/api/turmas/", json={"nome": "Turma A", "faixa_etaria": "Adultos"}).json()["id"]
    tb = adm.post("/api/turmas/", json={"nome": "Turma B", "faixa_etaria": "Jovens"}).json()["id"]
    tri = adm.post("/api/trimestres/", json={"ano": 2026, "numero": 4}).json()["id"]
    dom = adm.get(f"/api/trimestres/{tri}/domingos").json()[0]["id"]
    ax = adm.post("/api/alunos/", json={"nome": "Aluno X"}).json()["id"]
    ay = adm.post("/api/alunos/", json={"nome": "Aluno Y"}).json()["id"]
    adm.post("/api/matriculas/", json={"aluno_id": ax, "turma_id": ta, "trimestre_id": tri})
    adm.post("/api/matriculas/", json={"aluno_id": ay, "turma_id": tb, "trimestre_id": tri})
    senha_prof = secrets.token_urlsafe(12)
    adm.post("/api/usuarios/", json={"nome": "Prof A", "username": "prof_a", "senha": senha_prof, "role": "professor", "turma_id": ta})
    assert prof.post("/api/auth/login", json={"username": "prof_a", "senha": senha_prof}).status_code == 200

    chamada = lambda turma: {"trimestre_id": tri, "domingo_id": dom, "chamadas": [], "visitantes": [], "fechamento": {}}
    painel = lambda turma: f"/api/turmas/{turma}/painel?trimestre_id={tri}&domingo_id={dom}"

    print("\n== Sem login: tudo da API bloqueado (401), páginas e login abertos")
    check("GET /", anon.get("/"), 200)
    check("GET /login.html", anon.get("/login.html"), 200)
    check("GET /static/sessao.js", anon.get("/static/sessao.js?v=1"), 200)
    for url in ["/api/turmas/", f"/api/turmas/{ta}", "/api/trimestres/", "/api/trimestres/ativo",
                f"/api/trimestres/{tri}/domingos", "/api/alunos/", "/api/matriculas/",
                painel(ta), f"/api/alunos/{ax}/historico?trimestre_id={tri}", "/api/usuarios/",
                f"/api/dashboard/dados?trimestre_id={tri}", f"/api/fechamento/{dom}"]:
        check(f"GET {url}", anon.get(url), 401)
    check("POST /api/alunos/", anon.post("/api/alunos/", json={"nome": "Invasor"}), 401)
    check("POST /api/turmas/", anon.post("/api/turmas/", json={"nome": "X", "faixa_etaria": "X"}), 401)
    check("PUT /api/turmas/{id}", anon.put(f"/api/turmas/{ta}", json={"nome": "X", "faixa_etaria": "X"}), 401)
    check("POST /api/trimestres/", anon.post("/api/trimestres/", json={"ano": 2027, "numero": 1}), 401)
    check("POST /api/matriculas/", anon.post("/api/matriculas/", json={"aluno_id": ax, "turma_id": tb, "trimestre_id": tri}), 401)
    check("POST chamada", anon.post(f"/api/turmas/{ta}/chamada", json=chamada(ta)), 401)

    print("\n== Token inválido")
    falso = TestClient(app, cookies={"ebd_session": "token.falso.qualquer"})
    check("GET /api/turmas/ com token falso", falso.get("/api/turmas/"), 401)

    print("\n== Professor da Turma A")
    check("GET /api/turmas/", prof.get("/api/turmas/"), 200)
    check("GET /api/trimestres/ativo", prof.get("/api/trimestres/ativo"), 200)
    check("GET domingos", prof.get(f"/api/trimestres/{tri}/domingos"), 200)
    check("GET painel da própria turma", prof.get(painel(ta)), 200)
    check("GET painel de outra turma", prof.get(painel(tb)), 403)
    check("POST chamada da própria turma", prof.post(f"/api/turmas/{ta}/chamada", json=chamada(ta)), 200)
    check("POST chamada de outra turma", prof.post(f"/api/turmas/{tb}/chamada", json=chamada(tb)), 403)
    check("GET histórico de aluno da turma", prof.get(f"/api/alunos/{ax}/historico?trimestre_id={tri}"), 200)
    check("GET histórico de aluno de outra turma", prof.get(f"/api/alunos/{ay}/historico?trimestre_id={tri}"), 403)
    check("GET /api/alunos/ (lista geral)", prof.get("/api/alunos/"), 403)
    check("GET /api/matriculas/", prof.get("/api/matriculas/"), 403)
    check("POST /api/alunos/", prof.post("/api/alunos/", json={"nome": "Z"}), 403)
    check("POST /api/turmas/", prof.post("/api/turmas/", json={"nome": "Z", "faixa_etaria": "Z"}), 403)
    check("POST /api/trimestres/", prof.post("/api/trimestres/", json={"ano": 2027, "numero": 1}), 403)
    check("GET /api/usuarios/", prof.get("/api/usuarios/"), 403)

    print("\n== Admin continua com acesso total")
    check("GET /api/alunos/?incluir_inativos=true", adm.get("/api/alunos/?incluir_inativos=true"), 200)
    check("GET /api/matriculas/", adm.get("/api/matriculas/"), 200)
    check("GET painel de qualquer turma", adm.get(painel(tb)), 200)
    check("POST chamada de qualquer turma", adm.post(f"/api/turmas/{tb}/chamada", json=chamada(tb)), 200)
    check("GET histórico de qualquer aluno", adm.get(f"/api/alunos/{ay}/historico?trimestre_id={tri}"), 200)
    check("PUT /api/turmas/{id}", adm.put(f"/api/turmas/{ta}", json={"nome": "Turma A", "faixa_etaria": "Adultos"}), 200)

print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{len(falhas)} FALHA(S): ' + '; '.join(falhas)}")

