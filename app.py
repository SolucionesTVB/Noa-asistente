import os, re, time, json, threading, requests
from flask import Flask, request, jsonify
from rapidfuzz import process, fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sentence_transformers import SentenceTransformer
import psycopg2

app = Flask(__name__)

# ===== Config =====
WS_TOKEN    = os.getenv("WASENDER_TOKEN")
WS_SEND_URL = os.getenv("WS_SEND_URL", "https://wasenderapi.com/api/send-message")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "noa-admin-123")
BOT_NAME    = "Noa"
BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "contacto@noa.cr")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_ENABLED = bool(DATABASE_URL)

SEEN_IDS, LAST_SENT = set(), {}
MIN_GAP = 5  # Wasender: 1 msg / 5s

# ===== Utilidades =====
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
    ok = 200 <= r.status_code < 300
    if ok: LAST_SENT[to] = time.time()
    return ok

# ===== DB =====
def db_conn():
    ssl = "require" if ("render.com" in DATABASE_URL or "neon.tech" in DATABASE_URL) else None
    return psycopg2.connect(DATABASE_URL, sslmode=ssl)

def db_exec(sql, params=None, fetch=False):
    if not DB_ENABLED: return None
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
    db_exec("""
    CREATE TABLE IF NOT EXISTS nlu_samples(
      id BIGSERIAL PRIMARY KEY, text TEXT NOT NULL, intent VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS sessions(
      phone TEXT PRIMARY KEY, intent VARCHAR(64), step INT, data JSONB DEFAULT '{}'::jsonb, updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS polizas_chunks(
      id SERIAL PRIMARY KEY,
      poliza TEXT,
      fuente TEXT,
      chunk TEXT,
      embedding VECTOR(384)
    );
    """)

# ===== Sesiones =====
_MEM_SESS = {}
def sess_get(phone):
    if not DB_ENABLED: return _MEM_SESS.get(phone)
    rows = db_exec("SELECT intent,step,data FROM sessions WHERE phone=%s;", (phone,), fetch=True)
    if rows:
        intent, step, data = rows[0]
        return {"intent":intent, "step":step, "data":(data or {})}
    return None
def sess_set(phone, sess):
    if not DB_ENABLED: _MEM_SESS[phone] = sess; return
    db_exec("""
    INSERT INTO sessions(phone,intent,step,data,updated_at)
    VALUES(%s,%s,%s,%s,now())
    ON CONFLICT (phone) DO UPDATE SET intent=EXCLUDED.intent, step=EXCLUDED.step, data=EXCLUDED.data, updated_at=now();
    """,(phone, sess.get("intent"), sess.get("step"), json.dumps(sess.get("data",{}))))
def sess_clear(phone):
    if not DB_ENABLED: _MEM_SESS.pop(phone, None); return
    db_exec("DELETE FROM sessions WHERE phone=%s;", (phone,))

# ===== NLU =====
CLASSES = ["auto_ins","schedule","statement","reminder","greet","complaint","email_only","poliza","fallback"]
SEED = [
    ("quiero asegurar mi carro","auto_ins"),
    ("necesito seguro de auto","auto_ins"),
    ("cotización para vehículo","auto_ins"),
    ("asegurar mi vehículo","auto_ins"),
    ("agendá con jeff el 15 de setiembre a las 9am","schedule"),
    ("quiero una reunión mañana a las 10","schedule"),
    ("estado de cuenta","statement"),
    ("enviar recordatorio de pago","reminder"),
    ("hola","greet"),
    ("no estas leyendo bien","complaint"),
    ("pásame el correo","email_only"),
    ("qué cubre el seguro de equipo electrónico","poliza"),
    ("exclusiones en el seguro de autos","poliza"),
    ("condiciones generales del todo riesgo construcción","poliza"),
    ("qué incluye la póliza de incendios","poliza"),
]

LABEL2ID = {c:i for i,c in enumerate(CLASSES)}
ID2LABEL = {i:c for c,i in LABEL2ID.items()}
VECTORIZER, CLF = None, None
USER_DATA_PATH = "nlu_user.json"

def load_user_samples():
    if DB_ENABLED:
        rows = db_exec("SELECT text,intent FROM nlu_samples;", fetch=True) or []
        return [(r[0], r[1]) for r in rows]
    return []
def save_user_sample(text, intent):
    if DB_ENABLED:
        db_exec("INSERT INTO nlu_samples(text,intent) VALUES (%s,%s);", (text,intent))
