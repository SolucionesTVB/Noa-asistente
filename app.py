from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime

app = Flask(__name__)

# Variables de entorno
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL")
WASENDER_TOKEN = os.getenv("WASENDER_TOKEN")
OWNER_PHONE = os.getenv("OWNER_PHONE", "+50600000000")
BOT_NAME = os.getenv("BOT_NAME", "Noa Asistente")

# --- Función para enviar mensajes ---
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

# --- Rutas ---
@app.route('/')
def home():
    return f"{BOT_NAME} está en línea 🚀"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    sender = data.get("from")
    text = data.get("text", "").lower().strip()

    reply = handle_message(sender, text)
    if reply:
        send_message(sender, reply)

    return jsonify({"status": "ok"}), 200

# --- Procesador de mensajes ---
def handle_message(sender, text):
    # --- Comandos del dueño ---
    if sender == OWNER_PHONE:
        if text == "ayuda":
            return "📋 Comandos: ayuda, recargar kb, status kb, modo silencio on/off, nota: <texto>"
        if text.startswith("nota:"):
            return f"📝 Guardé tu nota: {text[5:].strip()}"
        if text == "status kb":
            return "✅ Noa está corriendo en Render y escuchando mensajes."
        # (recargar kb y modo silencio se pueden simular luego)
    
    # --- Respuestas por intención ---
    if any(s in text for s in ["hola", "buenas", "saludos"]):
        return f"👋 Hola, soy {BOT_NAME}. ¿En qué te puedo ayudar hoy?"

    if "todo riesgo" in text:
        return "🔒 El seguro *Todo Riesgo* cubre daños materiales, responsabilidad civil y riesgos adicionales en Costa Rica."

    if "construcción" in text:
        return "🏗️ El seguro de *Todo Riesgo Construcción* protege la obra, materiales y responsabilidad civil durante la ejecución."

    if "electrónic" in text:
        return "💻 El seguro de *Equipo Electrónico* cubre computadoras, servidores y equipos de oficina contra daños accidentales."

    if "cotización" in text:
        return "📑 Claro, necesito tu *nombre, correo y tipo de seguro* para prepararte una propuesta."

    if "agendar" in text or "llamar" in text:
        return "📞 ¿Querés que agendemos una llamada? Decime hora y lo organizamos."

    if "recordame" in text:
        return "⏰ Perfecto, te voy a recordar eso. (Próximamente se conectará a Google Calendar/Sheets 😉)"

    if "resumime" in text:
        return "📄 Enviame el audio o texto y te lo resumo en 3 puntos."

    # --- Fallback ---
    return "🤖 Puedo ayudarte con *seguros (Todo Riesgo, Construcción, Electrónicos)* o recordatorios. ¿Qué ocupás?"

# --- Registro de logs (simple en archivo local) ---
@app.after_request
def log_request(response):
    with open("logs.txt", "a") as f:
        f.write(f"{datetime.now()} | {response.status} | {response.get_data(as_text=True)}\n")
    return response

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
