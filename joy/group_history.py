"""Histórico de conversas do grupo WhatsApp LPO - SIÉ JOY (JSONL append-only, seguro p/ escritas concorrentes)."""
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List

HOME = os.environ.get("HERMES_HOME", "/opt/data")
LOG_FILE = os.path.join(HOME, "group_log.jsonl")
LEGACY_FILE = os.path.join(HOME, "group_log.json")  # formato antigo (lista JSON), migrado na primeira leitura
MAX_LINES = 20000


def _migrate_legacy() -> None:
    if os.path.isfile(LOG_FILE) or not os.path.isfile(LEGACY_FILE):
        return
    try:
        with open(LEGACY_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        with open(LOG_FILE, "a", encoding="utf-8") as out:
            for m in old:
                out.write(json.dumps(m, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load() -> List[Dict[str, Any]]:
    _migrate_legacy()
    if not os.path.isfile(LOG_FILE):
        return []
    out: List[Dict[str, Any]] = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # linha truncada não derruba o histórico
    return out


def _trim_if_needed() -> None:
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_LINES:
            tmp = LOG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(lines[-MAX_LINES:])
            os.replace(tmp, LOG_FILE)
    except OSError:
        pass


def record_message(chat_id: str, sender_name: str, sender_id: str, text: str, is_audio: bool = False,
                   msg_id: str = "", kind: str = "text") -> None:
    """Registra uma mensagem (texto, áudio transcrito ou mídia) no log persistente do grupo."""
    now = datetime.now()
    entry = {
        "timestamp": now.isoformat(), "time_str": now.strftime("%d/%m %H:%M"), "epoch": time.time(),
        "chat_id": chat_id, "sender_name": sender_name, "sender_id": sender_id,
        "is_audio": is_audio, "kind": kind, "msg_id": msg_id, "text": (text or "").strip(),
    }
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    _migrate_legacy()
    with open(LOG_FILE, "a", encoding="utf-8") as f:  # O_APPEND: escrita única => sem corrida entre webhooks
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if int(now.timestamp()) % 50 == 0:
        _trim_if_needed()


def get_recent_messages(hours: float = 24.0, since_epoch: float = 0.0) -> List[Dict[str, Any]]:
    cutoff = max(time.time() - hours * 3600, since_epoch)
    return [m for m in _load() if m.get("epoch", 0) >= cutoff]


def format_messages(msgs: List[Dict[str, Any]], max_chars: int = 12000) -> str:
    if not msgs:
        return "Nenhuma mensagem recente registrada no grupo."
    lines = []
    for m in msgs:
        tag = {"audio": " (ÁUDIO)", "image": " (IMAGEM)", "document": " (DOCUMENTO)"}.get(
            m.get("kind") or ("audio" if m.get("is_audio") else "text"), "")
        lines.append(f"[{m.get('time_str')}] {m.get('sender_name')}{tag}: {m.get('text')}")
    full = "\n".join(lines)
    return full[-max_chars:] if len(full) > max_chars else full


def format_recent_history(hours: float = 24.0, max_chars: int = 12000) -> str:
    return format_messages(get_recent_messages(hours), max_chars)
