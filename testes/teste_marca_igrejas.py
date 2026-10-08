"""Fase 4: marca (logo, cor, nome, manifest, ícones) e uploads separados por igreja, e JWT com a igreja.

Só roda em Postgres (TEST_DATABASE_URL): o SQLite não tem RLS, então não isola igrejas.
Duas igrejas em domínios diferentes.
"""
import io, os, secrets, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

if not _banco.PG:
    print("PULADO: defina TEST_DATABASE_URL=postgresql+asyncpg://... (SQLite não isola igrejas)")
    sys.exit(0)

DB = Path(__file__).parent / f"teste_marca_{secrets.token_hex(3)}.db"
UPLOADS = Path(tempfile.mkdtemp(prefix="ebd_uploads_fase4_"))
os.environ.update(DATABASE_URL=_banco.url(DB), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DEBUG="false",
                  SECRET_KEY=secrets.token_hex(16), UPLOADS_DIR=str(UPLOADS))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.chdir(str(Path(__file__).resolve().parent.parent / "app"))

import bcrypt
from fastapi.testclient import TestClient
from PIL import Image

import armazenamento
import tenant
from main import app
from routers.auth import criar_token

falhas = []


def check(desc, ok):
    print(f"{'OK  ' if ok else 'ERRO'} {desc}")
    if not ok:
        falhas.append(desc)


def png(cor):
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), cor).save(buf, format="PNG")
    return buf.getvalue()


def pixel_central(resp):
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    return img.getpixel((img.width // 2, img.height // 2))


def perto(px, cor, tol=12):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], cor))


def cliente(host):
    return TestClient(app, base_url=f"http://{host}", raise_server_exceptions=False)


VERMELHO, AZUL = (220, 30, 30), (30, 60, 220)
senha2 = "senha-igreja-b-" + secrets.token_hex(4)

# ── arquivos legados (antes da fase 4) vão para a pasta da igreja original ──
(UPLOADS / "logo.png").write_bytes(b"legado")
(UPLOADS / "icon-192.png").write_bytes(b"legado")
check("migração de arquivos soltos: 2 arquivos movidos", armazenamento.migrar_arquivos_legados() == 2)
check("os arquivos legados foram para a pasta da igreja 1 e a raiz ficou limpa",
      (UPLOADS / "1" / "logo.png").exists() and not (UPLOADS / "logo.png").exists())
check("rodar de novo não faz nada (idempotente)", armazenamento.migrar_arquivos_legados() == 0)
(UPLOADS / "1" / "logo.png").unlink(); (UPLOADS / "1" / "icon-192.png").unlink()

with TestClient(app):  # sobe o app uma vez (cria as tabelas em SQLite) para poder preparar as igrejas
    pass
_banco.sql(DB, "update igrejas set dominio_proprio=? where id=1", ("igreja1.test",))
_banco.sql(DB, "insert into igrejas (id, nome, dominio_proprio, ativa, created_at) values (?,?,?,?,?)", (2, "Igreja B", "igrejab.test", True, datetime(2026, 10, 8)))
hash2 = bcrypt.hashpw(senha2.encode(), bcrypt.gensalt()).decode()
_banco.sql(DB, "insert into usuarios (nome, username, senha_hash, role, ativo, created_at, igreja_id) values (?,?,?,?,?,?,?)",
           ("Admin B", "admin", hash2, "admin", True, datetime(2026, 10, 8), 2))
tenant.limpar_cache()

