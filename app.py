# app.py — Noa Asistente (Wasender + Render) con diagnósticos
from flask import Flask, request, jsonify
import os, requests, re
from datetime import datetime

app = Flask(__name__)

# ===== ENV =====
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message").strip()
WASENDER_TOKEN    = (os.getenv("WASENDER_TOKEN") or "").strip()
OWNER_PHONE       = os.getenv("OWNER_PHONE", "+50660457989").strip()
BOT_NAME          = os.getenv("BOT_NAME", "Noa Asistente").strip()

# Normaliza por si te pasaron solo el dominio
if WASENDER_BASE_URL.rstrip("/") == "https://wasenderapi.com":
    WASENDER_BASE_URL = "https://wasenderapi.com/api/send-message"

# ===== Utils =====
def append_log(line: str):
    try:
        with open("logs.txt", "a") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")
    except Exception as e:
        print("[LOG WARN]", e)

def clean_msisdn(n: str) -> str:
    """+506XXXXXXXX sin espacios/guiones."""
    if not n: return n
    n = re.sub(r"[^\d+]", "", n)
    if n.startswith("506") and not n.startswith("+"):
        n = "+" + n
    return n

def send_message(to: str, text: str):
    """Envía mensaje por Wasender y loguea resultado."""
    to = clean_msisdn(to or "")
    if not to:
        print("[SEND] número vacío")
        return
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

# ===== Parse webhook (lista o dict) =====
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
    # soporta conversation y extendedTextMessage.body
    text = (message_obj.get("conversation")
            or (message_obj.get("extendedTextMessage") or {}).get("text")
            or "").strip()
    return clean_msisdn(sender), text

# ===== Intents =====
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
    if any(k in t for k in ("hola", "buenas", "hello")):
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
    if any(k in t for k in ("agendar", "llamar", "llamada")):
        return "📞 ¿Te agendo una llamada? Decime día y hora."

    # recordatorios
    if any(k in t for k in ("recordame", "recordar", "recordatorio")):
        append_log(f"[REMINDER] {sender}: {text}")
        return "⏰ Anotado. (Pronto se conecta a calendario)."

    # fallback
    return ("🤖 Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones y recordatorios. ¿Qué ocupás?")

# ===== Rutas =====
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

# ===== Endpoints de diagnóstico =====
@app.route("/debug", methods=["GET"])
def debug():
    masked_token = (WASENDER_TOKEN[:6] + "…" + WASENDER_TOKEN[-6:]) if WASENDER_TOKEN else ""
    return jsonify({
        "BOT_NAME": BOT_NAME,
        "OWNER_PHONE": OWNER_PHONE,
        "WASENDER_BASE_URL": WASENDER_BASE_URL,
        "WASENDER_TOKEN_masked": masked_token
    })

@app.route("/self-test", methods=["POST"])
def self_test():
    """Envía un ping a OWNER_PHONE para validar token/env sin Wasender Webhook."""
    msg = "Ping de Noa ✅ (self-test)"
    send_message(OWNER_PHONE, msg)
    return jsonify({"ok": True, "sent_to": OWNER_PHONE, "text": msg})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
