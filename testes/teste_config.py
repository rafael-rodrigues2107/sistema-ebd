"""Teste local das Configurações da Igreja — banco e uploads temporários."""
import io, os, secrets, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _banco

DB = Path(__file__).parent / f"teste_config_{secrets.token_hex(3)}.db"
UPLOADS = tempfile.mkdtemp(prefix="ebd_uploads_")
PASTA = Path(UPLOADS) / "1"  # desde a fase 4 os arquivos ficam em uploads/<igreja_id>/ (aqui: igreja 1)
os.environ.update(DATABASE_URL=_banco.url(DB), ADMIN_INITIAL_PASSWORD=_banco.SENHA_ADMIN, DEBUG="false",
                  SECRET_KEY=secrets.token_hex(16), UPLOADS_DIR=UPLOADS)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.chdir(str(Path(__file__).resolve().parent.parent / "app"))

from fastapi.testclient import TestClient
from PIL import Image
from main import app

falhas = []
def check(desc, cond, extra=""):
    if not cond: falhas.append(desc)
    print(f"{'OK ' if cond else 'ERRO'}  {desc} {extra}")

def imagem(formato, tamanho=(400, 400), cor=(200, 30, 30, 255), transparente=False):
    img = Image.new("RGBA", tamanho, (0, 0, 0, 0) if transparente else cor)
    if transparente:  # círculo opaco no meio, bordas transparentes
        for x in range(100, 300):
            for y in range(100, 300):
                img.putpixel((x, y), cor)
    if formato == "JPEG": img = img.convert("RGB")
    buf = io.BytesIO(); img.save(buf, format=formato)
    return buf.getvalue()

def envia(c, dados, nome="logo.png", tipo="image/png"):
    return c.post("/api/config/logo", files={"arquivo": (nome, dados, tipo)})

