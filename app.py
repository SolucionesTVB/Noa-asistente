# app.py — Noa Asistente (Wasender + Render) v2
# - Intenciones: saludo, seguros (Todo Riesgo / Construcción / Electrónicos), pedir datos, recordatorios, cierre
# - Modo silencio fuera de horario (configurable)
# - Lista blanca opcional
# - Comandos de dueño (ayuda, status kb, nota: <texto>)
# - Endpoints: /health, /debug, /self-test
# - Logs simples a logs.txt

from flask import Flask, request, jsonify
import os, requests, re, json
from datetime import datetime, time
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ========= ENV =========
WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com/api/send-message").strip()
WASENDER_TOKEN    = (os.getenv("WASENDER_TOKEN") or "").strip()
OWNER_PHONE       = os.getenv("OWNER_PHONE", "+50660457989").strip()
BOT_NAME          = os.getenv("BOT_NAME", "Noa Asistente").strip()

# Opcionales
TIMEZONE          = os.getenv("TZ", "America/Costa_Rica").strip()
# Formato "HH:MM-HH:MM" (ej: "20:00-07:30"). Fuera de ese rango = silencio.
QUIET_HOURS       = os.getenv("QUIET_HOURS", "")  # "" para desactivar; ejemplo recomendado: "20:00-07:30"
# "true"/"false": usar LLM (futuro). Ahora solo reglas si es false.
USE_LLM           = (os.getenv("USE_LLM", "false").lower().strip() == "true")
# Coma-separado: +506XXXXXXXX, +1XXXXXXXXXX
WHITELIST         = [n.strip() for n in os.getenv("WHITELIST", "").split(",") if n.strip()]  # vacío = responder a todos
# Si no está en whitelist: "auto" = presentar y pedir nombre; "hold" = no responder
REPLY_UNKNOWN     = os.getenv("REPLY_UNKNOWN", "auto").strip().lower()  # "auto" | "hold"

# Normaliza URL del API si quedó solo el dominio
if WASENDER_BASE_URL.rstrip("/") == "https://wasenderapi.com":
    WASENDER_BASE_URL = "https://wasenderapi.com/api/send-message"

# ========= UTILS =========
def append_log(line: str):
    try:
        with open("logs.txt", "a") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")
    except Exception as e:
        print("[LOG WARN]", e)

def clean_msisdn(n: str) -> str:
    """Devuelve +506XXXXXXXX sin espacios/guiones si corresponde."""
    if not n: return n
    n = re.sub(r"[^\d+]", "", n)
    if n.startswith("506") and not n.startswith("+"):
        n = "+" + n
    return n

def send_message(to: str, text: str):
    """Envía mensaje por Wasender y deja rastro en logs."""
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
        append_log(f"SEND -> {to} | {text[:150]} | {r.status_code}")
    except Exception as e:
        print("[Wasender ERROR]", e)
        append_log(f"SEND ERROR -> {to} | {e}")

def get_now_local():
    try:
        return datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        return datetime.utcnow()

def parse_hhmm(s: str) -> time | None:
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except Exception:
        return None

def is_quiet_hours(now: datetime) -> bool:
    """Devuelve True si estamos fuera de horario (modo silencio activo)."""
    if not QUIET_HOURS:
        return False
    slot = QUIET_HOURS.replace(" ", "")
    if "-" not in slot:
        return False
    start_s, end_s = slot.split("-", 1)
    t_start, t_end = parse_hhmm(start_s), parse_hhmm(end_s)
    if not (t_start and t_end):
        return False
    cur = now.time()
    # Si el rango cruza medianoche (ej: 20:00-07:30)
    if t_start > t_end:
        return (cur >= t_start) or (cur < t_end)
    # Rango normal (ej: 18:00-21:00)
    return (cur >= t_start) and (cur < t_end)

def present_intro(name: str = "Soy Noa"):
    return (f"👋 {name}. Asistente de Tony.\n"
            "Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones, recordatorios y consultas técnicas.\n"
            "¿Cómo te llamás?")

# ========= PARSE WEBHOOK =========
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
    # texto (conversation o extendedTextMessage.text)
    message_obj = (msg.get("message") or {})
    text = (message_obj.get("conversation")
            or (message_obj.get("extendedTextMessage") or {}).get("text")
            or "").strip()
    return clean_msisdn(sender), text

# ========= INTENTS =========
def handle_owner_commands(t: str) -> str | None:
    if t == "ayuda":
        return ("📋 *Comandos (dueño)*\n"
                "• ayuda\n• status kb\n• nota: <texto>\n"
                "• modo silencio on/off\n")
    if t == "status kb":
        return "✅ Noa en línea. Webhook OK."
    if t.startswith("nota:"):
        nota = t[5:].strip()
        if nota:
            append_log(f"[NOTA] {OWNER_PHONE}: {nota}")
            return f"📝 Guardé tu nota: {nota}"
        return "Decime el texto de la nota: `nota: …`"
    if t in ("modo silencio on", "modo silencio off"):
        # No persistimos en ENV (Render), pero dejamos log y confirmación.
        estado = "activado" if t.endswith("on") else "desactivado"
        append_log(f"[MODO_SILENCIO] {estado} (manual)")
        return f"🔇 Modo silencio {estado} (temporal)"
    return None

