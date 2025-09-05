# app.py — Noa Asistente (Render + Wasender)
# Reglas de intención + IA opcional (LLM) para fallback inteligente.
from flask import Flask, request, jsonify
import os, requests
from datetime import datetime

app = Flask(__name__)

# ===== Config (ENV) =====
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message")
WASENDER_TOKEN    = os.getenv("WASENDER_TOKEN", "")
OWNER_PHONE       = os.getenv("OWNER_PHONE", "+50600000000")
BOT_NAME          = os.getenv("BOT_NAME", "Noa Asistente")

# IA opcional
USE_LLM          = os.getenv("USE_LLM", "false").lower() in ("1","true","yes","on")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL        = os.getenv("LLM_MODEL", "gpt-4o-mini")  # cambialo si querés

# ===== Util =====
def send_message(to: str, text: str):
    if not (WASENDER_BASE_URL and WASENDER_TOKEN):
        print("[WARN] Falta WASENDER_BASE_URL o WASENDER_TOKEN")
        return
    headers = {"Authorization": f"Bearer {WASENDER_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": to, "text": text}
    try:
        r = requests.post(WASENDER_BASE_URL, headers=headers, json=payload, timeout=15)
        print(f"[Wasender] {r.status_code} {r.text}")
    except Exception as e:
        print("[ERROR] Enviando mensaje:", e)

def append_log(line: str):
    try:
        with open("logs.txt", "a") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")
    except Exception as e:
        print("[WARN] No se pudo escribir logs.txt:", e)

# ===== Parse webhook Wasender (lista o dict) =====
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
    remote_jid = (msg.get("key", {}) or {}).get("remoteJid", "")
    sender = remote_jid.split("@")[0] if remote_jid else None
    message_obj = msg.get("message", {}) or {}
    text = (message_obj.get("conversation") or "").strip()
    return sender, text

# ===== IA opcional (LLM) =====
def ai_reply(user_text: str) -> str:
    """
    Usa un LLM solo si USE_LLM=true y OPENAI_API_KEY está configurado.
    Prompt centrado en seguros CR + asistente personal de Tony.
    """
    if not (USE_LLM and OPENAI_API_KEY):
        return ""
    try:
        # Llamada simple usando REST (sin SDK) para evitar dependencias.
        import json
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        body = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": (
                    "Eres Noa, asistente de Tony en Costa Rica. "
                    "Respondes claro y breve. Sabes de seguros (Todo Riesgo, Construcción, Equipo Electrónico). "
                    "Si piden cotización, solicita nombre y correo. Si piden recordatorio, confirma y sugiere hora."
                )},
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.4,
            "max_tokens": 300
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions",
                             headers=headers, data=json.dumps(body), timeout=20)
        data = resp.json()
        txt = (data.get("choices", [{}])[0]
                   .get("message", {})
                   .get("content", "")).strip()
        return txt or ""
    except Exception as e:
        print("[LLM ERROR]", e)
        return ""

# ===== Reglas / Intenciones =====
def handle_intent(sender: str, text: str) -> str:
    t = (text or "").lower().strip()

    # Dueño
    if sender == OWNER_PHONE:
        if t == "ayuda":
            return ("📋 *Comandos (dueño)*\n"
                    "• ayuda\n• status kb\n• modo silencio on/off (placeholder)\n• nota: <texto>")
        if t == "status kb":
            return "✅ Noa en línea (Render). Webhook activo."
        if t.startswith("nota:"):
            nota = t[5:].strip()
            if nota:
                append_log(f"[NOTA] {sender}: {nota}")
                return f"📝 Guardé tu nota: {nota}"
            return "Decime el texto de la nota: `nota: …`"
        if t in ("modo silencio on", "modo silencio off"):
            return "🔇 Modo silencio (placeholder)."

    # Saludos
    if any(s in t for s in ("hola", "buenas", "saludos", "buenos días", "buenas tardes", "buenas noches")):
        return f"👋 Hola, soy *{BOT_NAME}*. ¿En qué te puedo ayudar hoy?"

    # Seguros CR
    if "todo riesgo" in t and "constru" in t:
        return ("🏗️ *Todo Riesgo Construcción*: cubre obra, materiales, equipo y RC durante la ejecución. "
                "Decime *nombre y correo* para enviarte una propuesta.")
    if "todo riesgo" in t:
        return ("🔒 *Seguro Todo Riesgo*: daños materiales, robo, RC y adicionales según póliza. "
                "¿Querés una cotización? Pasame *nombre y correo*.")
    if "electrónic" in t or "equipo electrónico" in t:
        return ("💻 *Equipo Electrónico*: protege computadoras, servidores y equipos contra daños, "
                "picos de tensión y robo con violencia. ¿Cotizamos?")

    # Cotización / datos
    if "cotiz" in t or "precio" in t:
        return "📑 Para cotizar: *nombre, correo y tipo de seguro* (Todo Riesgo, Construcción, Electrónicos)."

    # Agenda / llamada
    if any(k in t for k in ("agendar", "llamar", "agenda", "llamada")):
        return "📞 ¿Te agendo una llamada? Decime día y hora y lo organizamos."

    # Recordatorios
    if any(k in t for k in ("recordame", "recordar", "recordatorio")):
        append_log(f"[REMINDER] {sender}: {text}")
        return "⏰ Listo, lo anoté. (Pronto se conecta a calendar para recordarte automático)."

    # Resumen
    if "resumime" in t or "resumen" in t:
        return "📄 Enviame el audio o texto y te lo resumo en 3 puntos."

    # Fallback: primero IA (si está activada), si no, respuesta guía
    ai = ai_reply(text)
    if ai:
        return ai

    return ("🤖 Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones y recordatorios. ¿Qué ocupás?")

# ===== Rutas =====
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
            return jsonify({"ok": True, "note": "no sender"}), 200

        reply = handle_intent(sender, text)
        if reply:
            send_message(sender, reply)

    except Exception as e:
        print("Error procesando webhook:", e)

    return jsonify({"ok": True}), 200

# ===== Helpers internos =====
def extract_sender_and_text(payload: dict):
    msg = get_message_node(payload)
    remote_jid = (msg.get("key", {}) or {}).get("remoteJid", "")
    sender = remote_jid.split("@")[0] if remote_jid else None
    message_obj = msg.get("message", {}) or {}
    text = (message_obj.get("conversation") or "").strip()
    return sender, text

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

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
