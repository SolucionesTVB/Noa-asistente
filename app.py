# app.py — Noa Asistente (Wasender + Render)
from flask import Flask, request, jsonify
import os, requests
from datetime import datetime

app = Flask(__name__)

# ====== ENV ======
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message").strip()
WASENDER_TOKEN    = (os.getenv("WASENDER_TOKEN") or "").strip()
OWNER_PHONE       = os.getenv("OWNER_PHONE", "+50660457989").strip()
BOT_NAME          = os.getenv("BOT_NAME", "Noa Asistente").strip()

# Normaliza por si te pasaron el dominio sin el path
if WASENDER_BASE_URL.rstrip("/") == "https://wasenderapi.com":
    WASENDER_BASE_URL = "https://wasenderapi.com/api/send-message"

# ====== util ======
def append_log(line: str):
    try:
        with open("logs.txt", "a") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")
    except Exception as e:
        print("[LOG WARN]", e)

def send_message(to: str, text: str):
    """Envía mensaje por Wasender y loguea el resultado."""
    if not WASENDER_TOKEN:
        print("[SEND] Falta WASENDER_TOKEN")
        return
    headers = {
        "Authorization": f"Bearer {WASENDER_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"to": to, "text": text}
    try:
        r = requests.post(WASENDER_BASE_URL, headers=headers, json=payload, timeout=20)
        print(f"[Wasender] {r.status_code} {r.text}")
        append_log(f"SEND -> {to} | {text[:120]} | {r.status_code}")
    except Exception as e:
        print("[Wasender ERROR]", e)
        append_log(f"SEND ERROR -> {to} | {e}")

# ====== parse webhook (lista o dict) ======
def get_message_node(payload: dict) -> dict:
    data = payload.get("data", {})
    msg = data.get("messages")
    if isinstance(msg, list) and msg:
        return msg[0]
    if isinstance(msg, dict):
        return msg
    alt = data.get("message")
    if isinstance(alt, dict):
        return alt
    return {}

def extract_sender_and_text(payload: dict):
    msg = get_message_node(payload)
    # remitente
    remote_jid = ((msg.get("key") or {}).get("remoteJid") or "").strip()
    sender = remote_jid.split("@")[0] if remote_jid else None
    # texto
    message_obj = (msg.get("message") or {})
    text = (message_obj.get("conversation") or "").strip()
    return sender, text

# ====== intents ======
def handle_intent(text: str, sender: str) -> str:
    t = (text or "").lower().strip()

    # dueño
    if sender == OWNER_PHONE:
        if t == "ayuda":
            return ("📋 *Comandos (dueño)*\n"
                    "• ayuda\n• status kb\n• nota: <texto>")
        if t == "status kb":
            return "✅ Noa en línea. Webhook OK."
        if t.startswith("nota:"):
            nota = t[5:].strip()
            if nota:
                append_log(f"[NOTA] {sender}: {nota}")
                return f"📝 Guardé tu nota: {nota}"
            return "Decime el texto de la nota: `nota: …`"

    # saludos
    if t in ("hola", "hello", "buenas") or "hola " in t or "buenas " in t:
        return f"👋 Hola, soy *{BOT_NAME}*. ¿En qué te ayudo hoy?"

    # seguros
    if "todo riesgo" in t and "constru" in t:
        return ("🏗️ *Todo Riesgo Construcción*: cubre obra, materiales, equipo y RC durante la ejecución. "
                "Decime *nombre y correo* para una propuesta.")
    if "todo riesgo" in t:
        return ("🔒 *Seguro Todo Riesgo*: daños propios, a terceros y adicionales según póliza. "
                "¿Querés cotizar? Pasame *nombre y correo*.")
    if "electrónic" in t or "equipo electrónico" in t:
        return ("💻 *Equipo Electrónico*: protege computadoras/servidores ante daño accidental, picos y robo con violencia.")

    # cotización / datos
    if "cotiz" in t or "precio" in t:
        return "📑 Para cotizar: *nombre, correo y tipo de seguro* (Todo Riesgo, Construcción, Electrónicos)."

    # agenda
    if "agendar" in t or "llamar" in t or "llamada" in t:
        return "📞 ¿Te agendo una llamada? Decime día y hora."

    # recordatorios (placeholder de almacenamiento)
    if "recordame" in t or "recordar" in t or "recordatorio" in t:
        append_log(f"[REMINDER] {sender}: {text}")
        return "⏰ Anotado. (Pronto se conecta a calendario para recordarte automático)."

    # fallback
    return ("🤖 Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones y recordatorios. ¿Qué ocupás?")

# ====== routes ======
@app.route("/", methods=["GET"])
def home():
    return f"{BOT_NAME} está activo ✅"

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    print("==> Webhook payload:", payload)
    append_log(f"PAYLOAD {str(payload)[:500]}")

    try:
        sender, text = extract_sender_and_text(payload)
        print(f"[WH] sender={sender} | text={text}")

        if not sender:
            return jsonify({"ok": True, "note": "no sender"}), 200

        reply = handle_intent(text, sender)
        if reply:
            send_message(sender, reply)

    except Exception as e:
        print("[Webhook ERROR]", e)
        append_log(f"WEBHOOK ERROR {e}")

    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
