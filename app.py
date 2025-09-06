import os, json, time, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Credenciales embebidas (como pediste)
WS_TOKEN   = "551e81dc3c384cb437675f4066e84e081595a38d35193921f4e7eb3556e97466"  # sin "Bearer"
WS_SEND_URL= "https://wasenderapi.com/api/send-message"  # espera {"to": "...", "text": "..."}

MENU = (
    "🤖 *Noa* — Asistente de Cobros\n"
    "1) Enviar recordatorio de pago\n"
    "2) Consultar estado de cuenta\n"
    "3) Hablar con un agente\n"
    "Escribe *1*, *2* o *3*. Escribe *menu* para volver aquí."
)

def normalize_text(t: str) -> str:
    return (t or "").strip().lower()

def normalize_to(n: str) -> str:
    s = str(n or "")
    s = s.split("@")[0]           # quita '@s.whatsapp.net'
    s = s.replace(" ", "").replace("-", "")
    if s.startswith("+"):
        return s
    # si viene sin +, igual lo dejamos (Wasender acepta sin + en muchos casos)
    return s

# Memorias simples para anti-spam / dedupe
SEEN_IDS = set()
LAST_SENT_AT = {}   # to -> timestamp
MIN_GAP_SEC = 5     # Wasender pide 1 msg cada 5s

def send_text(to: str, text: str) -> bool:
    if not WS_TOKEN or not WS_SEND_URL or not to:
        print("[ERR] send_text: faltan datos (token/url/to).")
        return False

    # Respetar rate limit simple por destinatario
    now = time.time()
    tprev = LAST_SENT_AT.get(to, 0)
    gap = now - tprev
    if gap < MIN_GAP_SEC:
        wait = MIN_GAP_SEC - gap
        print(f"[RATE] Esperando {wait:.1f}s para {to}")
        time.sleep(wait)

    headers = {"Authorization": f"Bearer {WS_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": to, "text": text}

    try:
        r = requests.post(WS_SEND_URL, json=payload, headers=headers, timeout=15)
        print(f"[Wasender] {r.status_code} {r.text[:200]}")
        if r.status_code == 429:
            # Intentar una sola vez respetando retry_after si viene
            try:
                ra = r.json().get("retry_after", 5)
            except Exception:
                ra = 5
            ra = max(2, min(10, int(ra)))
            print(f"[Wasender] 429: reintentando en {ra}s…")
            time.sleep(ra)
            r = requests.post(WS_SEND_URL, json=payload, headers=headers, timeout=15)
            print(f"[Wasender][retry] {r.status_code} {r.text[:200]}")
        ok = 200 <= r.status_code < 300
        if ok:
            LAST_SENT_AT[to] = time.time()
        return ok
    except Exception as e:
        print(f"[ERR] send_text: {e}")
        return False

def extract_sender_and_text(payload: dict):
    """
    Devuelve (sender, text) o (None, None) si hay que ignorar (p.ej. fromMe=True).
    Soporta:
    - Plano: {"from": "...", "text": "..."} y variantes
    - Wasender 'messages.upsert' con:
        data.messages.key.remoteJid -> '506XXXX@s.whatsapp.net'
        data.messages.message.conversation
        data.messages.message.extendedTextMessage.text
    - Ignora eventos where fromMe=True (nuestro propio mensaje)
    """
    # 0) plano
    for k in ("from", "jid", "sender", "phone", "number", "waId"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            sender = normalize_to(v)
            text = None
            # texto directo o anidado
            for tk in ("text", "message", "body", "msg"):
                tv = payload.get(tk)
                if isinstance(tv, str) and tv.strip():
                    text = normalize_text(tv); break
                if isinstance(tv, dict):
                    for kk in ("body", "text"):
                        vv = tv.get(kk)
                        if isinstance(vv, str) and vv.strip():
                            text = normalize_text(vv); break
                if text: break
            return sender, text or ""

    # 1) evento upsert (estructura que estás viendo en logs)
    if payload.get("event") == "messages.upsert":
        data = payload.get("data", {}) or {}
        m = data.get("messages", {}) or {}
        # puede venir lista, tomamos el primero
        if isinstance(m, list):
            m = m[0] if m else {}
        if not isinstance(m, dict):
            return None, None

        # dedupe por id
        mid = (m.get("key", {}) or {}).get("id") or m.get("id")
        if mid:
            if mid in SEEN_IDS:
                print(f"[DEDUPE] Ignorando id repetido {mid}")
                return None, None
            # limitar memoria
            if len(SEEN_IDS) > 2000:
                SEEN_IDS.clear()
            SEEN_IDS.add(mid)

        # ignorar mensajes nuestros
        if (m.get("key", {}) or {}).get("fromMe") or m.get("fromMe"):
            return None, None

        # extraer remitente
        sender = m.get("remoteJid") or (m.get("key", {}) or {}).get("remoteJid") or ""
        sender = normalize_to(sender)

        # extraer texto
        msg = m.get("message") or {}
        text = ""
        if isinstance(msg, dict):
            text = msg.get("conversation") \
                or (msg.get("extendedTextMessage") or {}).get("text") \
                or (msg.get("imageMessage") or {}).get("caption") \
                or (msg.get("videoMessage") or {}).get("caption") \
                or ""

        return sender, normalize_text(text)

    return None, None

@app.get("/")
def root():
    return jsonify(ok=True, service="noa-backend", endpoints=["/health","/webhook"])

@app.get("/health")
def health():
    return jsonify(ok=True, status="healthy")

@app.post("/webhook")
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    print("==> Webhook payload:", data)

    sender, text_in = extract_sender_and_text(data)
    print(f"[WH] sender={sender or ''} | text={text_in or ''}")

    # Si no hay remitente (p.ej. era fromMe o un evento sin mensaje), salimos OK sin responder
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