def intent_reply(text: str, sender: str) -> str:
    """Reglas base para responder. Si USE_LLM==True, aquí se podría integrar un LLM."""
    t = (text or "").lower().strip()

    # comandos dueño
    if sender == OWNER_PHONE:
        resp = handle_owner_commands(t)
        if resp:
            return resp

    # saludos
    if any(k in t for k in ("hola", "buenas", "hello")):
        return f"👋 Hola, soy *{BOT_NAME}*. ¿En qué te ayudo hoy?"

    # seguros CR
    if "todo riesgo" in t and ("constru" in t or "obra" in t):
        return ("🏗️ *Todo Riesgo Construcción*: protege obra, materiales y equipo, "
                "además de responsabilidad civil durante la ejecución.\n"
                "Decime *nombre y correo* para armar la propuesta.")
    if "todo riesgo" in t or ("seguro" in t and "auto" in t):
        return ("🚗 *Seguro Todo Riesgo (auto)*: daños propios, a terceros y coberturas adicionales según póliza.\n"
                "¿Querés cotizar? Pasame *nombre, correo y placa*.")
    if any(k in t for k in ("electrónic", "equipo electrónico", "servidor", "computadora")):
        return ("💻 *Equipo Electrónico*: cubre equipos ante daño accidental, picos de voltaje y robo con violencia.\n"
                "Si te interesa, pasame *nombre y correo*.")

    # pedir datos / cotización
    if any(k in t for k in ("cotiz", "precio", "presup")):
        return "📑 Para cotizar: *nombre, correo y tipo de seguro* (Todo Riesgo, Construcción, Electrónicos)."

    # agenda / cierre
    if any(k in t for k in ("agendar", "llamar", "llamada", "agenda", "cita")):
        return "📞 ¿Te agendo una llamada? Decime día y hora."

    # recordatorios
    if any(k in t for k in ("recordame", "recordar", "recordatorio")):
        append_log(f"[REMINDER] {sender}: {text}")
        return "⏰ Anotado. (Pronto conectaré calendario para recordarte automático)."

    # fallback
    return ("🤖 Puedo ayudarte con *seguros en Costa Rica* (Todo Riesgo, Construcción, Electrónicos), "
            "cotizaciones y recordatorios. ¿Qué ocupás?")

# ========= RUTAS =========
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return f"{BOT_NAME} está activo ✅", 200

@app.route("/debug", methods=["GET"])
def debug():
    masked_token = (WASENDER_TOKEN[:6] + "…" + WASENDER_TOKEN[-6:]) if WASENDER_TOKEN else ""
    return jsonify({
        "BOT_NAME": BOT_NAME,
        "OWNER_PHONE": OWNER_PHONE,
        "WASENDER_BASE_URL": WASENDER_BASE_URL,
        "WASENDER_TOKEN_masked": masked_token,
        "TZ": TIMEZONE,
        "QUIET_HOURS": QUIET_HOURS,
        "USE_LLM": USE_LLM,
        "WHITELIST": WHITELIST,
        "REPLY_UNKNOWN": REPLY_UNKNOWN
    })

@app.route("/self-test", methods=["POST"])
def self_test():
    """Envía un ping al dueño para validar token/URL sin depender del webhook."""
    msg = "Ping de Noa ✅ (self-test)"
    send_message(OWNER_PHONE, msg)
    return jsonify({"ok": True, "sent_to": OWNER_PHONE, "text": msg})

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

        # Lista blanca
        if WHITELIST and sender not in WHITELIST:
            if REPLY_UNKNOWN == "auto":
                send_message(sender, present_intro())
            # si es "hold", no respondemos nada
            return jsonify({"ok": True, "note": "unknown sender handled"}), 200

        # Modo silencio (fuera de horario)
        now = get_now_local()
        if is_quiet_hours(now) and sender != OWNER_PHONE:
            # Ejemplo: 8:30 por defecto
            morning_at = now.replace(hour=8, minute=30, second=0, microsecond=0)
            hh = morning_at.strftime("%H:%M")
            send_message(sender, f"🌙 Estoy fuera de horario. Te respondo en la mañana, ¿te parece si te escribo a las {hh}?")
            return jsonify({"ok": True, "note": "quiet hours"}), 200

        # Reglas (o LLM si se activa en el futuro)
        reply = intent_reply(text, sender)
        if reply:
            send_message(sender, reply)

    except Exception as e:
        print("[Webhook ERROR]", e)
        append_log(f"WEBHOOK ERROR {e}")

    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
