import os, re, time, json, threading, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ===== Config =====
WS_TOKEN    = "551e81dc3c384cb437675f4066e84e081595a38d35193921f4e7eb3556e97466"
WS_SEND_URL = "https://wasenderapi.com/api/send-message"
ADMIN_TOKEN = "noa-admin-123"
BOT_NAME    = "Noa"
BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "contacto@noa.cr")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_ENABLED = bool(DATABASE_URL)

SEEN_IDS, LAST_SENT = set(), {}
MIN_GAP = 5  # Wasender: 1 msg / 5s

def _norm_text(t): 
    if not t: return ""
    t = str(t).strip()
    return t.replace("“","\"").replace("”","\"").replace("’","'").replace("‘","'")
def _lc(t): return _norm_text(t).lower()
def _norm_to(n):
    s = str(n or "").split("@")[0]
    return s.replace(" ", "").replace("-", "")

def send_text(to, text):
    if not (to and WS_TOKEN and WS_SEND_URL): return False
    now = time.time()
    gap = now - LAST_SENT.get(to, 0)
    if gap < MIN_GAP: time.sleep(MIN_GAP - gap)
    h = {"Authorization": f"Bearer {WS_TOKEN}","Content-Type":"application/json"}
    r = requests.post(WS_SEND_URL, json={"to":to,"text":text}, headers=h, timeout=15)
    print(f"[Wasender] {r.status_code} {r.text[:200]}")
    if r.status_code == 429:
        try: ra = max(2, min(10, int(r.json().get("retry_after",5))))
        except Exception: ra = 5
        time.sleep(ra)
        r = requests.post(WS_SEND_URL, json={"to":to,"text":text}, headers=h, timeout=15)
        print(f"[Wasender][retry] {r.status_code} {r.text[:200]}")
    ok = 200 <= r.status_code < 300
    if ok: LAST_SENT[to] = time.time()
    return ok

# ===== DB helpers (Postgres) =====
def db_conn():
    import psycopg2
    ssl = "require" if ("render.com" in DATABASE_URL or "neon.tech" in DATABASE_URL) else None
    return psycopg2.connect(DATABASE_URL, sslmode=ssl)

def db_exec(sql, params=None, fetch=False):
    if not DB_ENABLED: raise RuntimeError("DB off")
    conn = db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                if fetch: return cur.fetchall()
    finally:
        conn.close()

