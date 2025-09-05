# app.py
from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime

app = Flask(__name__)

# ========= Config =========
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message")
WASENDER_TOKEN = os.getenv("WASENDER_TOKEN", "")
OWNER_PHONE = os.getenv("OWNER_PHONE", "+50600000000")
BOT_NAME = os.getenv("BOT_NAME", "Noa Asistente")

# ========= Util: envío de mensajes =========
def send_message(to: str, text: str):
    if not (WASENDER_BASE_URL and WASENDER_TOKEN):
        print("[WARN] Falta WASENDER_BASE_URL o WASENDER_TOKEN")
        return
    headers = {
        "Authorization": f"Bearer {WASENDER_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"to": to, "text": text}
    try:
        r = requests.post(WASENDER_BASE_URL, json=payload, headers=headers, timeout=15)
        print("[Wasender] status", r.status_code, "resp", r.text)
    except Exception as e:
        print("[ERROR] Enviando mensaje:", e)

# ========= Extractores tolerantes (parche) =========
def extract_sender(payload: dict) -> str | None:
    # claves directas comunes
    for k in ["from", "jid", "phone", "waId", "waid"]:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # WhatsApp Cloud-like
    try:
        return payload["messages"][0]["from"]
    except Exception:
        pass
    # anidados
    snd = payload.get("sender")
    if isinstance(snd, dict):
        v = snd.get("id") or snd.get("phone")
        if v: return v
    return None

def extract_text(payload: dict) -> str:
    # directos
    for k in ["text", "message", "body", "content"]:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            vv = v.get("body") or v.get("text")
            if isinstance(vv, str) and vv.strip():
                return vv.strip()
    # WhatsApp Cloud-like
    try:
        msg = payload["messages"][0]
        if "text" in msg and "body" in msg["text"]:
            return msg["text"]["body"].strip()
        if msg.get("type") == "text" and "body" in msg:
            return msg["body"].strip()
    except Exception:
        pass
    # dentro de "data"
    data = payload.get("data")
    if isinstance(data, dict):
        vv = data.get("text") or data.get("body")
        if isinstance(vv, str) and vv.strip():
            return vv.strip()
    return ""

# ========= Intenciones / Reglas =========
def handle_message(sender: str, text: str) -> str:
    t = text.lower().strip()

    # --- Comandos del dueño ---
    if sender == OWNER_PHONE:
        if t == "ayuda":
            return ("📋 *Comandos (dueño)*\n"
                    "• ayuda\n"
                    "• status kb\n"
                    "• modo silencio on / modo silencio off (placeholder)\n"
                    "• nota: <texto>")
        if t == "status kb":
            return "✅ Noa en línea (Render). Webhook activo."
        if t.startswith("nota:"):
            nota = t[5:].strip()
            if nota:
                append_log(f"[NOTA] {sender}: {nota}")
                return f"📝 Guardé tu nota: {nota}"
            return "Decime el texto de la nota: `nota: …`"
        if t in ["modo silencio on", "modo silencio off"]:
            return "🔇 Modo silencio es placeholder por ahora. Lo activamos luego con horario."

    # --- Saludos ---
    if any(s in t for s in ["hola", "buenas", "saludos", "buenos días", "buenas tardes", "buenas noches"]):
        return f"👋 Hola, soy *{BOT_NAME}*. ¿En qué te puedo ayudar hoy?"

    # --- Seguros CR (respuestas cortas base) ---
    if "todo riesgo" in t and "constru" in t:
        return ("🏗️ *Todo Riesgo Construcción*: cubre obra, materiales, equipo y RC durante la ejecución. "
                "Decime nombre y correo para enviarte una propuesta.")
    if "todo riesgo" in t:
        return ("🔒 *Seguro Todo Riesgo*: daños materiales, robo, RC y adicionales según póliza. "
                "¿Querés una cotización? Nombre y correo, porfa.")
    if "electrónic" in t:
        return ("💻 *Equipo Electrónico*: protege computadoras, servidores y equipos de oficina contra daños accidentales, "
                "picos de tensión y robo con violencia.")

    # --- Cotización / datos ---
    if "cotiz" in t or "precio" in t:
        return "📑 Para cotizar: *nombre, correo y tipo de seguro* (Todo Riesgo, Construcción, Electrónicos)."

    # --- Agendar / llamada ---
    if "agendar" in t or "llamar" in t or "agenda" in t:
        return "📞 ¿Te agendo una llamada? Decime día y hora y lo organizamos."

    # --- Recordatorios (placeholder) ---
    if "recordame" in t or "recordar" in t:
        return "⏰ Lo anoto. Próximamente conectaré con calendario para recordarte automáticamente."

    # --- Resumen (placeholder) ---
    if "resumime" in t or "resumen" in t:
        return "📄 Enviame el audio o texto y te lo resumo en 3 puntos."

    # --- Fallback ---
    return ("🤖 Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones y recordatorios. ¿Qué ocupás?")

# ========= Logging simple =========
def append_log(line: str):
    try:
        with open("logs.txt", "a") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")
    except Exception as e:
        print("[WARN] No se pudo escribir logs.txt:", e)

@app.after_request
def log_response(resp):
    append_log(f"HTTP {resp.status} -> {resp.get_data(as_text=True)[:200]}")
    return resp

# ========= Rutas =========
@app.route("/")
def home():
    return f"{BOT_NAME} está en línea 🚀"

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    print("==> Webhook payload:", payload)  # visible en Logs de Render
    append_log(f"PAYLOAD {str(payload)[:400]}")

    sender = extract_sender(payload)
    text = extract_text(payload)

    if not sender:
        print("[WARN] No sender en payload")
        return jsonify({"ok": True, "note": "no sender"}), 200

    reply = handle_message(sender, text or "")
    if reply:
        send_message(sender, reply)

    return jsonify({"ok": True}), 200

# ========= Main =========
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
