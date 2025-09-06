import os, re, json, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# *** Credenciales embebidas (como pediste) ***
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
    """Acepta +5068..., 5068..., 5068...@s.whatsapp.net y devuelve solo dígitos con prefijo país si ya venía."""
    s = str(n or "")
    s = s.split("@")[0]  # quita '@s.whatsapp.net' si viene
    s = s.replace(" ", "").replace("-", "")
    return s

def extract_sender_and_text(data: dict):
    """
    Intenta leer SENDER y TEXT de varios formatos:
    - Plano: {"from": "...", "text": "..."} o keys similares
    - Wasender variantes: {"jid": "...", "message": "..."} | {"sender": "...", "body": "..."}
    - WhatsApp Cloud API: {"entry":[{"changes":[{"value":{"messages":[{"from":"...", "text":{"body":"..."}}]}}]}]}
    - Chat-API: {"messages":[{"author":"...", "body":"..."}]}
    """
    sender = ""
    text = ""

    # 1) Plano / sencillo
    for k in ("from", "jid", "sender", "phone", "number", "waId"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            sender = v
            break

    # text directo o anidado simple
    direct_text_keys = ("text", "message", "body", "msg")
    for k in direct_text_keys:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            text = v
            break
        if isinstance(v, dict):
            for kk in ("body", "text"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    text = vv
                    break

    # 2) WhatsApp Cloud API (anidado)
    if not sender or not text:
        try:
            entry = data.get("entry") or []
            if entry:
                changes = entry[0].get("changes", [])
                if changes:
                    val = changes[0].get("value", {})
                    msgs = val.get("messages", []) or []
                    if msgs:
                        m = msgs[0]
                        sender = sender or m.get("from", "")
                        # text puede venir como dict {"body": "..."}
                        if not text:
                            if isinstance(m.get("text"), dict):
                                text = m["text"].get("body", "")
                            elif isinstance(m.get("text"), str):
                                text = m.get("text")
                            elif isinstance(m.get("button"), dict):
                                text = m["button"].get("text", "")
                            elif isinstance(m.get("interactive"), dict):
                                # botón o lista
                                inter = m["interactive"]
                                text = (inter.get("button_reply", {}) or {}).get("title") \
                                       or (inter.get("list_reply", {}) or {}).get("title") \
                                       or ""
        except Exception:
            pass

    # 3) Chat-API / GreenAPI / similares
    if (not sender or not text) and isinstance(data.get("messages"), list) and data["messages"]:
        m = data["messages"][0]
        sender = sender or m.get("author") or m.get("from") or ""
        text   = text   or m.get("body")   or ""

    return normalize_to(sender), normalize_text(text)

def send_text(to: str, text: str) -> bool:
    if not WS_TOKEN or not WS_SEND_URL:
        print("[ERR] Faltan credenciales Wasender.")
        return False
    headers = {"Authorization": f"Bearer {WS_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": to, "text": text}
    try:
        r = requests.post(WS_SEND_URL, json=payload, headers=headers, timeout=15)
        print(f"[Wasender] {r.status_code} {r.text[:200]}")
        return r.ok
    except Exception as e:
        print(f"[ERR] send_text: {e}")
        return False

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
    print(f"[WH] sender={sender} | text={text_in}")

    if not sender:
        # No pudimos identificar a quién responder: registrar y salir "ok" para que el proveedor no reintente sin fin
        print("[WARN] No sender detected in payload.")
        return jsonify(ok=True, note="no-sender"), 200

    if text_in in ("hola","buenas","menu","", None):
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
