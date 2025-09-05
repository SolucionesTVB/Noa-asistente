from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime

app = Flask(__name__)

# Variables de entorno
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message")
WASENDER_TOKEN = os.getenv("WASENDER_TOKEN")
OWNER_PHONE = os.getenv("OWNER_PHONE", "+50660457989")
BOT_NAME = os.getenv("BOT_NAME", "Noa Asistente")

# Función para enviar mensajes
def send_message(to, text):
    headers = {
        "Authorization": f"Bearer {WASENDER_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": to,
        "text": text
    }
    try:
        r = requests.post(WASENDER_BASE_URL, headers=headers, json=payload)
        print("[Wasender]", r.status_code, r.text)
        return r.status_code, r.text
    except Exception as e:
        print("[Error send_message]", e)
        return 500, str(e)

# --- Lógica de intenciones ---
def handle_intent(text, sender):
    t = text.lower()

    # Saludo
    if t in ["hola", "buenas", "hello"]:
        return f"👋 Hola, soy {BOT_NAME}. ¿En qué te ayudo hoy?"

    # Seguros
    if "todo riesgo" in t:
        return "🚗 El seguro Todo Riesgo cubre daños propios y a terceros, ideal para autos en Costa Rica."
    if "construcción" in t:
        return "🏗️ El seguro Todo Riesgo Construcción protege tu obra ante imprevistos como accidentes, incendios o robo."
    if "electrónico" in t or "equipo" in t:
        return "💻 El seguro de Equipo Electrónico cubre computadoras, servidores y dispositivos ante daño o robo."

    # Recordatorios
    if "recordame" in t or "recuérdeme" in t:
        return "📌 Anotado. Te voy a enviar un recordatorio según lo indicado."

    # Cierre
    if "cotizar" in t or "propuesta" in t:
        return "¿Querés que te agende una llamada para revisar la propuesta? 📞"

    # Fallback
    return "🤖 Puedo ayudarte con seguros, recordatorios o consultas técnicas. ¿Qué ocupás?"

# Ruta home
@app.route("/", methods=["GET"])
def home():
    return f"{BOT_NAME} está activo ✅"

# Webhook para mensajes entrantes
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("==> Webhook payload:", data)

    try:
        # Extraer número y texto
        msg = data.get("data", {}).get("messages", {})
        sender = msg.get("key", {}).get("remoteJid", "").split("@")[0]
        text = msg.get("message", {}).get("conversation", "")

        print(f"[WH] sender={sender} | text={text}")

        if sender and text:
            reply = handle_intent(text, sender)
            send_message(sender, reply)

    except Exception as e:
        print("[Webhook error]", e)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