with cliente("igreja1.test") as c1, cliente("igrejab.test") as c2, cliente("igrejab.test") as c2_anonimo:
    r1 = c1.post("/api/auth/login", json={"username": "admin", "senha": _banco.SENHA_ADMIN})
    r2 = c2.post("/api/auth/login", json={"username": "admin", "senha": senha2})
    check("as duas igrejas têm um 'admin' e cada um entra na sua", r1.status_code == 200 and r2.status_code == 200)

    # ── cada igreja configura nome, cor e logo ──
    ok = c1.put("/api/config", json={"nome_igreja": "Igreja Alfa", "nome_app": "Alfa", "cor_primaria": "#dc1e1e"}).status_code == 200
    ok &= c2.put("/api/config", json={"nome_igreja": "Igreja Beta", "nome_app": "Beta", "cor_primaria": "#1e3cdc"}).status_code == 200
    check("cada igreja salva a própria configuração (nome, nome curto, cor)", ok)
    ok = c1.post("/api/config/logo", files={"arquivo": ("logo.png", png(VERMELHO), "image/png")}).status_code == 200
    ok &= c2.post("/api/config/logo", files={"arquivo": ("logo.png", png(AZUL), "image/png")}).status_code == 200
    check("cada igreja envia o seu logo", ok)

    # ── a marca é pública e vem do domínio ──
    cfg1, cfg2 = c2_anonimo.get("/api/config").json(), cliente("igreja1.test").get("/api/config").json()
    check("/api/config por domínio, sem login: Beta em igrejab.test, Alfa em igreja1.test",
          cfg1["nome_igreja"] == "Igreja Beta" and cfg2["nome_igreja"] == "Igreja Alfa"
          and cfg1["cor_primaria"] == "#1e3cdc" and cfg2["cor_primaria"] == "#dc1e1e")
    m1, m2 = cliente("igreja1.test").get("/manifest.json").json(), c2_anonimo.get("/manifest.json").json()
    check("manifest do PWA próprio de cada igreja (nome, nome curto e cor do tema)",
          (m1["name"], m1["short_name"], m1["theme_color"]) == ("Igreja Alfa", "Alfa", "#dc1e1e")
          and (m2["name"], m2["short_name"], m2["theme_color"]) == ("Igreja Beta", "Beta", "#1e3cdc"))
    i1, i2 = cliente("igreja1.test").get("/marca/icon-512.png"), c2_anonimo.get("/marca/icon-512.png")
    check("ícone do app: vermelho na Alfa e azul na Beta",
          i1.status_code == 200 and i2.status_code == 200 and perto(pixel_central(i1), VERMELHO) and perto(pixel_central(i2), AZUL))
    check("logo.png também é de cada igreja",
          perto(pixel_central(cliente("igreja1.test").get("/marca/logo.png")), VERMELHO)
          and perto(pixel_central(c2_anonimo.get("/marca/logo.png")), AZUL))

    # ── arquivos em pastas separadas ──
    check("uploads separados: pasta 1 e pasta 2, cada uma com os seus ícones",
          (UPLOADS / "1" / "icon-512.png").is_file() and (UPLOADS / "2" / "icon-512.png").is_file()
          and (UPLOADS / "1" / "icon-512.png").read_bytes() != (UPLOADS / "2" / "icon-512.png").read_bytes()
          and not list(UPLOADS.glob("*.png")))

    # ── apagar o logo de uma igreja não mexe na outra ──
    check("igreja B remove o logo", c2.delete("/api/config/logo").status_code == 200)
    pad = c2_anonimo.get("/marca/icon-512.png")
    padrao = (Path(__file__).resolve().parent.parent / "app" / "static" / "icons" / "icon-512.png").read_bytes()
    check("sem logo, a igreja B volta ao ícone padrão do sistema", pad.status_code == 200 and pad.content == padrao)
    check("o logo da igreja A continua intacto",
          perto(pixel_central(cliente("igreja1.test").get("/marca/icon-512.png")), VERMELHO)
          and (UPLOADS / "1" / "icon-512.png").is_file())

    # ── JWT com a igreja ──
    tok1 = c1.cookies.get("ebd_session")
    check("o login grava o cookie de sessão", bool(tok1))
    with cliente("igrejab.test") as invasor:
        r = invasor.get("/api/auth/me", headers={"Authorization": f"Bearer {tok1}"})
        check("o token da igreja A não autentica no domínio da igreja B", r.status_code == 401)
    me1 = c1.get("/api/auth/me").json()
    forjado = criar_token(me1["id"], "admin", igreja_id=2)
    with cliente("igreja1.test") as c:
        check("token com igreja diferente da do domínio é recusado (mesmo com usuário existente)",
              c.get("/api/auth/me", headers={"Authorization": f"Bearer {forjado}"}).status_code == 401)
        antigo = criar_token(me1["id"], "admin")  # sem claim "ig": emitido antes da fase 4
        check("token antigo (sem igreja) continua valendo até expirar",
              c.get("/api/auth/me", headers={"Authorization": f"Bearer {antigo}"}).status_code == 200)
        certo = criar_token(me1["id"], "admin", igreja_id=1)
        check("token com a igreja certa vale",
              c.get("/api/auth/me", headers={"Authorization": f"Bearer {certo}"}).status_code == 200)

    # ── a igreja A não consegue mexer na marca da B ──
    r = c1.put("/api/config", json={"nome_igreja": "Sequestrada", "nome_app": "X", "cor_primaria": "#000000"})
    check("o admin da A só altera a configuração da A", r.status_code == 200
          and c2_anonimo.get("/api/config").json()["nome_igreja"] == "Igreja Beta")

# ── validação de domínio para o certificado HTTPS (o Caddy pergunta antes de emitir) ──
_banco.sql(DB, "insert into igrejas (id, nome, dominio_proprio, ativa, created_at) values (?,?,?,?,?)",
           (3, "Igreja C", "igrejac.test", False, datetime(2026, 10, 8)))
tenant.limpar_cache()
with cliente("interno.invalido") as ca:  # o Host da requisição não importa: vale o parâmetro `domain`
    def pergunta(dominio):
        return ca.get("/interno/dominio-permitido", params={"domain": dominio}).status_code
    check("certificado: domínio de igreja ativa é permitido (inclusive com www.)",
          pergunta("igreja1.test") == 200 and pergunta("igrejab.test") == 200 and pergunta("www.igrejab.test") == 200)
    check("certificado: domínio desconhecido, vazio ou de igreja suspensa é negado",
          pergunta("desconhecido.test") == 404 and pergunta("") == 404 and pergunta("igrejac.test") == 404)

DB.unlink(missing_ok=True)
print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\nFALHARAM {len(falhas)}: {falhas}")
sys.exit(1 if falhas else 0)