try:
    with TestClient(app) as adm, TestClient(app) as prof, TestClient(app) as anon:
        adm.post("/api/auth/login", json={"username": "admin", "senha": "admin123"})
        turma = adm.post("/api/turmas/", json={"nome": "Primários", "faixa_etaria": "6-8"}).json()["id"]
        senha = secrets.token_urlsafe(10)
        adm.post("/api/usuarios/", json={"nome": "Prof", "username": "prof", "senha": senha, "role": "professor", "turma_id": turma})
        prof.post("/api/auth/login", json={"username": "prof", "senha": senha})

        print("== Padrão (sem configuração)")
        r = anon.get("/api/config")
        check("GET /api/config é público: 200", r.status_code == 200, str(r.status_code))
        c = r.json()
        check("valores padrão", (c["nome_igreja"], c["nome_app"], c["cor_primaria"], c["logo_url"]) ==
              ("Sistema EBD", "EBD", "#4f46e5", None), str(c))
        m = anon.get("/manifest.json")
        check("manifest público: 200", m.status_code == 200 and "manifest+json" in m.headers["content-type"])
        check("manifest padrão", m.json()["short_name"] == "EBD" and m.json()["theme_color"] == "#4f46e5")
        for arq in ("icon-192.png", "icon-512.png", "maskable-192.png", "maskable-512.png", "apple-touch-icon.png"):
            r = anon.get(f"/marca/{arq}")
            check(f"fallback /marca/{arq}: PNG", r.status_code == 200 and r.content[:4] == b"\x89PNG")
        check("/marca/logo.png sem logo: 404", anon.get("/marca/logo.png").status_code == 404)
        check("/marca/arquivo-qualquer: 404", anon.get("/marca/segredo.txt").status_code == 404)
        check("/marca/../ não escapa: 404", anon.get("/marca/..%2F..%2Fconfig.py").status_code == 404)
        check("/api/seed não existe mais", anon.post("/api/seed").status_code in (404, 405))
        check("/docs fechado em produção", anon.get("/docs").status_code == 404)

        print("== Permissões")
        corpo = {"nome_igreja": "Igreja Batista Central", "nome_app": "EBD Central", "cor_primaria": "#0f766e"}
        check("sem login PUT: 401", anon.put("/api/config", json=corpo).status_code == 401)
        check("professor PUT: 403", prof.put("/api/config", json=corpo).status_code == 403)
        check("sem login logo: 401", envia(anon, imagem("PNG")).status_code == 401)
        check("professor logo: 403", envia(prof, imagem("PNG")).status_code == 403)
        check("sem login DELETE logo: 401", anon.delete("/api/config/logo").status_code == 401)
        check("professor DELETE logo: 403", prof.delete("/api/config/logo").status_code == 403)

        print("== Salvar nome e cor")
        r = adm.put("/api/config", json=corpo)
        check("admin salva: 200", r.status_code == 200, r.text)
        c = anon.get("/api/config").json()
        check("config pública reflete", (c["nome_igreja"], c["nome_app"], c["cor_primaria"]) == ("Igreja Batista Central", "EBD Central", "#0f766e"))
        m = anon.get("/manifest.json").json()
        check("manifest com nome e cor", (m["name"], m["short_name"], m["theme_color"]) == ("Igreja Batista Central", "EBD Central", "#0f766e"), str(m))
        check("cor maiúscula é normalizada", adm.put("/api/config", json={**corpo, "cor_primaria": "#0F766E"}).json()["cor_primaria"] == "#0f766e")
        check("cor clara recusada", adm.put("/api/config", json={**corpo, "cor_primaria": "#ffff00"}).status_code == 422)
        check("branco recusado", adm.put("/api/config", json={**corpo, "cor_primaria": "#ffffff"}).status_code == 422)
        check("cor inválida recusada", adm.put("/api/config", json={**corpo, "cor_primaria": "vermelho"}).status_code == 422)
        check("cor sem # recusada", adm.put("/api/config", json={**corpo, "cor_primaria": "0f766e"}).status_code == 422)
        check("nome do app > 15: recusado", adm.put("/api/config", json={**corpo, "nome_app": "x" * 16}).status_code == 422)
        check("nome vazio recusado", adm.put("/api/config", json={**corpo, "nome_igreja": "   "}).status_code == 422)
        check("recusas não alteraram a config", anon.get("/api/config").json()["cor_primaria"] == "#0f766e")

        print("== Upload do logo")
        for fmt, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
            r = envia(adm, imagem(fmt), f"logo.{fmt.lower()}", mime)
            check(f"upload {fmt}: 200", r.status_code == 200, r.text[:120])
        c = anon.get("/api/config").json()
        check("logo_url preenchida", c["logo_url"] and c["logo_url"].startswith("/marca/logo.png?v="), str(c))
        tamanhos = {"icon-192.png": 192, "icon-512.png": 512, "maskable-192.png": 192, "maskable-512.png": 512, "apple-touch-icon.png": 180}
        for arq, lado in tamanhos.items():
            r = anon.get(f"/marca/{arq}")
            im = Image.open(io.BytesIO(r.content))
            check(f"{arq} gerado {lado}x{lado}", r.status_code == 200 and im.size == (lado, lado), str(im.size))
        check("apple-touch-icon sem transparência", Image.open(io.BytesIO(anon.get("/marca/apple-touch-icon.png").content)).mode == "RGB")
        check("logo.png servido", anon.get("/marca/logo.png").status_code == 200)
        check("arquivos gravados no volume", {p.name for p in PASTA.glob("*.png")} >= set(tamanhos) | {"logo.png"})
        check("manifest versionado pelo logo", f"v={c['versao']}" in anon.get("/manifest.json").json()["icons"][0]["src"])

        print("== Logo transparente e logo claro")
        envia(adm, imagem("PNG", (500, 300), transparente=True))
        im = Image.open(io.BytesIO(anon.get("/marca/maskable-512.png").content)).convert("RGB")
        check("logo escuro: fundo do maskable branco", im.getpixel((2, 2)) == (255, 255, 255), str(im.getpixel((2, 2))))
        im_any = Image.open(io.BytesIO(anon.get("/marca/icon-512.png").content))
        check("icon 'any' mantém transparência", im_any.getpixel((1, 1))[3] == 0)
        envia(adm, imagem("PNG", (400, 400), cor=(250, 250, 250, 255), transparente=True))
        im = Image.open(io.BytesIO(anon.get("/marca/maskable-512.png").content)).convert("RGB")
        check("logo claro: fundo vira a cor principal", im.getpixel((2, 2)) == (0x0f, 0x76, 0x6e), str(im.getpixel((2, 2))))
        im = Image.open(io.BytesIO(envia(adm, imagem("PNG", (300, 600), cor=(10, 10, 200, 255))) and anon.get("/marca/icon-512.png").content))
        check("logo retangular cabe inteiro no ícone", im.size == (512, 512) and im.getpixel((256, 256))[3] == 255)

        print("== Uploads inválidos")
        n = len(list(PASTA.iterdir())); v = anon.get("/api/config").json()["versao"]
        r = envia(adm, b"isto nao e uma imagem", "logo.png")
        check("texto com extensão .png: 400", r.status_code == 400, r.text[:100])
        r = envia(adm, b"%PDF-1.4 fake", "logo.pdf", "application/pdf")
        check("PDF: 400", r.status_code == 400)
        r = envia(adm, imagem("GIF" if False else "BMP"), "logo.bmp", "image/bmp")
        check("formato não aceito (BMP): 400", r.status_code == 400, r.text[:100])
        r = envia(adm, imagem("PNG", (30, 30)), "p.png")
        check("imagem pequena demais: 400", r.status_code == 400, r.text[:100])
        r = envia(adm, b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 10))
        check("arquivo > 5 MB: 413", r.status_code == 413, str(r.status_code))
        r = adm.post("/api/config/logo")
        check("sem arquivo: 422", r.status_code == 422)
        check("rejeições não mexeram nos arquivos nem na versão", len(list(PASTA.iterdir())) == n and anon.get("/api/config").json()["versao"] == v)

        print("== Remover logo")
        r = adm.delete("/api/config/logo")
        check("remover: 200 e sem logo_url", r.status_code == 200 and r.json()["logo_url"] is None, r.text)
        check("arquivos apagados do volume", not list(PASTA.glob("*.png")))
        check("logo.png volta a 404", anon.get("/marca/logo.png").status_code == 404)
        r = anon.get("/marca/icon-192.png")
        check("ícone volta ao padrão", r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (192, 192))
        check("remover de novo é inofensivo", adm.delete("/api/config/logo").status_code == 200)
        check("nome e cor continuam", anon.get("/api/config").json()["nome_igreja"] == "Igreja Batista Central")
finally:
    import shutil; shutil.rmtree(UPLOADS, ignore_errors=True)
    for f in Path(__file__).parent.glob("teste_config_*.db*"):
        try: f.unlink()
        except OSError: pass

print(f"\n{len(falhas)} falha(s)" if falhas else "\nTudo certo")
sys.exit(1 if falhas else 0)
