from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL")
WASENDER_TOKEN = os.getenv("WASENDER_TOKEN")
OWNER_PHONE = os.getenv("OWNER_PHONE", "+50600000000")
BOT_NAME = os.getenv("BOT_NAME", "Noa Asistente")

@app.route('/')
def home():
    return f"{BOT_NAME} está en línea 🚀"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    sender = data.get("from")
    text = data.get("text", "").lower()

    # Respuesta básica
    if "hola" in text:
        reply = f"Hola 👋, soy {BOT_NAME}. ¿En qué te ayudo hoy?"
    else:
        reply = f"Recibí tu mensaje: {text}"

    # Enviar la respuesta a WhatsApp
    send_message(sender, reply)
    return jsonify({"status": "ok"}), 200

def send_message(to, text):
    headers = {
        "Authorization": f"Bearer {WASENDER_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"to": to, "text": text}
    try:
        r = requests.post(WASENDER_BASE_URL, json=payload, headers=headers)
        print("Respuesta Wasender:", r.json())
    except Exception as e:
        print("Error enviando mensaje:", e)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
