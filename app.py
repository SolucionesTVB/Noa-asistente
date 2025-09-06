import os, time, re, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# == Credenciales (como pediste, embebidas) ==
WS_TOKEN   = "551e81dc3c384cb437675f4066e84e081595a38d35193921f4e7eb3556e97466"  # sin "Bearer"
WS_SEND_URL= "https://wasenderapi.com/api/send-message"  # {"to":"...","text":"..."}

# == Estado simple por remitente (memoria en RAM) ==
SESS = {}            # phone -> {"intent": str, "data": dict, "step": int}
SEEN_IDS = set()
LAST_SENT = {}
MIN_GAP = 5          # Wasender: 1 msg cada 5s

# ---------- Utils ----------
def _norm_text(t: str) -> str:
    t = (t or "").strip()
    # normaliza comillas raras
    t = t.replace("“","\"").replace("”","\"").replace("’","'").replace("‘","'")
    return t.lower()

def _norm_to(n: str) -> str:
    s = str(n or "")
    s = s.split("@")[0]            # quita '@s.whatsapp.net'
    return s.replace(" ", "").replace("-", "")

def send_text(to: str, text: str) -> bool:
    if not (to and WS_TOKEN and WS_SEND_URL): return False
    now = time.time()
    if now - LAST_SENT.get(to, 0) < MIN_GAP:
        time.sleep(MIN_GAP - (now - LAST_SENT[to]))
    h = {"Authorization": f"Bearer {WS_TOKEN}", "Content-Type": "application/json"}
    p = {"to": to, "text": text}
    r = requests.post(WS_SEND_URL, json=p, headers=h, timeout=15)
    print(f"[Wasender] {r.status_code} {r.text[:200]}")
    if r.status_code == 429:
        # reintento único
        try:
            ra = max(2, min(10, int(r.json().get("retry_after", 5))))
        except Exception:
            ra = 5
        time.sleep(ra)
        r = requests.post(WS_SEND_URL, json=p, headers=h, timeout=15)
        print(f"[Wasender][retry] {r.status_code} {r.text[:200]}")
    ok = 200 <= r.status_code < 300
    if ok: LAST_SENT[to] = time.time()
    return ok

# ---------- Parser de eventos (incluye messages.upsert) ----------
def parse_event(payload: dict):
    # Plano
    for k in ("from","jid","sender","phone","number","waId"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            sender = _norm_to(v)
            text = payload.get("text") or payload.get("message") or payload.get("body") or ""
            if isinstance(text, dict):
                text = text.get("body") or text.get("text") or ""
            return sender, _norm_text(text)

    # Wasender: messages.upsert
    if payload.get("event") == "messages.upsert":
        data = payload.get("data") or {}
        m = data.get("messages") or {}
        if isinstance(m, list): m = m[0] if m else {}
        if not isinstance(m, dict): return None, None

        # dedupe por id
        mid = (m.get("key") or {}).get("id") or m.get("id")
        if mid:
            if mid in SEEN_IDS: 
                print(f"[DEDUPE] {mid}"); return None, None
            if len(SEEN_IDS) > 2000: SEEN_IDS.clear()
            SEEN_IDS.add(mid)

        # ignorar nuestros mensajes
        if (m.get("key") or {}).get("fromMe") or m.get("fromMe"): 
            return None, None

        sender = _norm_to(m.get("remoteJid") or (m.get("key") or {}).get("remoteJid") or "")
        msg = m.get("message") or {}
        text = ""
        if isinstance(msg, dict):
            text = msg.get("conversation") \
                or (msg.get("extendedTextMessage") or {}).get("text") \
                or (msg.get("imageMessage") or {}).get("caption") \
                or (msg.get("videoMessage") or {}).get("caption") \
                or ""
        return sender, _norm_text(text)

    return None, None

# ---------- NLU simple (palabras clave) ----------
MESES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12
}

def detect_intent(text: str):
    t = _norm_text(text)
    if any(w in t for w in ("asegur","seguro","cotiz")) and any(w in t for w in ("carro","auto","vehicul")):
        return "auto_ins"
    if any(w in t for w in ("agend","reunion","reunión","cita","agenda")):
        return "schedule"
    if any(w in t for w in ("estado de cuenta","saldo","cuenta","debo")):
        return "statement"
    if any(w in t for w in ("pago","recordatorio","cobrar","cobro")):
        return "reminder"
    if t in ("hola","buenas","buenos dias","buenos días","hi","hey"):
        return "greet"
    return "fallback"

def parse_datetime_sp(text: str):
    """Parsea frases tipo '15 de setiembre a las 9am' o '15/09 9:30 pm'. Devuelve (dia, mes, hh, mm, ampm) o None."""
    t = _norm_text(text)
    # dd de mes hh(:mm)? am/pm
    m = re.search(r'(\d{1,2})\s*(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b.*?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', t)
    if m:
        d = int(m.group(1)); mes = MESES[m.group(2)]; hh = int(m.group(3)); mm = int(m.group(4) or 0); ampm = (m.group(5) or "").lower()
        return d, mes, hh, mm, ampm
    # dd/mm hh(:mm)? am/pm
    m = re.search(r'(\d{1,2})[/-](\d{1,2}).*?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', t)
    if m:
        d = int(m.group(1)); mes = int(m.group(2)); hh = int(m.group(3)); mm = int(m.group(4) or 0); ampm = (m.group(5) or "").lower()
        return d, mes, hh, mm, ampm
    # solo hora
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', t)
    if m:
        return None, None, int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    return None