def nlu_retrain():
    global VECTORIZER, CLF
    user = load_user_samples()
    X_text = [t for t,_ in SEED] + [t for t,_ in user]
    y_lab  = [y for _,y in SEED] + [y for _,y in user]
    if not X_text: X_text, y_lab = ["hola"], ["greet"]
    VECTORIZER = TfidfVectorizer(ngram_range=(1,2), max_features=20000, sublinear_tf=True)
    X = VECTORIZER.fit_transform([_lc(t) for t in X_text])
    y = [LABEL2ID.get(lbl, LABEL2ID["fallback"]) for lbl in y_lab]
    CLF = SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=2000, tol=1e-3)
    CLF.fit(X, y)
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

# ===== Polizas =====
MODEL = SentenceTransformer("all-MiniLM-L6-v2")

def buscar_poliza(query):
    try:
        emb = MODEL.encode(query).tolist()
        rows = db_exec("""
            SELECT poliza, fuente, chunk
            FROM polizas_chunks
            ORDER BY embedding <-> %s::vector
            LIMIT 1
        """, (emb,), fetch=True)
        if rows:
            poliza, fuente, chunk = rows[0]
            return f"📄 *{poliza}* — Condiciones Generales:\n\n{chunk}\n\nFuente: {fuente}"
        else:
            return "No encontré condiciones generales para esa consulta."
    except Exception as e:
        print("[Polizas] error:", e)
        return "No pude acceder a las condiciones generales ahora."

# ===== Intents =====
def greet(to): send_text(to, f"¡Hola! Soy {BOT_NAME}. Contame en una frase qué necesitás: asegurar tu carro, agendar una reunión, estado de cuenta o un recordatorio de pago.")
def complaint(to): send_text(to, "Tenés razón, no te leí bien. Decime en una frase clara qué querés y te hago una pregunta puntual para avanzar.")
def email_only(to): send_text(to, f"Nuestro correo de contacto es {BUSINESS_EMAIL}.")
def handle_statement(to): send_text(to, "Con gusto. Pasame tu *cédula o correo* y te devuelvo el estado de cuenta.")
def handle_reminder(to): send_text(to, "Decime *nombre del cliente* y *monto* para enviar el recordatorio.")

def handle_auto(to, text):
    s = sess_get(to) or {"intent":"auto_ins","step":1,"data":{}}
    if s["step"] == 1:
        send_text(to, "Te ayudo con el seguro del carro. ¿Cuál es *año, marca y modelo*?")
        s["step"] = 2; sess_set(to, s); return
    if s["step"] == 2:
        s["data"].update({"vehiculo": text})
        send_text(to, "Perfecto. Ahora decime *valor aproximado* y tu *correo* para enviarte la cotización.")
        s["step"] = 3; sess_set(to, s); return
    if s["step"] == 3:
        s["data"].update({"detalle": text})
        send_text(to, f"¡Listo! Tomé: {s['data']}. Te confirmo por correo en breve. ¿Algo más?")
        sess_clear(to); return

def handle_schedule(to, text):
    send_text(to, "¿Para qué *día y hora* te viene bien? Ej.: *15/09 9am* o *15 de setiembre 9:30 am*. Si es con alguien, decime con quién.")

def handle_fallback(to, text): send_text(to, "No te entendí del todo. Decime en una frase qué necesitás (p.ej. *asegurar mi carro*, *agendar con Jeff 15/09 9am*, *estado de cuenta*, *recordatorio de pago*).")

# ===== Rutas =====
@app.get("/health")
def health(): return jsonify(ok=True, status="healthy", db=("on" if DB_ENABLED else "off"))

@app.post("/webhook")
def webhook():
    payload = request.get_json(force=True, silent=True) or {}
    print("==> Webhook payload:", payload)
    sender = _norm_to(payload.get("from") or payload.get("jid") or payload.get("phone") or "")
    text = _norm_text(payload.get("text") or payload.get("body") or "")
    if not sender: return jsonify(ok=True), 200

    s = sess_get(sender)
    if s and s.get("intent") == "auto_ins":
        handle_auto(sender, text); return jsonify(ok=True)

    intent, conf = nlu_predict(text)
    print(f"[NLU] intent={intent} conf≈{conf:.2f}")

    if intent == "greet": greet(sender)
    elif intent == "complaint": complaint(sender)
    elif intent == "email_only": email_only(sender)
    elif intent == "auto_ins": handle_auto(sender, text)
    elif intent == "schedule": handle_schedule(sender, text)
    elif intent == "statement": handle_statement(sender)
    elif intent == "reminder": handle_reminder(sender)
    elif intent == "poliza": send_text(sender, buscar_poliza(text))
    else: handle_fallback(sender, text)
    return jsonify(ok=True)

if __name__ == "__main__":
    ensure_schema()
    nlu_retrain()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
