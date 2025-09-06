import os, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Credenciales embebidas (como pediste)
WS_TOKEN   = "551e81dc3c384cb437675f4066e84e081595a38d35193921f4e7eb3556e97466"  # sin "Bearer"
WS_SEND_URL= "https://wasenderapi.com/api/send-message"

MENU = (
    "🤖 *Noa* — Asistente de Cobros\n"
    "1) Enviar recordatorio de pago\n"
    "2) Consultar estado de cuenta\n"
    "3) Hablar con un agente\n"
    "Escribe *1*, *2* o *3*. Escribe *menu* para volver aquí."
)

def send_text(to: str, text: str) -> bool:
    if not WS_TOKEN or not WS_SEND_URL:
        print("[ERR] Faltan credenciales Wasender."); return False
    headers = {"Authorization": f"Bearer {WS_TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(WS_SEND_URL, json={"to": to, "text": text}, headers=headers, timeout=15)
        print(f"[Wasender] {r.status_code} {r.text[:200]}"); return r.ok
    except Exception as e:
        print(f"[ERR] send_text: {e}"); return False

def norm(t: str) -> str: return (t or "").strip().lower()

@app.get("/")
def root(): return jsonify(ok=True, service="noa-backend", endpoints=["/health","/webhook"])

@app.get("/health")
def health(): return jsonify(ok=True, status="healthy")

@app.post("/webhook")
def webhook():
    d = request.get_json(force=True, silent=True) or {}
    to = d.get("from") or d.get("jid") or d.get("sender") or ""
    t  = norm(d.get("text") or d.get("message") or d.get("body"))
    print("==> Webhook payload:", d); print(f"[WH] from={to} | text={t}")
    if t in ("hola","buenas","menu",""): send_text(to, MENU);  return jsonify(ok=True)
    if t=="1": send_text(to,"📩 Pásame *nombre/cédula* y monto aprox. para armar el recordatorio."); return jsonify(ok=True)
    if t=="2": send_text(to,"📊 Dame tu *cédula o correo* y te devuelvo el estado de cuenta.");    return jsonify(ok=True)
    if t=="3": send_text(to,"👤 Te conecto con un agente. Horario: *L–V 8:00–17:00*. Escribe *menu* para volver."); return jsonify(ok=True)
    send_text(to,"No te entendí 🤔. Escribe *menu* para ver opciones."); return jsonify(ok=True)

if __name__=="__main__": app.run(host="0.0.0.0", port=int(os.getenv("PORT",8000)))
