"""Ferramenta do DONO: criar, listar, suspender e reativar igrejas (fase 5). Só linha de comando.

Roda dentro do container do app (ou a partir de scripts/), conectando como DONO do banco
(MIGRATION_DATABASE_URL, superusuário, que ignora o RLS de propósito). Não existe rota HTTP para isto:
o papel do app (`ebd_app`) nem tem permissão de gravar em `igrejas`.

    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py listar
    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py verificar --subdominio batista
    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py criar --nome "Igreja Batista" --subdominio batista
    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py suspender batista
    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py reativar batista
    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py senha batista --usuario admin
    docker exec -it sistema-ebd-app-1 python /app/scripts/igrejas.py editar batista --nome "Novo nome" --subdominio novo

`criar` gera um admin com SENHA TEMPORÁRIA ALEATÓRIA, mostrada uma única vez (nunca vai para o log).
Cada ação (inclusive recusas) é registrada em AUDITORIA_DONO_LOG, uma linha JSON por ação.
"""
import argparse
import asyncio
import getpass
import ipaddress
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from config import settings  # noqa: E402
from routers.auth import hash_senha  # noqa: E402  (mesmo bcrypt do login)

# Nomes que nunca podem ser subdomínio de igreja: infraestrutura, e-mail, rotas do próprio sistema
RESERVADOS = {
    "www", "api", "admin", "administrador", "dp", "app", "apps", "mail", "email", "smtp", "imap", "pop", "ftp",
    "ns", "ns1", "ns2", "dns", "painel", "dono", "root", "interno", "static", "assets", "cdn", "caddy", "nginx",
    "db", "postgres", "suporte", "support", "status", "login", "healthz", "docs", "blog", "ebd", "minhaebd",
    "n8n", "baserow", "ollama", "openclaw", "localhost", "teste", "test", "demo",
}
RE_SUBDOMINIO = re.compile(r"^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])$")  # 3 a 63 caracteres
RE_DOMINIO = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
RE_USUARIO = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,99}$")


class Recusa(Exception):
    """Pedido inválido ou impossível: vai para a auditoria e para a tela, sem traceback."""


# ── Validação (funções puras, usadas também pelos testes) ────────────────────

def validar_subdominio(valor: str) -> str:
    if valor != valor.strip().lower():
        raise Recusa("subdomínio só aceita letras minúsculas, sem espaços")
    if not RE_SUBDOMINIO.match(valor):
        raise Recusa("subdomínio inválido: use 3 a 63 caracteres, só a-z, 0-9 e hífen (sem começar nem terminar com hífen)")
    if valor.startswith("xn--") or "--" in valor:
        raise Recusa("subdomínio inválido: não use hífen duplo")
    if valor in RESERVADOS:
        raise Recusa(f"subdomínio reservado: '{valor}'")
    return valor


def validar_dominio(valor: str) -> str:
    d = valor.strip().lower().rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    try:
        ipaddress.ip_address(d)
        raise Recusa("domínio próprio não pode ser um endereço IP")
    except ValueError:
        pass
    if not RE_DOMINIO.match(d) or "--" in d.replace("xn--", ""):
        raise Recusa(f"domínio próprio inválido: '{valor}'")
    base = settings.dominio_base.strip().lower()
    if base and (d == base or d.endswith("." + base)):
        # só a igreja 1 (minhaebd.cloud) é dona do domínio base; as outras usam subdomínio
        raise Recusa(f"'{d}' está sob o domínio base {base}: use --subdominio em vez de domínio próprio")
    return d


def validar_usuario(valor: str) -> str:
    if not RE_USUARIO.match(valor):
        raise Recusa("usuário do admin inválido: 3 a 100 caracteres minúsculos (a-z, 0-9, . _ - @)")
    return valor


# ── Auditoria ────────────────────────────────────────────────────────────────

def arquivo_auditoria() -> Path:
    caminho = os.environ.get("AUDITORIA_DONO_LOG") or settings.auditoria_dono_log
    return Path(caminho) if caminho else Path(settings.uploads_dir).parent / "auditoria_dono.log"


def _quem() -> str:
    try:
        return getpass.getuser()
    except Exception:  # container sem entrada no passwd
        return "?"


