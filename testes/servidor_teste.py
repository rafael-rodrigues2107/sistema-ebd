"""Sobe o app local com banco SQLite temporário (para teste no navegador)."""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

db = Path(__file__).parent / "teste_navegador.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
os.environ["DEBUG"] = "false"
os.environ["UPLOADS_DIR"] = str(Path(__file__).parent / "teste_uploads")
os.environ["SECRET_KEY"] = "teste-local-navegador"
BASE = Path(__file__).resolve().parent.parent / "app"
os.chdir(str(BASE))
sys.path.insert(0, str(BASE))

import uvicorn
uvicorn.run("main:app", host="127.0.0.1", port=8765)
