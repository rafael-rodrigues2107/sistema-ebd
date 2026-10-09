"""Fase 5: ferramenta do dono (scripts/igrejas.py): criar, listar, suspender, reativar e validar igrejas.

Só roda em Postgres (TEST_DATABASE_URL). A CLI é executada de verdade (subprocess), como o dono faria
dentro do container; o resto vai pelo app, com o Host de cada igreja.
"""
import json, os, re, secrets, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

if not _banco.PG:
    print("PULADO: defina TEST_DATABASE_URL=postgresql+asyncpg://... (SQLite não isola igrejas)")
    sys.exit(0)

RAIZ = Path(__file__).resolve().parent.parent
DB = Path(__file__).parent / f"teste_dono_{secrets.token_hex(3)}.db"
PASTA = Path(tempfile.mkdtemp(prefix="ebd_dono_"))
AUDITORIA = PASTA / "auditoria_dono.log"
os.environ.update(DATABASE_URL=_banco.url(DB), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DEBUG="false",
                  SECRET_KEY=secrets.token_hex(16), UPLOADS_DIR=str(PASTA / "uploads"),
                  DOMINIO_BASE="ebd.test", AUDITORIA_DONO_LOG=str(AUDITORIA))
sys.path.insert(0, str(RAIZ / "app"))
os.chdir(str(RAIZ / "app"))

from fastapi.testclient import TestClient

import tenant
from main import app

falhas = []


def check(desc, ok):
    print(f"{'OK  ' if ok else 'ERRO'} {desc}")
    if not ok:
        falhas.append(desc)


