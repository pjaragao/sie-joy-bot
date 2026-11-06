#!/usr/bin/env python3
"""Envia mensagem simulada para o sie-joy-bot e verifica a resposta."""
import json
import os
import sys
import time
import urllib.request

TOKEN = "DidjncvRsW2pciXJm9Z_4QiAvnSwI9-A1TTZZQW6TwE"
GROUP = "120363000000000000@g.us"
PAULO_LID = "13108374433914@lid"
PAULO_PHONE = "5511900000000@s.whatsapp.net"
BOT_ID = "5511900000000"

def post(text: str, target_host: str = "127.0.0.1", port: int = 8660):
    mid = f"TEST-{int(time.time()*1000)}"
    body = {
        "event": "messages.upsert",
        "instance": "sleeper-bot",
        "data": {
            "key": {
                "remoteJid": GROUP,
                "fromMe": False,
                "id": mid,
                "participant": PAULO_LID,
                "participantAlt": PAULO_PHONE
            },
            "pushName": "Paulo José Aragão Júnior",
            "message": {
                "extendedTextMessage": {
                    "text": text,
                    "contextInfo": {
                        "mentionedJid": [f"{BOT_ID}@s.whatsapp.net"]
                    }
                }
            }
        }
    }
    url = f"http://{target_host}:{port}/webhook/evolution"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Webhook-Token": TOKEN}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, mid

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "@sie qual o valor previsto de capex para a loja joy?"
    print(f"Disparando: {msg}")
    st, mid = post(msg)
    print(f"Status HTTP: {st}, Message ID: {mid}")
