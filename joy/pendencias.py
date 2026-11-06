"""Livro de pendências/decisões: nada vira 'efetivado' sem evidência explícita citada do grupo."""
import datetime
import os
import sqlite3
from typing import Optional

DB = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "pendencias_joy.db")
ESTADOS = ("aberto", "efetivado", "descartado")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS pendencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, detalhe TEXT,
        estado TEXT NOT NULL DEFAULT 'aberto', evidencia TEXT,
        criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL, ultimo_perguntado TEXT,
        responsavel TEXT, prazo TEXT)""")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pendencias)")}
    for col in ("responsavel", "prazo"):
        if col not in cols:
            conn.execute(f"ALTER TABLE pendencias ADD COLUMN {col} TEXT")
    return conn


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def registrar(titulo: str, detalhe: Optional[str] = None, responsavel: Optional[str] = None,
              prazo: Optional[str] = None) -> str:
    titulo = (titulo or "").strip()
    if len(titulo) < 3:
        return "Erro: informe um título para a pendência."
    with _conn() as c:
        dup = c.execute("SELECT id FROM pendencias WHERE estado='aberto' AND LOWER(titulo)=LOWER(?)", (titulo,)).fetchone()
        if dup:
            return f"Já existe a pendência #{dup['id']} em aberto com esse título."
        cur = c.execute("INSERT INTO pendencias (titulo, detalhe, criado_em, atualizado_em, responsavel, prazo) "
                        "VALUES (?,?,?,?,?,?)", (titulo, detalhe, _now(), _now(), responsavel, prazo))
    return f"Pendência #{cur.lastrowid} registrada (em aberto): {titulo}"


def atualizar(pid: int, estado: str, evidencia: Optional[str] = None) -> str:
    estado = (estado or "").lower()
    if estado not in ESTADOS:
        return f"Erro: estado deve ser um de {', '.join(ESTADOS)}."
    if estado == "efetivado" and not (evidencia or "").strip():
        return "Erro: para marcar como efetivado cite a mensagem do grupo que confirma (evidencia)."
    with _conn() as c:
        cur = c.execute("UPDATE pendencias SET estado=?, evidencia=COALESCE(?, evidencia), atualizado_em=? WHERE id=?",
                        (estado, evidencia, _now(), int(pid)))
    return f"Pendência #{pid} → {estado}." if cur.rowcount else f"Pendência #{pid} não encontrada."


def listar(estado: str = "aberto", limite: int = 30) -> str:
    q, args = "SELECT * FROM pendencias", []
    if estado and estado != "todos":
        q += " WHERE estado=?"
        args.append(estado)
    q += " ORDER BY atualizado_em DESC LIMIT ?"
    args.append(int(limite))
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    if not rows:
        return f"Nenhuma pendência ({estado})."
    icon = {"aberto": "🟡", "efetivado": "✅", "descartado": "⚪"}
    return "\n".join(
        f"{icon.get(r['estado'], '•')} #{r['id']} {r['titulo']}"
        + (f" — {r['detalhe']}" if r["detalhe"] else "")
        + (f"\n   _evidência: {r['evidencia']}_" if r["evidencia"] else "")
        for r in rows
    )


def abertas_texto() -> str:
    with _conn() as c:
        rows = c.execute("SELECT id, titulo, detalhe FROM pendencias WHERE estado='aberto' ORDER BY id").fetchall()
    return "\n".join(f"#{r['id']} {r['titulo']}" + (f" ({r['detalhe']})" if r["detalhe"] else "") for r in rows)