def cli(*args, entrada=""):  # stdin vazio = sem terminal
    """Roda scripts/igrejas.py como DONO (MIGRATION_DATABASE_URL), como no container."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "igrejas.py"), *args], cwd=RAIZ, env=env,
                       capture_output=True, text=True, encoding="utf-8", input=entrada)
    return r.returncode, r.stdout, r.stderr


def cliente(host):
    return TestClient(app, base_url=f"http://{host}", raise_server_exceptions=False)


def contar(tabela):
    import asyncpg, asyncio

    async def q():
        c = await asyncpg.connect(_banco.PG.replace("postgresql+asyncpg", "postgresql", 1))
        n = await c.fetchval(f"select count(*) from {tabela}")
        await c.close()
        return n
    return asyncio.run(q())


with TestClient(app):  # sobe o app: cria o admin da igreja 1 (IGREJA_PADRAO_ID=1)
    pass
_banco.sql(DB, "update igrejas set dominio_proprio=? where id=1", ("igreja1.test",))
tenant.limpar_cache()

# ── validação, sem gravar nada ──
ruins = {"www": "reservado", "api": "reservado", "admin": "reservado", "dp": "reservado", "Batista": "maiúscula",
         "a": "curto", "ab": "curto", "-batista": "hífen no início", "batista-": "hífen no fim",
         "bat_ista": "sublinhado", "bat ista": "espaço", "bat..ista": "ponto", "xn--abc": "punycode", "a--b": "hífen duplo",
         "x" * 64: "longo demais", "": "vazio"}
for sub, motivo in ruins.items():
    rc, _, err = cli("criar", "--nome", "Teste", f"--subdominio={sub}")
    check(f"subdomínio recusado ({motivo}): {sub[:20]!r}", rc == 2 and "RECUSADO" in err)
check("nenhuma igreja foi criada pelas recusas", contar("igrejas") == 1)
for dom, motivo in {"192.168.0.1": "IP", "semponto": "sem ponto", "x.ebd.test": "sob o domínio base",
                    "ebd.test": "domínio base", "igreja1.test": "já em uso", "WWW.igreja1.test": "já em uso (www)"}.items():
    rc, _, err = cli("criar", "--nome", "Teste", "--dominio", dom)
    check(f"domínio próprio recusado ({motivo}): {dom}", rc == 2)
rc, _, err = cli("criar", "--nome", "Teste")
check("criar sem subdomínio nem domínio é recusado", rc == 2)
rc, _, err = cli("criar", "--nome", "Teste", "--subdominio", "ok", "--admin-usuario", "A B")
check("usuário do admin inválido é recusado", rc == 2 and contar("igrejas") == 1)
rc, out, _ = cli("verificar", "--subdominio", "batista")
check("verificar: subdomínio livre e válido", rc == 0 and "livre" in out)

# ── criar ──
rc, out, err = cli("criar", "--nome", "Igreja Batista", "--subdominio", "batista", "--admin-nome", "Pastor Batista")
m = re.search(r"SENHA TEMPORÁRIA: (\S+)", out)
senha = m.group(1) if m else ""
check("criar: igreja, configuração e admin criados (exit 0, senha exibida)", rc == 0 and len(senha) >= 12 and "id 2" in out)
check("criar: avisa do DNS curinga", "*.ebd.test" in out)
rc, _, err = cli("criar", "--nome", "Outra", "--subdominio", "batista")
check("subdomínio duplicado é recusado", rc == 2 and "já em uso" in err)
rc, _, err = cli("verificar", "--subdominio", "batista")
check("verificar: subdomínio ocupado é recusado", rc == 2)
rc, _, err = cli("criar", "--nome", "Outra", "--subdominio", "OUTRA", "--dominio", "igreja1.test")
check("falha na validação não deixa linha pendurada (tudo ou nada)", rc == 2 and contar("igrejas") == 2 and contar("configuracao_igreja") >= 1)
tenant.limpar_cache()

H1, H2 = "igreja1.test", "batista.ebd.test"
with cliente(H2) as c2, cliente(H1) as c1, cliente(H2) as c2_ruim, cliente(H1) as c1_cruzado:
    r = c2.post("/api/auth/login", json={"username": "admin", "senha": senha})
    check("login na igreja nova pelo Host, com a senha temporária", r.status_code == 200)
    check("o login avisa que a troca de senha é obrigatória", r.json().get("trocar_senha") is True)
    check("senha temporária pendente: a API devolve 403 com o aviso",
          (lambda x: x.status_code == 403 and x.json()["detail"] == "Troca de senha obrigatória")(c2.get("/api/alunos/")))
    check("senha temporária pendente: /me continua acessível e traz trocar_senha",
          c2.get("/api/auth/me").json().get("trocar_senha") is True)
    check("troca: senha atual errada é recusada",
          c2.post("/api/auth/trocar-senha", json={"senha_atual": "errada", "senha_nova": "NovaSenha-123"}).status_code == 400)
    check("troca: nova senha curta é recusada",
          c2.post("/api/auth/trocar-senha", json={"senha_atual": senha, "senha_nova": "curta"}).status_code == 422)
    check("troca: nova senha igual à atual é recusada",
          c2.post("/api/auth/trocar-senha", json={"senha_atual": senha, "senha_nova": senha}).status_code == 400)
    check("troca de senha feita com sucesso",
          c2.post("/api/auth/trocar-senha", json={"senha_atual": senha, "senha_nova": "NovaSenha-123"}).status_code == 200)
    check("depois da troca a API libera e o flag some",
          c2.get("/api/alunos/").status_code == 200 and c2.get("/api/auth/me").json()["trocar_senha"] is False)
    check("a senha temporária não vale mais; a nova vale",
          cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": senha}).status_code == 401
          and cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": "NovaSenha-123"}).status_code == 200)
    check("senha errada é recusada", c2_ruim.post("/api/auth/login", json={"username": "admin", "senha": senha + "x"}).status_code == 401)
    check("o admin novo NÃO entra no domínio da outra igreja",
          c1_cruzado.post("/api/auth/login", json={"username": "admin", "senha": senha}).status_code == 401)
    check("o admin da outra igreja NÃO entra na nova",
          cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN}).status_code == 401)
    r1 = c1.post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN})
    check("a igreja 1 segue entrando normalmente", r1.status_code == 200)
    me = c2.get("/api/auth/me").json()
    check("o admin novo é admin, com o nome informado", me.get("role") == "admin" and me.get("nome") == "Pastor Batista")
    check("a configuração inicial leva o nome da igreja", c2.get("/api/config").json()["nome_igreja"] == "Igreja Batista")

    # ── isolamento: dados de uma não aparecem na outra ──
    check("igreja 1 cadastra um aluno", c1.post("/api/alunos/", json={"nome": "Aluno da Um"}).status_code == 201)
    check("igreja nova cadastra outro aluno", c2.post("/api/alunos/", json={"nome": "Aluno da Batista"}).status_code == 201)
    nomes1 = {a["nome"] for a in c1.get("/api/alunos/").json()}
    nomes2 = {a["nome"] for a in c2.get("/api/alunos/").json()}
    check("cada igreja vê só os próprios alunos", nomes1 == {"Aluno da Um"} and nomes2 == {"Aluno da Batista"})
    check("usuários também: a nova só vê o próprio admin", len(c2.get("/api/usuarios/").json()) == 1)
    check("o token da igreja nova não vale no domínio da outra",
          cliente(H1).get("/api/auth/me", headers={"Authorization": f"Bearer {c2.cookies.get('ebd_session')}"}).status_code == 401)

    # ── listar ──
    rc, out, _ = cli("listar", "--json")
    lista = {i["id"]: i for i in json.loads(out)}
    check("listar: 2 igrejas, status ativo e contagens por igreja",
          rc == 0 and len(lista) == 2 and lista[2]["status"] == "ativa" and lista[2]["alunos"] == 1 and lista[1]["alunos"] == 1
          and lista[2]["usuarios"] == 1 and lista[2]["enderecos"] == ["batista.ebd.test"])
    rc, out, _ = cli("listar")
    check("listar em texto mostra nome e endereço", rc == 0 and "Igreja Batista" in out and "batista.ebd.test" in out)

    # ── suspender ──
    rc, _, err = cli("suspender", "batista")
    check("suspender sem --sim e sem terminal é recusado", rc == 2 and contar("igrejas") == 2 and "--sim" in err)
    rc, out, _ = cli("suspender", "batista", "--sim")
    check("suspender (por subdomínio) funciona", rc == 0 and "suspensa" in out)
    tenant.limpar_cache()
    check("igreja suspensa: 403 em qualquer página", cliente(H2).get("/login.html").status_code == 403)
    check("igreja suspensa: 403 mesmo com sessão ativa", c2.get("/api/alunos/").status_code == 403)
    check("igreja suspensa: login recusado (403)",
          cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": senha}).status_code == 403)
    check("igreja suspensa: sem certificado HTTPS novo (Caddy)",
          cliente("x.test").get("/interno/dominio-permitido", params={"domain": H2}).status_code == 404)
    check("a outra igreja não foi afetada", c1.get("/api/alunos/").status_code == 200)
    rc, out, _ = cli("suspender", "2", "--sim")
    check("suspender de novo é inofensivo", rc == 0 and "já está suspensa" in out)
    rc, out, _ = cli("listar", "--json")
    check("listar mostra a igreja como suspensa", {i["id"]: i["status"] for i in json.loads(out)}[2] == "suspensa")

    # ── reativar ──
    rc, out, _ = cli("reativar", "2")
    check("reativar (por id) funciona", rc == 0 and "reativada" in out)
    tenant.limpar_cache()
    check("reativada: o admin volta a entrar com a mesma senha e os dados estão lá",
          cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": "NovaSenha-123"}).status_code == 200
          and {a["nome"] for a in c2.get("/api/alunos/").json()} == {"Aluno da Batista"})
    check("reativada: certificado volta a ser permitido",
          cliente("x.test").get("/interno/dominio-permitido", params={"domain": H2}).status_code == 200)

    # ── redefinir senha pela CLI ──
    rc, out, _ = cli("senha", "batista", "--usuario", "admin")
    m = re.search(r"SENHA TEMPORÁRIA: (\S+)", out)
    senha2 = m.group(1) if m else ""
    check("senha: redefine e mostra uma nova senha temporária", rc == 0 and len(senha2) >= 12 and senha2 != senha)
    check("senha: a sessão aberta passa a ser barrada (403) até trocar",
          c2.get("/api/alunos/").status_code == 403)
    check("senha: a senha anterior deixa de valer",
          cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": "NovaSenha-123"}).status_code == 401)
    r = cliente(H2).post("/api/auth/login", json={"username": "admin", "senha": senha2})
    check("senha: a temporária vale e exige a troca", r.status_code == 200 and r.json()["trocar_senha"] is True)
    check("senha: a igreja 1 não foi afetada (admin com a mesma senha de antes)",
          cliente(H1).post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN}).json()["trocar_senha"] is False)
    rc, _, err = cli("senha", "batista", "--usuario", "fantasma")
    check("senha: usuário inexistente é recusado", rc == 2 and "não existe" in err)
    rc, _, err = cli("senha", "naoexiste")
    check("senha: igreja inexistente é recusada", rc == 2 and "não encontrada" in err)

rc, _, err = cli("suspender", "naoexiste", "--sim")
check("suspender igreja inexistente é recusado", rc == 2 and "não encontrada" in err)

# ── igreja só com domínio próprio, e conferência de que o banco recusa quem não é dono ──
rc, out, _ = cli("criar", "--nome", "Igreja Dominio", "--dominio", "www.Igrejadominio.test", "--admin-usuario", "pastor")
check("criar só com domínio próprio (normaliza www. e maiúsculas)", rc == 0 and "igrejadominio.test" in out and "id 3" in out)
env_app = {**os.environ, "MIGRATION_DATABASE_URL": _banco.url_app(), "PYTHONIOENCODING": "utf-8"}
r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "igrejas.py"), "listar"], cwd=RAIZ, env=env_app,
                   capture_output=True, text=True, encoding="utf-8")
check("conectado como o papel do app (sem poder de dono), a ferramenta recusa", r.returncode == 2 and "dono" in r.stderr)

# ── auditoria ──
linhas = [json.loads(l) for l in AUDITORIA.read_text(encoding="utf-8").splitlines()]
acoes = [(l["acao"], l["resultado"]) for l in linhas]
check("auditoria: criar, senha, suspender, reativar e recusas registrados",
      ("criar", "ok") in acoes and ("senha", "ok") in acoes and ("suspender", "ok") in acoes and ("reativar", "ok") in acoes and ("criar", "recusado") in acoes)
check("auditoria: cada linha tem quando, quem e ação", all(l.get("quando") and l.get("quem") and l.get("acao") for l in linhas))
check("auditoria: a senha temporária nunca aparece", senha not in AUDITORIA.read_text(encoding="utf-8"))

DB.unlink(missing_ok=True)
print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\nFALHARAM {len(falhas)}: {falhas}")
sys.exit(1 if falhas else 0)
