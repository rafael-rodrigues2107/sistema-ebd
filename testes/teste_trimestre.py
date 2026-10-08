"""Teste local do 'Gerar próximo trimestre' — banco SQLite temporário."""
import os, secrets, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

DB = Path(__file__).parent / f"teste_trim_{secrets.token_hex(3)}.db"
os.environ.update(DATABASE_URL=_banco.url(DB), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DEBUG="false", SECRET_KEY=secrets.token_hex(16))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.chdir(str(Path(__file__).resolve().parent.parent / "app"))

from fastapi.testclient import TestClient
from main import app

falhas = []
def check(desc, cond, extra=""):
    if not cond: falhas.append(desc)
    print(f"{'OK ' if cond else 'ERRO'}  {desc} {extra}")

with TestClient(app) as adm, TestClient(app) as prof:
    adm.post("/api/auth/login", json={"username": "admin", "senha": "admin123"})
    ta = adm.post("/api/turmas/", json={"nome": "Efraim", "faixa_etaria": "Adultos"}).json()["id"]
    tb = adm.post("/api/turmas/", json={"nome": "Maternal", "faixa_etaria": "Criancas"}).json()["id"]
    tc = adm.post("/api/turmas/", json={"nome": "Turma Extinta", "faixa_etaria": "X"}).json()["id"]
    t2 = adm.post("/api/trimestres/", json={"ano": 2026, "numero": 2}).json()["id"]
    adm.post("/api/trimestres/", json={"ano": 2026, "numero": 3})
    t4 = adm.post("/api/trimestres/", json={"ano": 2026, "numero": 4}).json()["id"]

    def aluno(nome, turma, trim):
        a = adm.post("/api/alunos/", json={"nome": nome}).json()["id"]
        adm.post("/api/matriculas/", json={"aluno_id": a, "turma_id": turma, "trimestre_id": trim})
        return a
    for i in range(3): aluno(f"A{i}", ta, t4)
    for i in range(2): aluno(f"B{i}", tb, t4)
    inativo = aluno("Saiu", ta, t4)
    adm.delete(f"/api/alunos/{inativo}")                 # aluno inativo: não copia
    aluno("Velho", ta, t2)                                 # só no 2º tri: não copia
    aluno("Na extinta", tc, t4)
    _banco.sql(DB, "update turmas set ativo=false where id=?", (tc,))

    print("== Prévia")
    p = adm.get("/api/trimestres/proximo").json()
    check("próximo é 1º/2027", (p["ano"], p["numero"]) == (2027, 1), str((p["ano"], p["numero"])))
    check("período 01/01 a 31/03/2027", (p["data_inicio"], p["data_fim"]) == ("2027-01-01", "2027-03-31"))
    check("13 domingos", p["total_domingos"] == 13, str(p["total_domingos"]))
    check("origem é 4º/2026", (p["origem"]["ano"], p["origem"]["numero"]) == (2026, 4))
    check("5 matrículas (sem inativo, sem turma extinta)", p["total_matriculas"] == 5, str(p["total_matriculas"]))
    check("por turma Efraim=3 Maternal=2", {t["turma_nome"]: t["total"] for t in p["turmas"]} == {"Efraim": 3, "Maternal": 2}, str(p["turmas"]))
    total_trim_antes = len(adm.get("/api/trimestres/").json())
    check("prévia não grava nada", total_trim_antes == 3)

    print("== Gerar")
    r = adm.post("/api/trimestres/proximo")
    check("POST 201", r.status_code == 201, str(r.status_code))
    novo = r.json()
    doms = adm.get(f"/api/trimestres/{novo['id']}/domingos").json()
    check("13 domingos criados, 1º em 03/01/2027", len(doms) == 13 and doms[0]["data"] == "2027-01-03", f"{len(doms)} {doms[0]['data'] if doms else ''}")
    mats = [m for m in adm.get("/api/matriculas/").json() if m["trimestre_id"] == novo["id"]]
    check("5 matrículas copiadas", len(mats) == 5, str(len(mats)))
    check("data_matricula = 01/01/2027", all(m["data_matricula"] == "2027-01-01" for m in mats))
    check("turmas preservadas", sorted(m["turma_nome"] for m in mats) == ["Efraim"] * 3 + ["Maternal"] * 2)

    print("== Depois de gerar")
    ativo = adm.get("/api/trimestres/ativo").json()
    check("chamada continua no 4º/2026 hoje (04/10/2026)", (ativo["ano"], ativo["numero"]) == (2026, 4), str((ativo["ano"], ativo["numero"])))
    p2 = adm.get("/api/trimestres/proximo").json()
    check("próxima prévia vira 2º/2027 com origem 1º/2027", (p2["ano"], p2["numero"], p2["origem"]["ano"], p2["origem"]["numero"]) == (2027, 2, 2027, 1))

    print("== Permissões")
    senha = secrets.token_urlsafe(10)
    adm.post("/api/usuarios/", json={"nome": "P", "username": "prof_t", "senha": senha, "role": "professor", "turma_id": ta})
    prof.post("/api/auth/login", json={"username": "prof_t", "senha": senha})
    check("professor: GET prévia 403", prof.get("/api/trimestres/proximo").status_code == 403)
    check("professor: POST gerar 403", prof.post("/api/trimestres/proximo").status_code == 403)
    with TestClient(app) as anon:
        check("sem login: POST gerar 401", anon.post("/api/trimestres/proximo").status_code == 401)
    check("form manual ainda funciona (2028/1)", adm.post("/api/trimestres/", json={"ano": 2028, "numero": 1}).status_code == 201)
    check("form manual recusa duplicado", adm.post("/api/trimestres/", json={"ano": 2028, "numero": 1}).status_code == 409)

print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{len(falhas)} FALHA(S): ' + '; '.join(falhas)}")
