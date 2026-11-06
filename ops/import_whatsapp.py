#!/usr/bin/env python3
"""Importa uma exportação do WhatsApp (.txt ou .zip com o .txt) para o histórico do bot (group_log.jsonl).

Uso (dentro do container, que enxerga /opt/joy e /opt/data):
    docker cp export.zip sie-joy-bot:/tmp/export.zip
    docker exec sie-joy-bot /opt/hermes/.venv/bin/python /opt/joy/../data/scripts/import_whatsapp.py /tmp/export.zip [--dry-run]
Idempotente: mensagens já importadas (mesmo autor+horário+texto) são ignoradas.
"""
import datetime
import json
import os
import re
import sys
import zipfile

HOME = os.environ.get("HERMES_HOME", "/opt/data")
LOG = os.path.join(HOME, "group_log.jsonl")
GROUP = os.environ.get("EVOLUTION_HOME_CHANNEL", "120363000000000000@g.us")
# [14/10/2026 11:39:05] Nome: texto   |   14/10/2026 11:39 - Nome: texto   |   14/10/26, 11:39 - Nome: texto
LINE = re.compile(r"^‎?\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\]?\s*(?:-\s*)?([^:]+?):\s(.*)$")
MEDIA = re.compile(r"(<anexado:.*?>|<m[ií]dia oculta>|\(arquivo anexado\)|\.(?:jpg|jpeg|png|opus|ogg|pdf|mp4|webp)\b)", re.I)


def read_text(path: str) -> str:
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            return z.read(name).decode("utf-8", "replace")
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


SECRET = re.compile(r"(senha|password|token|csc|\.pfx|pplo\d+)", re.I)
DATE_START = re.compile(r"^\u200e?\[?\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}")
SKIP_SENDERS = {"mr irrelevant", "hermes", "sie"}
CUTOFF = datetime.datetime(2026, 10, 15, 11, 3)   # a partir daqui o bot já gravou ao vivo (evita duplicar)


def redact(t: str) -> str:
    return "[credencial removida]" if SECRET.search(t) else t


def parse(text: str):
    cur = None
    for raw in text.splitlines():
        m = LINE.match(raw.replace(" ", " "))
        if not m and DATE_START.match(raw):
            if cur:
                yield cur
            cur = None
            continue
        if m:
            if cur:
                yield cur
            d, mo, y, hh, mm, who, body = m.groups()
            y = int(y) + (2000 if int(y) < 100 else 0)
            dt = datetime.datetime(y, int(mo), int(d), int(hh), int(mm))
            cur = {"dt": dt, "who": who.strip(), "text": body}
        elif cur:
            cur["text"] += "\n" + raw
    if cur:
        yield cur


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    notes = {}
    if "--media-notes" in sys.argv:
        notes = json.load(open(sys.argv[sys.argv.index("--media-notes") + 1], encoding="utf-8"))
    items = [i for i in parse(read_text(sys.argv[1]))
             if i["who"].lower() not in SKIP_SENDERS and i["dt"] < CUTOFF and i["text"].strip()]
    for i in items:
        t = i["text"].strip()
        fm = re.search(r"([\w .\-]+\.(?:jpg|jpeg|png|opus|pdf))\s*\(arquivo anexado\)", t, re.I)
        if fm and fm.group(1).strip() in notes:
            t = f"[{fm.group(1).strip()}] conteúdo: {notes[fm.group(1).strip()]}"
        i["text"] = redact(t)
    seen = set()
    if os.path.isfile(LOG):
        for line in open(LOG, encoding="utf-8"):
            try:
                o = json.loads(line)
                seen.add((o.get("sender_name"), o.get("timestamp", "")[:16], (o.get("text") or "")[:80]))
            except ValueError:
                pass
    new = [i for i in items if (i["who"], i["dt"].isoformat()[:16], i["text"].strip()[:80]) not in seen]
    print(f"{len(items)} mensagens no arquivo, {len(new)} novas")
    if "--dry-run" in sys.argv:
        for i in new[:5]:
            print(i["dt"], i["who"], i["text"][:80])
        return 0
    with open(LOG, "a", encoding="utf-8") as out:
        for i in sorted(new, key=lambda x: x["dt"]):
            t = i["text"].strip()
            out.write(json.dumps({
                "timestamp": i["dt"].isoformat(), "time_str": i["dt"].strftime("%d/%m %H:%M"),
                "epoch": i["dt"].timestamp(), "chat_id": GROUP, "sender_name": i["who"], "sender_id": "",
                "is_audio": False, "kind": "document" if MEDIA.search(t) and len(t) < 80 else "text",
                "msg_id": "import", "text": t, "imported": True}, ensure_ascii=False) + "\n")
    print("importado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
