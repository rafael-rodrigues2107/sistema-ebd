"""Teste local das solicitações de troca de turma — banco SQLite temporário."""
import os, secrets, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

DB = Path(__file__).parent / f"teste_trocas_{secrets.token_hex(3)}.db"
os.environ.update(DATABASE_URL=_banco.url(DB), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DEBUG="false", SECRET_KEY=secrets.token_hex(16))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.chdir(str(Path(__file__).resolve().parent.parent / "app"))

from fastapi.testclient import TestClient
from main import app

falhas = []
def check(desc, cond, extra=""):
    if not cond: falhas.append(desc)
    print(f"{'OK ' if cond else 'ERRO'}  {desc} {extra}")

with TestClient(app) as adm, TestClient(app) as pa, TestClient(app) as pb, TestClient(app) as anon:
    adm.post("/api/auth/login", json={"username": "admin", "senha": "admin123"})
    ta = adm.post("/api/turmas/", json={"nome": "Primários", "faixa_etaria": "6-8"}).json()["id"]
    tb = adm.post("/api/turmas/", json={"nome": "Pré-Adolescentes", "faixa_etaria": "9-12"}).json()["id"]
    t4 = adm.post("/api/trimestres/", json={"ano": 2026, "numero": 4}).json()["id"]
    dom = adm.get(f"/api/trimestres/{t4}/domingos").json()[0]["id"]

    def aluno(nome, turma):
        a = adm.post("/api/alunos/", json={"nome": nome}).json()["id"]
        adm.post("/api/matriculas/", json={"aluno_id": a, "turma_id": turma, "trimestre_id": t4})
        return a
    joao, maria, pedro = aluno("João", ta), aluno("Maria", ta), aluno("Pedro", tb)
    # chamada antiga do João na turma A (histórico deve ficar lá)
    adm.post(f"/api/turmas/{ta}/chamada", json={"trimestre_id": t4, "domingo_id": dom, "visitantes": [], "fechamento": {},
             "chamadas": [{"aluno_id": joao, "presente": True, "trouxe_biblia": False, "trouxe_revista": False}]})
    # próximo trimestre já gerado (João deve mudar nele também)
    t1 = adm.post("/api/trimestres/proximo").json()["id"]

    senhas = {u: secrets.token_urlsafe(10) for u in ("prof_a", "prof_b")}
    adm.post("/api/usuarios/", json={"nome": "Prof A", "username": "prof_a", "senha": senhas["prof_a"], "role": "professor", "turma_id": ta})
    adm.post("/api/usuarios/", json={"nome": "Prof B", "username": "prof_b", "senha": senhas["prof_b"], "role": "professor", "turma_id": tb})
    pa.post("/api/auth/login", json={"username": "prof_a", "senha": senhas["prof_a"]})
    pb.post("/api/auth/login", json={"username": "prof_b", "senha": senhas["prof_b"]})
    painel = lambda c, turma: c.get(f"/api/turmas/{turma}/painel?trimestre_id={t4}&domingo_id={dom}").json()

    print("== Pedido do professor")
    check("sem login: 401", anon.post("/api/trocas/", json={"aluno_id": joao, "turma_destino_id": tb}).status_code == 401)
    check("prof A pede troca de aluno da turma B: 403", pa.post("/api/trocas/", json={"aluno_id": pedro, "turma_destino_id": ta}).status_code == 403)
    check("pedir para a mesma turma: 400", pa.post("/api/trocas/", json={"aluno_id": joao, "turma_destino_id": ta}).status_code == 400)
    r = pa.post("/api/trocas/", json={"aluno_id": joao, "turma_destino_id": tb, "motivo": "Fez 9 anos"})
    check("prof A pede troca do João: 201", r.status_code == 201, str(r.status_code))
    tj = r.json()
    check("dados do pedido", (tj["aluno_nome"], tj["turma_origem_nome"], tj["turma_destino_nome"], tj["status"], tj["solicitante_nome"]) ==
          ("João", "Primários", "Pré-Adolescentes", "pendente", "Prof A"), str(tj))
    check("segundo pedido pro mesmo aluno: 409", pa.post("/api/trocas/", json={"aluno_id": joao, "turma_destino_id": tb}).status_code == 409)
    alunos_a = {a["nome"]: a for a in painel(pa, ta)["alunos"]}
    check("chamada A mostra 'troca pendente' no João", alunos_a["João"]["troca_pendente_para"] == "Pré-Adolescentes")
    check("Maria sem troca pendente", alunos_a["Maria"]["troca_pendente_para"] is None)
    check("João continua na turma A até aprovar", "João" in alunos_a)

    print("== Listagem e permissões")
    check("prof A vê o próprio pedido", len(pa.get("/api/trocas/").json()) == 1)
    check("prof B não vê pedidos do A", pb.get("/api/trocas/").json() == [])
    check("admin vê pendentes", len(adm.get("/api/trocas/?status_filtro=pendente").json()) == 1)
    check("professor não aprova: 403", pa.post(f"/api/trocas/{tj['id']}/aprovar", json={}).status_code == 403)
    check("professor não recusa: 403", pa.post(f"/api/trocas/{tj['id']}/recusar", json={}).status_code == 403)

    print("== Aprovação")
    r = adm.post(f"/api/trocas/{tj['id']}/aprovar", json={})
    check("admin aprova: 200", r.status_code == 200 and r.json()["status"] == "aprovada", str(r.status_code))
    check("aprovar de novo: 409", adm.post(f"/api/trocas/{tj['id']}/aprovar", json={}).status_code == 409)
    check("João saiu da chamada A", "João" not in {a["nome"] for a in painel(pa, ta)["alunos"]})
    check("João entrou na chamada B", "João" in {a["nome"] for a in painel(pb, tb)["alunos"]})
    mats = [m for m in adm.get("/api/matriculas/").json() if m["aluno_nome"] == "João"]
    check("matrículas do João: B no 4º/2026 e no 1º/2027", sorted((m["trimestre_id"], m["turma_nome"]) for m in mats) ==
          sorted([(t4, "Pré-Adolescentes"), (t1, "Pré-Adolescentes")]), str(mats))
    hist = adm.get(f"/api/alunos/{joao}/historico?trimestre_id={t4}").json()
    check("histórico: presença antiga continua registrada na turma A", hist["domingos"][0]["turma_nome"] == "Primários" and hist["domingos"][0]["presente"] is True)

    print("== Recusa e cancelamento")
    r = pa.post("/api/trocas/", json={"aluno_id": maria, "turma_destino_id": tb})
    r = adm.post(f"/api/trocas/{r.json()['id']}/recusar", json={"resposta": "Ainda tem 7 anos"})
    check("admin recusa com resposta", r.status_code == 200 and r.json()["status"] == "recusada" and r.json()["resposta"] == "Ainda tem 7 anos")
    check("Maria continua na turma A", "Maria" in {a["nome"] for a in painel(pa, ta)["alunos"]})
    r = pa.post("/api/trocas/", json={"aluno_id": maria, "turma_destino_id": tb})
    check("depois da recusa, pode pedir de novo", r.status_code == 201)
    check("prof B não cancela pedido do A: 403", pb.post(f"/api/trocas/{r.json()['id']}/cancelar").status_code == 403)
    check("prof A cancela o próprio pedido", pa.post(f"/api/trocas/{r.json()['id']}/cancelar").json()["status"] == "cancelada")

    print("== Aluno movido por fora antes da aprovação")
    r = pb.post("/api/trocas/", json={"aluno_id": pedro, "turma_destino_id": ta})
    adm.put(f"/api/alunos/{pedro}", json={"turma_id": ta})   # admin mudou direto pela aba Alunos
    a = adm.post(f"/api/trocas/{r.json()['id']}/aprovar", json={})
    check("aprovar pedido desatualizado: 409 com explicação", a.status_code == 409 and "não está mais" in a.json()["detail"], a.text[:120])
    mats = [m for m in adm.get("/api/matriculas/").json() if m["aluno_nome"] == "Pedro"]
    check("edição direta do admin muda o trimestre atual e o já gerado", sorted((m["trimestre_id"], m["turma_nome"]) for m in mats) ==
          sorted([(t4, "Primários"), (t1, "Primários")]), str([(m["trimestre_id"], m["turma_nome"]) for m in mats]))
    check("Pedro aparece na chamada A de hoje", "Pedro" in {a["nome"] for a in painel(pa, ta)["alunos"]})

print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{len(falhas)} FALHA(S): ' + '; '.join(falhas)}")
