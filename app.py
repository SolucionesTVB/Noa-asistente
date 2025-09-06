import os, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ====== Variables de entorno (Render → Settings → Environment) ======
# WS_TOKEN: SOLO el token (sin la palabra "Bearer")
# WS_SEND_URL: https://api.wasenderapi.com/message/sendText
WS_TOKEN = os.getenv("WS_TOKEN", "")
WS_SEND_URL = os.getenv("WS_SEND_URL", "")

MENU = (
    "🤖 *Noa* — Asistente de Cobros\n"
    "1) Enviar recordatorio de pago\n"
    "2) Consultar estado de cuenta\n"
    "3) Hablar con un agente\n"
    "Escribe *1*, *2* o *3*. Escribe *menu* para volver aquí."
)

def send_text(jid: str, text: str) -> bool:
    if not WS_TOKEN or not WS_SEND_URL:
        print("[ERR] Faltan WS_TOKEN o WS_SEND_URL en variables de entorno.")
        return False
    headers = {
        "Authorization": f"Bearer {WS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"jid": jid, "message": text}
    try:
        r = requests.post(WS_SEND_URL, json=payload, headers=headers, timeout=10)
        print(f"[Wasender] {r.status_code} {r.text[:200]}")
        return r.ok
    except Exception as e:
        print(f"[ERR] send_text: {e}")
        return False

def normalize_text(t: str) -> str:
    return (t or "").strip().lower()

@app.route("/", methods=["GET"])
def root():
    return jsonify(ok=True, service="noa-backend", endpoints=["/health","/webhook"])

@app.route("/health", methods=["GET"])
def health():
    return jsonify(ok=True, service="noa-backend", status="healthy")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    sender = data.get("jid") or data.get("from") or data.get("sender") or ""
    text = normalize_text(data.get("text") or data.get("message") or data.get("body"))
    print("==> Webhook payload:", data)
    print(f"[WH] sender={sender} | text={text}")

    if text in ("hola", "buenas", "menu", ""):
        send_text(sender, MENU);  return jsonify(ok=True)
    if text == "1":
        send_text(sender, "📩 Pásame *nombre/cédula* y monto aprox. para armar el recordatorio.");  return jsonify(ok=True)
    if text == "2":
        send_text(sender, "📊 Dame tu *cédula o correo* y te devuelvo el estado de cuenta.");       return jsonify(ok=True)
    if text == "3":
        send_text(sender, "👤 Te conecto con un agente. Horario: *L–V 8:00–17:00*. Escribe *menu* para volver."); return jsonify(ok=True)

    send_text(sender, "No te entendí 🤔. Escribe *menu* para ver opciones.")
    return jsonify(ok=True)

if __name__ == "__main__":
    # Render inyecta $PORT. Por defecto 8000 si corrés local.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