# ---------- Handlers de intención ----------
def handle_greet(to): 
    txt = "¡Hola! Soy Noa. Contame en pocas palabras qué necesitás: asegurar tu carro, una cotización, agendar una reunión o ver tu estado de cuenta."
    send_text(to, txt)

def handle_auto_ins(to, text):
    st = SESS.setdefault(to, {"intent":"auto_ins","data":{}, "step":1})
    if st["step"] == 1:
        send_text(to, "Perfecto, te ayudo con el seguro del carro. Decime: *año, marca y modelo* (ej: 2018 Toyota Corolla).")
        st["step"] = 2; return
    if st["step"] == 2:
        # intentar extraer año + marca + modelo (muy simple)
        year = re.search(r'(20\d{2}|19\d{2})', text) or re.search(r'\b(\d{4})\b', text)
        year = year.group(1) if year else ""
        # marca y modelo: tomamos las 2 primeras palabras con letras
        words = [w for w in re.findall(r'[a-záéíóúñ]+', _norm_text(text)) if w not in ("modelo","marca","del","de","el")]
        marca = words[1] if (len(words)>=2 and not words[0].isdigit()) else (words[0] if words else "")
        modelo = words[2] if len(words)>=3 else ""
        st["data"].update({"year":year, "marca":marca, "modelo":modelo})
        send_text(to, "Genial. Ahora decime *valor aproximado* y *correo* para enviarte la cotización (ej: 10 millones, correo@dominio.com).")
        st["step"] = 3; return
    if st["step"] == 3:
        email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text or "", re.I)
        valor = re.search(r'(\d[\d\.\s,]*)\s*(millones|colones|crc|usd|$)', text or "", re.I)
        st["data"]["email"] = email.group(0) if email else ""
        st["data"]["valor"] = (valor.group(1)+" "+(valor.group(2) or "")).strip() if valor else ""
        y,m,mo = st["data"].get("year") or "?", st["data"].get("marca") or "?", st["data"].get("modelo") or "?"
        val = st["data"].get("valor") or "?"
        em  = st["data"].get("email") or "?"
        send_text(to, f"¡Listo! Tomé: {y} {m} {mo}, valor aprox: {val}. Te escribo al correo {em} con la cotización. ¿Algo más?")
        SESS.pop(to, None)

def handle_schedule(to, text):
    # intentar extraer fecha, hora y persona
    dt = parse_datetime_sp(text)
    persona = ""
    m = re.search(r'\bcon\s+([a-záéíóúñ ]{2,40})$', _norm_text(text))
    if m: persona = m.group(1).strip().title()
    if dt:
        d, mes, hh, mm, ampm = dt
        hora = f"{hh:02d}:{mm:02d}" + (f" {ampm}" if ampm else "")
        fecha = f"{(d or '??')}/{(mes or '??')}"
        quien = f" con {persona}" if persona else ""
        send_text(to, f"Agendado{quien}: {fecha} a las {hora}. Te confirmo por este medio. ¿Algo más?")
    else:
        send_text(to, "Dale, ¿para qué *día y hora*? Ej: *15/09 9am* o *15 de setiembre 9:30 am*. ¿Y con quién?")

def handle_statement(to, _text):
    send_text(to, "Con gusto. Decime tu *cédula o correo* y te devuelvo el estado de cuenta.")

def handle_reminder(to, _text):
    send_text(to, "Decime a quién y por qué monto querés enviar el recordatorio de pago. Ej: 'A Juan Pérez, ₡35.000 por mensualidad'.")

def handle_fallback(to, text):
    # sin menú ni números: guía breve
    if text in ("menu","menú","1","2","3"):
        send_text(to, "Hablame normal 🙂: 'asegurar mi carro', 'agendá con Jeff el 15/09 9am', 'estado de cuenta', 'enviar recordatorio de pago'.")
    else:
        send_text(to, "No te entendí del todo. Decime en una frase qué necesitás y te ayudo.")

# ---------- Rutas ----------
@app.get("/")
def root():
    return jsonify(ok=True, service="noa-backend", endpoints=["/health","/webhook"])

@app.get("/health")
def health():
    return jsonify(ok=True, status="healthy")

@app.post("/webhook")
def webhook():
    payload = request.get_json(force=True, silent=True) or {}
    print("==> Webhook payload:", payload)
    sender, text = parse_event(payload)
    print(f"[WH] sender={sender or ''} | text={text or ''}")

    if not sender:
        return jsonify(ok=True, note="ignored"), 200

    # flujo con estado
    st = SESS.get(sender)
    if st and st.get("intent") == "auto_ins":
        handle_auto_ins(sender, text);  return jsonify(ok=True)

    intent = detect_intent(text)
    if intent == "greet":      handle_greet(sender)
    elif intent == "auto_ins": handle_auto_ins(sender, text)
    elif intent == "schedule": handle_schedule(sender, text)
    elif intent == "statement":handle_statement(sender, text)
    elif intent == "reminder": handle_reminder(sender, text)
    else:                      handle_fallback(sender, text)
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
