import os, time, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Credenciales embebidas (como pediste)
WS_TOKEN   = "551e81dc3c384cb437675f4066e84e081595a38d35193921f4e7eb3556e97466"  # sin "Bearer"
WS_SEND_URL= "https://wasenderapi.com/api/send-message"  # espera {"to":"...","text":"..."}

MENU = (
    "🤖 *Noa* — Asistente de Cobros\n"
    "1) Enviar recordatorio de pago\n"
    "2) Consultar estado de cuenta\n"
    "3) Hablar con un agente\n"
    "Escribe *1*, *2* o *3*. Escribe *menu* para volver aquí."
)

def _norm_text(t: str) -> str:
    return (t or "").strip().lower()

def _norm_to(n: str) -> str:
    s = str(n or "")
    s = s.split("@")[0]                 # quita '@s.whatsapp.net'
    s = s.replace(" ", "").replace("-", "")
    return s if s else ""

LAST_SENT = {}
MIN_GAP = 5  # Wasender: 1 mensaje cada 5s

def send_text(to: str, text: str) -> bool:
    if not (to and WS_TOKEN and WS_SEND_URL):
        print("[ERR] send_text: faltan datos."); return False

    # rate limit simple por destinatario
    now = time.time()
    prev = LAST_SENT.get(to, 0)
    if now - prev < MIN_GAP:
        wait = MIN_GAP - (now - prev)
        print(f"[RATE] Esperando {wait:.1f}s -> {to}")
        time.sleep(wait)

    headers = {"Authorization": f"Bearer {WS_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": to, "text": text}
    r = requests.post(WS_SEND_URL, json=payload, headers=headers, timeout=15)
    print(f"[Wasender] {r.status_code} {r.text[:200]}")

    if r.status_code == 429:
        # reintento único respetando retry_after si viene
        try:
            ra = max(2, min(10, int(r.json().get("retry_after", 5))))
        except Exception:
            ra = 5
        print(f"[Wasender] 429 -> reintento en {ra}s")
        time.sleep(ra)
        r = requests.post(WS_SEND_URL, json=payload, headers=headers, timeout=15)
        print(f"[Wasender][retry] {r.status_code} {r.text[:200]}")

    ok = 200 <= r.status_code < 300
    if ok: LAST_SENT[to] = time.time()
    return ok

def parse_event(payload: dict):
    """
    Retorna (sender, text) soportando:
    - Plano: {"from": "...", "text": "..."} y variantes
    - Wasender: {"event":"messages.upsert", "data":{"messages":{ ... }}}
      * Ignora fromMe=True (eco propio)
      * Toma remoteJid y conversation / extendedTextMessage.text
    """
    # 1) Plano
    for k in ("from", "jid", "sender", "phone", "number", "waId"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            sender = _norm_to(v)
            text = payload.get("text") or payload.get("message") or payload.get("body") or ""
            if isinstance(text, dict):
                text = text.get("body") or text.get("text") or ""
            return sender, _norm_text(text)

    # 2) messages.upsert (lo que muestran tus logs)
    if payload.get("event") == "messages.upsert":
        data = payload.get("data") or {}
        m = data.get("messages") or {}
        if isinstance(m, list):
            m = m[0] if m else {}
        if not isinstance(m, dict):
            return None, None

        # ignorar mensajes nuestros (fromMe True)
        from_me = (m.get("key") or {}).get("fromMe") or m.get("fromMe")
        if from_me:
            return None, None

        sender = m.get("remoteJid") or (m.get("key") or {}).get("remoteJid") or ""
        sender = _norm_to(sender)

        msg = m.get("message") or {}
        text = ""
        if isinstance(msg, dict):
            text = msg.get("conversation") \
                or (msg.get("extendedTextMessage") or {}).get("text") \
                or (msg.get("imageMessage") or {}).get("caption") \
                or (msg.get("videoMessage") or {}).get("caption") \
                or ""

        return sender, _norm_text(text)

    return None, None

@app.get("/")
def root():
    return jsonify(ok=True, service="noa-backend", endpoints=["/health","/webhook"])

@app.get("/health")
def health():
    return jsonify(ok=True, status="healthy")

@app.post("/webhook")
def webhook():
    payload = request.get_json(force=True, silent=True) or {}
    print("==> Webhook payload:", payload)

    sender, text_in = parse_event(payload)
    print(f"[WH] sender={sender or ''} | text={text_in or ''}")

    # Si no hay remitente (p.ej. eco nuestro), no respondemos
    if not sender:
        return jsonify(ok=True, note="ignored"), 200

    if text_in in ("hola", "buenas", "menu", "", None):
        send_text(sender, MENU);  return jsonify(ok=True)
    if text_in == "1":
        send_text(sender, "📩 Pásame *nombre/cédula* y monto aprox. para armar el recordatorio.");  return jsonify(ok=True)
    if text_in == "2":
        send_text(sender, "📊 Dame tu *cédula o correo* y te devuelvo el estado de cuenta.");       return jsonify(ok=True)
    if text_in == "3":
        send_text(sender, "👤 Te conecto con un agente. Horario: *L–V 8:00–17:00*. Escribe *menu* para volver."); return jsonify(ok=True)

    send_text(sender, "No te entendí 🤔. Escribe *menu* para ver opciones.")
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
