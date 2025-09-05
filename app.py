# app.py — Noa Asistente (Render + Wasender)
# Autor: Tony + Noa
# Descripción: Webhook robusto para WhatsApp (Wasender), comandos del dueño,
# intenciones básicas (seguros CR), y envío de respuestas.

from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime

app = Flask(__name__)

# ================== Configuración por variables de entorno ==================
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message")
WASENDER_TOKEN    = os.getenv("WASENDER_TOKEN", "")
OWNER_PHONE       = os.getenv("OWNER_PHONE", "+50600000000")
BOT_NAME          = os.getenv("BOT_NAME", "Noa Asistente")

# ================== Utilidades ==================
def send_message(to: str, text: str):
    """
    Envía un mensaje usando Wasender.
    NOTA: WASENDER_BASE_URL debe apuntar al endpoint final /api/send-message.
    """
    if not WASENDER_TOKEN or not WASENDER_BASE_URL:
        print("[WARN] Falta WASENDER_TOKEN o WASENDER_BASE_URL")
        return

    headers = {
        "Authorization": f"Bearer {WASENDER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"to": to, "text": text}

    try:
        r = requests.post(WASENDER_BASE_URL, headers=headers, json=payload, timeout=15)
        print(f"[Wasender] {r.status_code} {r.text}")
    except Exception as e:
        print("[ERROR] Enviando mensaje:", e)


def append_log(line: str):
    """Log simple a archivo (útil para auditoría rápida)."""
    try:
        with open("logs.txt", "a") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")
    except Exception as e:
        print("[WARN] No se pudo escribir logs.txt:", e)


# ================== Extracción robusta del payload ==================
def get_message_node(payload: dict) -> dict:
    """
    Wasender puede enviar 'messages' como lista o como objeto.
    Esta función devuelve un dict con el mensaje.
    """
    data = payload.get("data", {})
    msg = data.get("messages")

    # Si viene lista, agarramos el primero
    if isinstance(msg, list) and msg:
        return msg[0]
    # Si ya es dict, lo usamos directo
    if isinstance(msg, dict):
        return msg

    # Fallback (algunos tests envían {data: {message: "..."}})
    alt = data.get("message")
    if isinstance(alt, dict):
        return alt

    return {}


def extract_sender_and_text(payload: dict) -> tuple[str | None, str]:
    """
    Extrae número y texto del mensaje para Wasender.
    - Número: key.remoteJid -> "+506...@s.whatsapp.net" -> "+506..."
    - Texto: message.conversation
    """
    msg = get_message_node(payload)

    # Remitente
    remote_jid = (msg.get("key", {}) or {}).get("remoteJid", "")
    sender = remote_jid.split("@")[0] if remote_jid else None

    # Texto
    message_obj = msg.get("message", {}) or {}
    text = message_obj.get("conversation", "") or ""

    return sender, text.strip()


# ================== Reglas / Intenciones ==================
def handle_intent(sender: str, text: str) -> str:
    t = (text or "").lower().strip()

    # ---- Comandos del dueño (solo OWNER_PHONE) ----
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
        if t in ("modo silencio on", "modo silencio off"):
            return "🔇 Modo silencio (placeholder). Lo activamos luego con horario."

    # ---- Saludos ----
    if any(s in t for s in ("hola", "buenas", "saludos", "buenos días", "buenas tardes", "buenas noches")):
        return f"👋 Hola, soy *{BOT_NAME}*. ¿En qué te puedo ayudar hoy?"

    # ---- Seguros Costa Rica (respuestas base) ----
    if "todo riesgo" in t and "constru" in t:
        return ("🏗️ *Todo Riesgo Construcción*: cubre obra, materiales, equipo y RC durante la ejecución. "
                "Decime nombre y correo para una propuesta.")
    if "todo riesgo" in t:
        return ("🔒 *Seguro Todo Riesgo*: daños materiales, robo, RC y adicionales según póliza. "
                "¿Querés cotización? Nombre y correo, porfa.")
    if "electrónic" in t:
        return ("💻 *Equipo Electrónico*: protege computadoras, servidores y equipos de oficina contra daños "
                "accidentales, picos de tensión y robo con violencia.")

    # ---- Cotización / datos ----
    if "cotiz" in t or "precio" in t:
        return "📑 Para cotizar: *nombre, correo y tipo de seguro* (Todo Riesgo, Construcción, Electrónicos)."

    # ---- Agendar / llamada ----
    if any(k in t for k in ("agendar", "llamar", "agenda", "llamada")):
        return "📞 ¿Te agendo una llamada? Decime día y hora y lo organizamos."

    # ---- Recordatorios (placeholder) ----
    if any(k in t for k in ("recordame", "recordar", "recordatorio")):
        return "⏰ Lo anoto. Próximamente conectaré con calendario para recordarte automáticamente."

    # ---- Resumen (placeholder) ----
    if "resumime" in t or "resumen" in t:
        return "📄 Enviame el audio o texto y te lo resumo en 3 puntos."

    # ---- Fallback ----
    return ("🤖 Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones y recordatorios. ¿Qué ocupás?")


# ================== Rutas ==================
@app.route("/")
def home():
    return f"{BOT_NAME} está en línea 🚀"


@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    append_log(f"PAYLOAD {str(payload)[:500]}")
    print("==> Webhook payload:", payload)

    try:
        sender, text = extract_sender_and_text(payload)
        print(f"[WH] sender={sender} | text={text}")

        if not sender:
            # Responder 200 para que Wasender no reintente
            return jsonify({"ok": True, "note": "no sender"}), 200

        reply = handle_intent(sender, text)
        if reply:
            send_message(sender, reply)

    except Exception as e:
        print("Error procesando webhook:", e)

    return jsonify({"ok": True}), 200


# ================== Main (solo local) ==================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