def auditar(acao: str, resultado: str, **detalhes) -> None:
    """Uma linha JSON por ação. NUNCA recebe senha."""
    linha = {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quem": _quem(),
        "acao": acao, "resultado": resultado, **detalhes,
    }
    try:
        caminho = arquivo_auditoria()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError as e:  # não derruba a ação, mas avisa
        print(f"AVISO: não consegui gravar a auditoria ({e})", file=sys.stderr)


# ── Banco (como DONO) ────────────────────────────────────────────────────────

def criar_engine():
    url = settings.migration_database_url or settings.database_url
    if "postgresql" not in url:
        raise Recusa("esta ferramenta só funciona com PostgreSQL (SQLite não isola igrejas)")
    return create_async_engine(url, poolclass=NullPool)


async def exigir_dono(conn) -> None:
    """Recusa rodar com um papel que o RLS barra: contagens viriam zeradas e gravações falhariam."""
    r = (await conn.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"))).scalar()
    if not r:
        raise Recusa("conexão sem poder de dono (o RLS valeria). Defina MIGRATION_DATABASE_URL com o usuário dono do banco.")


async def achar_igreja(conn, ref: str):
    """Aceita id, subdomínio ou domínio próprio."""
    ref = ref.strip().lower()
    if ref.isdigit():
        linha = (await conn.execute(text("SELECT * FROM igrejas WHERE id = :i"), {"i": int(ref)})).mappings().first()
    else:
        d = ref[4:] if ref.startswith("www.") else ref
        linha = (await conn.execute(
            text("SELECT * FROM igrejas WHERE lower(subdominio) = :r OR lower(dominio_proprio) = :r"), {"r": d}
        )).mappings().first()
    if not linha:
        raise Recusa(f"igreja não encontrada: '{ref}'")
    return linha


async def checar_livre(conn, subdominio: str | None, dominio: str | None, ignorar_id: int = 0) -> None:
    """Endereço livre para uso. `ignorar_id`: a própria igreja, ao editar."""
    base = settings.dominio_base.strip().lower()
    if subdominio:
        if (await conn.scalar(text("SELECT count(*) FROM igrejas WHERE lower(subdominio) = :s AND id <> :i"),
                              {"s": subdominio, "i": ignorar_id})):
            raise Recusa(f"subdomínio já em uso: '{subdominio}'")
        if base and (await conn.scalar(text("SELECT count(*) FROM igrejas WHERE lower(dominio_proprio) = :h AND id <> :i"),
                                       {"h": f"{subdominio}.{base}", "i": ignorar_id})):
            raise Recusa(f"'{subdominio}.{base}' já é domínio próprio de outra igreja")
    if dominio:
        if (await conn.scalar(text("SELECT count(*) FROM igrejas WHERE lower(dominio_proprio) = :d AND id <> :i"),
                              {"d": dominio, "i": ignorar_id})):
            raise Recusa(f"domínio já em uso: '{dominio}'")
        if base and dominio.endswith("." + base) and (await conn.scalar(
                text("SELECT count(*) FROM igrejas WHERE lower(subdominio) = :s AND id <> :i"),
                {"s": dominio[: -len(base) - 1], "i": ignorar_id})):
            raise Recusa(f"'{dominio}' colide com o subdomínio de outra igreja")


# ── Comandos ─────────────────────────────────────────────────────────────────

async def cmd_verificar(args) -> int:
    if not args.subdominio and not args.dominio:
        raise Recusa("informe --subdominio e/ou --dominio")
    sub = validar_subdominio(args.subdominio) if args.subdominio else None
    dom = validar_dominio(args.dominio) if args.dominio else None
    engine = criar_engine()
    try:
        async with engine.connect() as conn:
            await exigir_dono(conn)
            await checar_livre(conn, sub, dom)
    finally:
        await engine.dispose()
    base = settings.dominio_base.strip()
    print("livre e válido:", ", ".join(x for x in (f"{sub}.{base}" if sub and base else sub, dom) if x))
    return 0


async def cmd_criar(args) -> int:
    nome = args.nome.strip()
    if not 2 <= len(nome) <= 120:
        raise Recusa("nome da igreja deve ter de 2 a 120 caracteres")
    if not args.subdominio and not args.dominio:
        raise Recusa("informe --subdominio e/ou --dominio (a igreja precisa de um endereço)")
    sub = validar_subdominio(args.subdominio) if args.subdominio else None
    dom = validar_dominio(args.dominio) if args.dominio else None
    if sub and not settings.dominio_base.strip():
        raise Recusa("DOMINIO_BASE não está definido: subdomínios não funcionariam. Use --dominio ou defina DOMINIO_BASE.")
    usuario = validar_usuario(args.admin_usuario)
    nome_admin = (args.admin_nome or "Administrador").strip()[:200]
    senha = secrets.token_urlsafe(12)

    engine = criar_engine()
    try:
        async with engine.begin() as conn:  # tudo ou nada
            await exigir_dono(conn)
            await checar_livre(conn, sub, dom)
            igreja_id = (await conn.execute(
                text("INSERT INTO igrejas (nome, subdominio, dominio_proprio, ativa, created_at) "
                     "VALUES (:n, :s, :d, true, now()) RETURNING id"),
                {"n": nome, "s": sub, "d": dom})).scalar_one()
            await conn.execute(
                text("INSERT INTO configuracao_igreja (nome_igreja, updated_at, igreja_id) VALUES (:n, now(), :i)"),
                {"n": nome, "i": igreja_id})
            await conn.execute(
                text("INSERT INTO usuarios (nome, username, senha_hash, role, ativo, trocar_senha, created_at, igreja_id) "
                     "VALUES (:nome, :u, :h, 'admin', true, true, now(), :i)"),
                {"nome": nome_admin, "u": usuario, "h": hash_senha(senha), "i": igreja_id})
    finally:
        await engine.dispose()

    base = settings.dominio_base.strip()
    enderecos = ([f"{sub}.{base}"] if sub else []) + ([dom] if dom else [])
    auditar("criar", "ok", igreja_id=igreja_id, nome=nome, subdominio=sub, dominio_proprio=dom, admin=usuario)
    print(f"Igreja criada: id {igreja_id} — {nome}")
    for e in enderecos:
        print(f"  endereço: https://{e}")
    print(f"  admin: {usuario}")
    print(f"  SENHA TEMPORÁRIA: {senha}")
    print("  (mostrada só agora, não fica gravada em lugar nenhum; o sistema exige a troca no primeiro acesso)")
    if sub:
        print(f"  DNS: precisa existir o registro curinga *.{base} (ou um A para {sub}.{base}) apontando para a VPS.")
    if dom:
        print(f"  DNS: o cliente precisa apontar {dom} (A) para o IP da VPS; o certificado sai na primeira visita.")
    return 0


async def cmd_listar(args) -> int:
    consulta = """
        SELECT i.id, i.nome, i.subdominio, i.dominio_proprio, i.ativa, i.created_at,
               (SELECT count(*) FROM alunos a WHERE a.igreja_id = i.id AND a.ativo) AS alunos,
               (SELECT count(*) FROM turmas t WHERE t.igreja_id = i.id AND t.ativo) AS turmas,
               (SELECT count(*) FROM usuarios u WHERE u.igreja_id = i.id AND u.ativo) AS usuarios
          FROM igrejas i ORDER BY i.id"""
    engine = criar_engine()
    try:
        async with engine.connect() as conn:
            await exigir_dono(conn)
            linhas = [dict(r) for r in (await conn.execute(text(consulta))).mappings()]
    finally:
        await engine.dispose()
    base = settings.dominio_base.strip()
    for r in linhas:
        r["enderecos"] = ([f"{r['subdominio']}.{base}"] if r["subdominio"] and base else []) + \
                         ([r["dominio_proprio"]] if r["dominio_proprio"] else [])
        r["status"] = "ativa" if r["ativa"] else "suspensa"
    if args.json:
        print(json.dumps(linhas, ensure_ascii=False, default=str))
        return 0
    print(f"{'ID':>3}  {'STATUS':<9} {'ALUNOS':>6} {'TURMAS':>6} {'USUÁR.':>6}  NOME / ENDEREÇO")
    for r in linhas:
        print(f"{r['id']:>3}  {r['status']:<9} {r['alunos']:>6} {r['turmas']:>6} {r['usuarios']:>6}  "
              f"{r['nome']} — {', '.join(r['enderecos']) or '(sem endereço)'}")
    print(f"{len(linhas)} igreja(s); {sum(1 for r in linhas if r['ativa'])} ativa(s).")
    return 0


async def _mudar_status(args, ativa: bool) -> int:
    acao = "reativar" if ativa else "suspender"
    engine = criar_engine()
    try:
        async with engine.begin() as conn:
            await exigir_dono(conn)
            ig = await achar_igreja(conn, args.igreja)
            if ig["ativa"] == ativa:
                print(f"'{ig['nome']}' (id {ig['id']}) já está {'ativa' if ativa else 'suspensa'}; nada a fazer.")
                return 0
            if not ativa and not args.sim:
                restantes = await conn.scalar(text("SELECT count(*) FROM igrejas WHERE ativa AND id <> :i"), {"i": ig["id"]})
                aviso = " Ela é a ÚNICA igreja ativa: o sistema inteiro ficará fora do ar." if not restantes else ""
                if not sys.stdin.isatty():
                    raise Recusa(f"suspender exige confirmação: rode com --sim.{aviso}")
                try:
                    resposta = input(f"Suspender '{ig['nome']}' (id {ig['id']})?{aviso} Digite 'sim': ")
                except EOFError:
                    resposta = ""
                if resposta.strip().lower() != "sim":
                    raise Recusa("cancelado")
            await conn.execute(text("UPDATE igrejas SET ativa = :a WHERE id = :i"), {"a": ativa, "i": ig["id"]})
    finally:
        await engine.dispose()
    auditar(acao, "ok", igreja_id=ig["id"], nome=ig["nome"])
    print(f"'{ig['nome']}' (id {ig['id']}) {'reativada' if ativa else 'suspensa'}.")
    print("  O app guarda a resposta por até 30 segundos; depois disso o efeito é total "
          + ("(acesso volta e o certificado pode ser emitido)." if ativa else "(403 para todos e nenhum certificado novo)."))
    return 0


async def cmd_senha(args) -> int:
    """Redefine a senha de um usuário da igreja: nova senha temporária, troca obrigatória no próximo login."""
    usuario = args.usuario.strip().lower()
    senha = secrets.token_urlsafe(12)
    engine = criar_engine()
    try:
        async with engine.begin() as conn:
            await exigir_dono(conn)
            ig = await achar_igreja(conn, args.igreja)
            u = (await conn.execute(
                text("SELECT id, nome, role, ativo FROM usuarios WHERE igreja_id = :i AND lower(username) = :u"),
                {"i": ig["id"], "u": usuario})).mappings().first()
            if not u:
                raise Recusa(f"usuário '{usuario}' não existe na igreja '{ig['nome']}'")
            await conn.execute(
                text("UPDATE usuarios SET senha_hash = :h, trocar_senha = true, ativo = true WHERE id = :id"),
                {"h": hash_senha(senha), "id": u["id"]})
    finally:
        await engine.dispose()
    auditar("senha", "ok", igreja_id=ig["id"], nome=ig["nome"], usuario=usuario, reativou=not u["ativo"])
    print(f"Senha de '{usuario}' ({u['role']}) em '{ig['nome']}' (id {ig['id']}) redefinida.")
    print(f"  SENHA TEMPORÁRIA: {senha}")
    print("  (mostrada só agora; a troca é exigida no próximo login. Sessões já abertas passam a ser barradas.)")
    if not u["ativo"]:
        print("  O usuário estava inativo e foi reativado.")
    return 0


async def cmd_editar(args) -> int:
    """Muda nome, subdomínio ou domínio próprio de uma igreja existente. Só altera o que for informado."""
    if not any((args.nome, args.subdominio, args.dominio, args.sem_dominio)):
        raise Recusa("nada a alterar: use --nome, --subdominio, --dominio ou --sem-dominio")
    if args.dominio and args.sem_dominio:
        raise Recusa("use --dominio ou --sem-dominio, não os dois")
    nome = args.nome.strip() if args.nome else None
    if nome is not None and not 2 <= len(nome) <= 120:
        raise Recusa("nome da igreja deve ter de 2 a 120 caracteres")
    sub = validar_subdominio(args.subdominio) if args.subdominio else None
    dom = validar_dominio(args.dominio) if args.dominio else None
    engine = criar_engine()
    try:
        async with engine.begin() as conn:
            await exigir_dono(conn)
            ig = await achar_igreja(conn, args.igreja)
            novo = {"nome": nome or ig["nome"], "subdominio": sub or ig["subdominio"],
                    "dominio_proprio": None if args.sem_dominio else (dom or ig["dominio_proprio"])}
            if not novo["subdominio"] and not novo["dominio_proprio"]:
                raise Recusa("a igreja ficaria sem nenhum endereço (subdomínio ou domínio próprio)")
            if novo["subdominio"] and not settings.dominio_base.strip():
                raise Recusa("DOMINIO_BASE não está definido: subdomínios não funcionariam.")
            mudou = {k: (ig[k], v) for k, v in novo.items() if ig[k] != v}
            if not mudou:
                print("Nada mudou: os valores informados já são os atuais.")
                return 0
            await checar_livre(conn, sub, dom, ignorar_id=ig["id"])
            await conn.execute(
                text("UPDATE igrejas SET nome = :n, subdominio = :s, dominio_proprio = :d WHERE id = :i"),
                {"n": novo["nome"], "s": novo["subdominio"], "d": novo["dominio_proprio"], "i": ig["id"]})
    finally:
        await engine.dispose()
    auditar("editar", "ok", igreja_id=ig["id"], alteracoes={k: {"de": a, "para": b} for k, (a, b) in mudou.items()})
    print(f"Igreja id {ig['id']} atualizada:")
    for k, (a, b) in mudou.items():
        print(f"  {k}: {a or '(vazio)'} -> {b or '(vazio)'}")
    if "subdominio" in mudou or "dominio_proprio" in mudou:
        print("  ATENÇÃO: o endereço antigo deixa de funcionar na hora (404) e quem instalou o app no celular precisa")
        print("  reinstalar pelo endereço novo; sessões abertas no endereço antigo caem. O certificado novo sai na")
        print("  primeira visita (precisa de DNS apontando para a VPS). O app guarda a resolução por até 30 segundos.")
    return 0


async def cmd_suspender(args) -> int:
    return await _mudar_status(args, False)


async def cmd_reativar(args) -> int:
    return await _mudar_status(args, True)


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="igrejas.py", description="Ferramenta do dono: gerencia as igrejas do sistema.")
    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("criar", help="cria igreja, configuração inicial e admin com senha temporária")
    c.add_argument("--nome", required=True)
    c.add_argument("--subdominio", help="vira <subdominio>.<DOMINIO_BASE>")
    c.add_argument("--dominio", help="domínio próprio do cliente (opcional)")
    c.add_argument("--admin-usuario", default="admin", help="login do primeiro admin (padrão: admin)")
    c.add_argument("--admin-nome", help="nome de exibição do admin")
    c.set_defaults(fn=cmd_criar)

    v = sub.add_parser("verificar", help="diz se o subdomínio/domínio é válido e está livre (não grava nada)")
    v.add_argument("--subdominio")
    v.add_argument("--dominio")
    v.set_defaults(fn=cmd_verificar)

    ls = sub.add_parser("listar", help="lista igrejas com status e contagens")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=cmd_listar)

    ed = sub.add_parser("editar", help="muda nome, subdomínio ou domínio próprio de uma igreja")
    ed.add_argument("igreja", help="id, subdomínio ou domínio próprio atual")
    ed.add_argument("--nome")
    ed.add_argument("--subdominio")
    ed.add_argument("--dominio", help="novo domínio próprio")
    ed.add_argument("--sem-dominio", action="store_true", help="remove o domínio próprio")
    ed.set_defaults(fn=cmd_editar)

    pw = sub.add_parser("senha", help="redefine a senha de um usuário (temporária, troca obrigatória)")
    pw.add_argument("igreja", help="id, subdomínio ou domínio próprio")
    pw.add_argument("--usuario", default="admin", help="login do usuário (padrão: admin)")
    pw.set_defaults(fn=cmd_senha)

    for nome, fn, ajuda in (("suspender", cmd_suspender, "bloqueia o acesso (403) e a emissão de certificado"),
                            ("reativar", cmd_reativar, "devolve o acesso")):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("igreja", help="id, subdomínio ou domínio próprio")
        if nome == "suspender":
            s.add_argument("--sim", action="store_true", help="confirma sem perguntar")
        s.set_defaults(fn=fn)
    return p


def main(argv=None) -> int:
    args = montar_parser().parse_args(argv)
    try:
        return asyncio.run(args.fn(args))
    except Recusa as e:
        auditar(args.comando, "recusado", motivo=str(e),
                **{k: v for k, v in vars(args).items() if k in ("nome", "subdominio", "dominio", "igreja", "usuario", "sem_dominio")})
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