def ensure_schema():
    if not DB_ENABLED: return
    try:
        db_exec("""
        CREATE TABLE IF NOT EXISTS nlu_samples (
            id BIGSERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            intent VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        db_exec("""
        CREATE TABLE IF NOT EXISTS sessions (
            phone TEXT PRIMARY KEY,
            intent VARCHAR(64),
            step INT,
            data JSONB DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        print("[DB] nlu_samples & sessions OK")
    except Exception as e:
        print("[DB] init error:", e)

def sess_get(phone):
    if not DB_ENABLED: return _MEM_SESS.get(phone)
    rows = db_exec("SELECT intent, step, data FROM sessions WHERE phone=%s;", (phone,), fetch=True)
    if rows:
        intent, step, data = rows[0]
        return {"intent":intent, "step":step, "data":(data or {})}
    return None

def sess_set(phone, sess):
    if not DB_ENABLED:
        _MEM_SESS[phone] = sess; return
    db_exec("""
    INSERT INTO sessions (phone,intent,step,data,updated_at)
    VALUES (%s,%s,%s,%s,now())
    ON CONFLICT (phone) DO UPDATE SET intent=EXCLUDED.intent, step=EXCLUDED.step, data=EXCLUDED.data, updated_at=now();
    """, (phone, sess.get("intent"), sess.get("step"), json.dumps(sess.get("data",{}))))

def sess_clear(phone):
    if not DB_ENABLED:
        _MEM_SESS.pop(phone, None); return
    db_exec("DELETE FROM sessions WHERE phone=%s;", (phone,))

# fallback de memoria si no hay DB
_MEM_SESS = {}

# ===== Webhook parser (incluye Wasender messages.upsert) =====
def parse_event(payload: dict):
    # Plano
    for k in ("from","jid","sender","phone","number","waId"):
        v = payload.get(k)
        if isinstance(v,str) and v.strip():
            sender = _norm_to(v)
            text = payload.get("text") or payload.get("message") or payload.get("body") or ""
            if isinstance(text, dict): text = text.get("body") or text.get("text") or ""
            return sender, _norm_text(text)
    # Wasender upsert
    if payload.get("event") == "messages.upsert":
        data = payload.get("data") or {}
        m = data.get("messages") or {}
        if isinstance(m, list): m = m[0] if m else {}
        if not isinstance(m, dict): return None, None
        mid = (m.get("key") or {}).get("id") or m.get("id")
        if mid:
            if mid in SEEN_IDS: return None, None
            if len(SEEN_IDS) > 2000: SEEN_IDS.clear()
            SEEN_IDS.add(mid)
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

# ===== NLU (sklearn) =====
CLASSES = ["auto_ins","schedule","statement","reminder","greet","complaint","email_only","fallback"]
SEED = [
    ("quiero asegurar mi carro","auto_ins"),
    ("necesito seguro de auto","auto_ins"),
    ("cotización para vehículo","auto_ins"),
    ("seguro todo riesgo del carro","auto_ins"),
    ("asegurar mi vehículo","auto_ins"),
    ("agendá con jeff el 15 de setiembre a las 9am","schedule"),
    ("quiero una reunión mañana a las 10","schedule"),
    ("programar cita para el 20/09 3 pm","schedule"),
    ("agendar reunión","schedule"),
    ("estado de cuenta","statement"),
    ("quiero ver mi saldo","statement"),
    ("cuánto debo","statement"),
    ("enviar recordatorio de pago","reminder"),
    ("mandar cobro a juan por 35000","reminder"),
    ("recordatorio a cliente por mensualidad","reminder"),
    ("hola","greet"), ("buenas","greet"), ("buenos días","greet"), ("hey","greet"),
    ("no estas leyendo bien","complaint"), ("no me entendés","complaint"),
    ("pásame el correo","email_only"), ("dame el correo","email_only"), ("solo paseme el correo","email_only"),
    ("ayuda","fallback"), ("???","fallback"),
]
LABEL2ID = {c:i for i,c in enumerate(CLASSES)}
ID2LABEL = {i:c for c,i in LABEL2ID.items()}
VECTORIZER = None
CLF = None
USER_DATA_PATH = "nlu_user.json"
LOCK = threading.Lock()

def load_user_samples():
    if DB_ENABLED:
        try:
            rows = db_exec("SELECT text,intent FROM nlu_samples ORDER BY id ASC;", fetch=True) or []
            return [(r[0], r[1]) for r in rows]
        except Exception as e:
            print("[DB] read error:", e)
    try:
        with open(USER_DATA_PATH,"r",encoding="utf-8") as f:
            data = json.load(f)
        return [(d["text"], d["intent"]) for d in data if d.get("text") and d.get("intent") in CLASSES]
    except Exception:
        return []

def save_user_sample(text, intent):
    if DB_ENABLED:
        try:
            db_exec("INSERT INTO nlu_samples(text,intent) VALUES (%s,%s);", (text,intent)); return
        except Exception as e:
            print("[DB] insert error:", e)
    arr = []
    if os.path.exists(USER_DATA_PATH):
        with open(USER_DATA_PATH,"r",encoding="utf-8") as f: arr = json.load(f)
    arr.append({"text":text,"intent":intent})
    with open(USER_DATA_PATH,"w",encoding="utf-8") as f: json.dump(arr,f,ensure_ascii=False)

def nlu_retrain():
    global VECTORIZER, CLF
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import SGDClassifier
    user = load_user_samples()
    X_text = [t for t,_ in SEED] + [t for t,_ in user]
    y_lab  = [y for _,y in SEED] + [y for _,y in user]
    if not X_text: X_text, y_lab = ["hola"], ["greet"]
    VECTORIZER = TfidfVectorizer(ngram_range=(1,2), max_features=20000, sublinear_tf=True)
    X = VECTORIZER.fit_transform([_lc(t) for t in X_text])
    y = [LABEL2ID.get(lbl, LABEL2ID["fallback"]) for lbl in y_lab]
    CLF = SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=2000, tol=1e-3)
    CLF.fit(X, y)
    print(f"[NLU] modelo entrenado con {len(y)} ejemplos (DB={'on' if DB_ENABLED else 'off'})")

def nlu_predict(text):
    t = _lc(text)
    if not t.strip(): return "fallback", 0.0
    X = VECTORIZER.transform([t])
    try:
        proba = CLF.predict_proba(X)[0]
        idx = int(proba.argmax()); conf = float(proba[idx])
        return ID2LABEL[idx], conf
    except Exception:
        idx = int(CLF.predict(X)[0]); 
        return ID2LABEL[idx], 0.5

ensure_schema()
nlu_retrain()

# ===== extractores =====
EMAIL_RE = re.compile(r'[\w\.\+\-]+@[\w\.-]+\.\w+', re.I)
def extract_email(text):
    m = EMAIL_RE.search(text or "");  return m.group(0) if m else ""
def extract_value(text):
    t = _lc(text)
    m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(m|millon(?:es)?|millones)\b', t)
    if m: return f"{m.group(1).replace(',','.') } millones"
    m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(k|mil)\b', t)
    if m: return f"{m.group(1).replace(',','.') } mil"
    m = re.search(r'(usd|\$|dolares|dólares)\s*([\d\.\, ]+)', t)
    if m: return f"USD {re.sub(r'[^0-9\.]','', m.group(2))}"
    m = re.search(r'(₡|crc|colones?)\s*([\d\.\, ]+)', t)
    if m: return f"₡{re.sub(r'[^0-9\.]','', m.group(2))}"
    m = re.search(r'(\d[\d\.\, ]+)', t)
    if m: return re.sub(r'[^0-9\.]', '', m.group(1))
    return ""

# ===== intents auxiliares =====
def heuristic_intent(text, base, conf):
    t = _lc(text)
    if conf >= 0.55: return base
    if any(w in t for w in ("asegur","seguro","cotiz")) and any(w in t for w in ("carro","auto","vehicul")): return "auto_ins"
    if any(w in t for w in ("agend","reunion","reunión","cita","agenda")): return "schedule"
    if "estado de cuenta" in t or "saldo" in t or "cuenta" in t: return "statement"
    if "pago" in t or "recordatorio" in t or "cobrar" in t: return "reminder"
    if "pasame el correo" in t or "pásame el correo" in t or "dame el correo" in t: return "email_only"
    if "no estas leyendo" in t or "no estás leyendo" in t or "no me entend" in t: return "complaint"
    return base

# ===== respuestas =====
def greet(to):
    send_text(to, f"¡Hola! Soy {BOT_NAME}. Contame en una frase qué necesitás: asegurar tu carro, agendar una reunión, estado de cuenta o un recordatorio de pago.")
def complaint(to):
    send_text(to, "Tenés razón, no te leí bien. Decime en una frase clara qué querés y te hago una pregunta puntual para avanzar.")
def email_only(to):
    s = sess_get(to) or {}
    user_email = (s.get("data") or {}).get("email","")
    if user_email:
        send_text(to, f"Tengo tu correo: {user_email}. Si querés escribirnos directo: {BUSINESS_EMAIL}. ¿Seguimos con algo más?")
    else:
        send_text(to, f"Nuestro correo de contacto es {BUSINESS_EMAIL}. Si querés, pasame tu correo y te envío la info.")
def handle_statement(to): send_text(to, "Con gusto. Pasame tu *cédula o correo* y te devuelvo el estado de cuenta.")
def handle_reminder(to):  send_text(to, "Decime *nombre del cliente* y *monto* para enviar el recordatorio (ej.: Juan Pérez, ₡35.000 por mensualidad).")

def handle_schedule(to, text):
    MESES = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
    t = _lc(text)
    dmes = re.search(r'(\d{1,2})\s*(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b', t)
    d, mes = (int(dmes.group(1)), MESES[dmes.group(2)]) if dmes else (None, None)
    hhmm = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', t)
    hh, mm, ap = (int(hhmm.group(1)), int(hhmm.group(2) or 0), (hhmm.group(3) or "").lower()) if hhmm else (None, None, "")
    who = ""
    m = re.search(r'\bcon\s+([a-záéíóúñ ]{2,40})$', t)
    if m: who = m.group(1).strip().title()
    if d and (hh is not None):
        fecha = f"{d:02d}/{mes:02d}" if mes else f"{d:02d}/??"
        hora  = f"{hh:02d}:{mm:02d}" + (f" {ap}" if ap else "")
        send_text(to, f"Agendado{(' con '+who) if who else ''}: {fecha} a las {hora}. ¿Algo más?")
    else:
        send_text(to, "¿Para qué *día y hora* te viene bien? Ej.: *15/09 9am* o *15 de setiembre 9:30 am*. Si es con alguien, decime *con quién*.")

def handle_auto(to, text):
    s = sess_get(to) or {"intent":"auto_ins","step":1,"data":{}}

    if s["step"] == 1:
        send_text(to, "Te ayudo con el seguro del carro. ¿Cuál es *año, marca y modelo*? (ej: 2018 Toyota Corolla)")
        s["step"] = 2; sess_set(to, s); return

    if s["step"] == 2:
        year = re.search(r'(20\d{2}|19\d{2})', text or "")
        year = year.group(1) if year else ""
        # incluye números: 'x6'
        words = [w for w in re.findall(r'[a-z0-9áéíóúñ]+', _lc(text))]
        stop = {"modelo","marca","del","de","el"}
        words = [w for w in words if w not in stop]
        marca  = words[1] if len(words)>=2 else (words[0] if words else "")
        modelo = words[2] if len(words)>=3 else (words[1] if len(words)>=2 else "")
        s["data"].update({"year":year,"marca":marca,"modelo":modelo})
        send_text(to, "Perfecto. Ahora decime *valor aproximado* y tu *correo* para enviarte la cotización.")
        s["step"] = 3; sess_set(to, s); return

    if s["step"] == 3:
        eml   = extract_email(text)
        valor = extract_value(text)
        if eml:   s["data"]["email"] = eml
        if valor: s["data"]["valor"] = valor

        falta_email = not s["data"].get("email")
        falta_valor = not s["data"].get("valor")

        if falta_email and falta_valor:
            send_text(to, "Me falta tu *correo* y el *valor aproximado* del vehículo (ej.: ₡10.000.000 o 10 millones).")
            sess_set(to, s); return
        if falta_email:
            send_text(to, "¿Me pasás tu *correo* para enviarte la cotización?")
            sess_set(to, s); return
        if falta_valor:
            send_text(to, "¿Cuál es el *valor aproximado* del vehículo? (ej.: ₡10.000.000 o 10 millones)")
            sess_set(to, s); return

        y = s["data"].get("year") or "?"
        m = s["data"].get("marca") or "?"
        mo= s["data"].get("modelo") or "?"
        v = s["data"]["valor"]; e = s["data"]["email"]
        send_text(to, f"¡Listo! Tomé: {y} {m} {mo}, valor aprox {v}. Te confirmo por correo {e} en breve. ¿Algo más?")
        sess_clear(to); return

def handle_fallback(to, text):
    send_text(to, "No te entendí del todo. Decime en una frase qué necesitás (p.ej. *asegurar mi carro*, *agendar con Jeff 15/09 9am*, *estado de cuenta*, *recordatorio de pago*).")

# ===== Rutas =====
@app.get("/")
def root():
    return jsonify(ok=True, service="noa-backend",
                   endpoints=["/health","/webhook","/nlu/debug","/feedback","/nlu/retrain"],
                   db=("on" if DB_ENABLED else "off"))

@app.get("/health")
def health():
    return jsonify(ok=True, status="healthy", db=("on" if DB_ENABLED else "off"))

@app.post("/webhook")
def webhook():
    payload = request.get_json(force=True, silent=True) or {}
    print("==> Webhook payload:", payload)
    sender, text = parse_event(payload)
    print(f"[WH] sender={sender or ''} | text={text or ''}")
    if not sender: return jsonify(ok=True, note="ignored"), 200

    s = sess_get(sender)
    if s and s.get("intent") == "auto_ins":
        handle_auto(sender, text);  return jsonify(ok=True)

    # NLU
    intent, conf = nlu_predict(text)
    intent = heuristic_intent(text, intent, conf)
    print(f"[NLU] intent={intent} conf≈{conf:.2f}")

    if intent == "greet":       greet(sender)
    elif intent == "complaint": complaint(sender)
    elif intent == "email_only":email_only(sender)
    elif intent == "auto_ins":  handle_auto(sender, text)
    elif intent == "schedule":  handle_schedule(sender, text)
    elif intent == "statement": handle_statement(sender)
    elif intent == "reminder":  handle_reminder(sender)
    else:                       handle_fallback(sender, text)
    return jsonify(ok=True)

# ===== NLU admin =====
@app.get("/nlu/debug")
def nlu_debug():
    text = request.args.get("text","")
    label, conf = nlu_predict(text)
    return jsonify(text=text, intent=label, confidence=conf, db=("on" if DB_ENABLED else "off"))

@app.post("/feedback")
def feedback():
    token = request.headers.get("X-Admin-Token") or request.args.get("token") or (request.get_json(silent=True) or {}).get("token")
    if token != ADMIN_TOKEN: return jsonify(ok=False, error="unauthorized"), 401
    body = request.get_json(force=True) or {}
    text = (body.get("text") or "").strip()
    intent = (body.get("intent") or "").strip()
    if not text or intent not in CLASSES: return jsonify(ok=False, error="bad_input"), 400
    save_user_sample(text, intent)
    threading.Thread(target=nlu_retrain, daemon=True).start()
    return jsonify(ok=True, db=("on" if DB_ENABLED else "off"))

@app.post("/nlu/retrain")
def nlu_retrain_endpoint():
    token = request.headers.get("X-Admin-Token") or request.args.get("token") or (request.get_json(silent=True) or {}).get("token")
    if token != ADMIN_TOKEN: return jsonify(ok=False, error="unauthorized"), 401
    nlu_retrain()
    return jsonify(ok=True, msg="retrained", db=("on" if DB_ENABLED else "off"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
