import os, re, time, json, threading, requests
from flask import Flask, request, jsonify
from rapidfuzz import process
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import psycopg2
from psycopg2.extras import Json
from sentence_transformers import SentenceTransformer

# ==== CONFIG ====
app = Flask(__name__)
DB_URL = os.getenv("DATABASE_URL")
WS_URL = os.getenv("WS_SEND_URL")
WS_TOKEN = os.getenv("WASENDER_TOKEN")
TZ = os.getenv("TZ", "America/Costa_Rica")

# ==== DB HELPERS ====
def db_conn():
    return psycopg2.connect(DB_URL, sslmode="require")

def ensure_schema():
    if not DB_URL: 
        print("[DB] DATABASE_URL no configurado")
        return
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS nlu_samples (
        id SERIAL PRIMARY KEY,
        text TEXT,
        intent TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS polizas_chunks (
        id SERIAL PRIMARY KEY,
        poliza TEXT,
        fuente TEXT,
        chunk TEXT,
        embedding VECTOR(384)
    );
    """)
    conn.commit()
    conn.close()
    print("[DB] schema asegurado")

# ==== NLU ====
CLASSES = ["auto_ins","schedule","statement","reminder","greet",
           "complaint","email_only","poliza","fallback"]

SEED = [
    ("hola","greet"),
    ("buenos días","greet"),
    ("quiero asegurar mi carro","auto_ins"),
    ("necesito una póliza de auto","auto_ins"),
    ("asegurar un pick up","auto_ins"),
    ("agendame una cita mañana","schedule"),
    ("quiero reunión con Jeff el 15/09","schedule"),
    ("estado de cuenta","statement"),
    ("muéstrame mi saldo","statement"),
    ("recordame pago de póliza","reminder"),
    ("avisame cuando venza la factura","reminder"),
    ("no me atendieron bien","complaint"),
    ("estoy molesto con el servicio","complaint"),
    ("mi correo es tony@example.com","email_only"),
    ("coberturas seguro equipo electrónico","poliza"),
    ("exclusiones seguro incendio","poliza"),
    ("qué cubre la póliza de construcción","poliza"),
    ("condiciones generales del seguro de auto","poliza"),
]

VECTORIZER = TfidfVectorizer()
CLASSIFIER = LogisticRegression(max_iter=200)
MODEL = None

def nlu_retrain():
    global VECTORIZER, CLASSIFIER, MODEL
    X_train = [x for x,y in SEED]
    y_train = [y for x,y in SEED]

    if DB_URL:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("SELECT text,intent FROM nlu_samples")
            rows = cur.fetchall()
            for t,i in rows:
                X_train.append(t)
                y_train.append(i)
            conn.close()
        except Exception as e:
            print("[DB] error cargando samples:", e)

    if X_train:
        X_vec = VECTORIZER.fit_transform(X_train)
        CLASSIFIER.fit(X_vec, y_train)
        MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        print(f"[NLU] modelo entrenado con {len(X_train)} ejemplos")
    else:
        print("[NLU] sin ejemplos")

def nlu_predict(text):
    if not MODEL:
        return "fallback", 0.0
    vec = VECTORIZER.transform([text])
    intent = CLASSIFIER.predict(vec)[0]
    prob = max(CLASSIFIER.predict_proba(vec)[0])
    return intent, prob

# ==== POLIZAS ====
def buscar_poliza(query):
    try:
        emb = MODEL.encode(query).tolist()
        conn = db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT poliza, fuente, chunk
                    FROM polizas_chunks
                    ORDER BY embedding <-> %s::vector
                    LIMIT 1
                """, (emb,))
                row = cur.fetchone()
        conn.close()
        if row:
            poliza, fuente, chunk = row
            return f"📄 *{poliza}* — Condiciones Generales:\n\n{chunk}\n\nFuente: {fuente}"
        else:
            return "No encontré condiciones generales para esa consulta."
    except Exception as e:
        print("[Polizas] error:", e)
        return "No pude acceder a las condiciones generales ahora."

# ==== RESPUESTAS ====
def send_text(to, text):
    if not WS_URL or not WS_TOKEN:
        print("[WS] faltan variables de entorno")
        return
    try:
        r = requests.post(WS_URL,
            headers={"Authorization": f"Bearer {WS_TOKEN}"},
            json={"to": to, "text": text}, timeout=10)
        print("[Wasender]", r.status_code, r.text)
    except Exception as e:
        print("[Wasender] error:", e)

def handle_intent(sender, intent, text):
    if intent == "greet":
        send_text(sender, "👋 Hola, soy Noa Asistente. ¿En qué te ayudo hoy?")
    elif intent == "auto_ins":
        send_text(sender, "🚗 Te ayudo con el seguro del carro. ¿Cuál es año, marca y modelo? (ej: 2018 Toyota Corolla)")
    elif intent == "schedule":
        send_text(sender, "📅 ¿Qué día y hora te viene bien? Ej.: 15/09 9am con Jeff")
    elif intent == "statement":
        send_text(sender, "📊 Consultando tu estado de cuenta...")
    elif intent == "reminder":
        send_text(sender, "⏰ Te agendo un recordatorio de pago.")
    elif intent == "complaint":
        send_text(sender, "😟 Lamento eso, lo escalaré a un agente humano.")
    elif intent == "email_only":
        send_text(sender, "📧 Gracias, guardaré tu correo.")
    elif intent == "poliza":
        respuesta = buscar_poliza(text)
        send_text(sender, respuesta)
    else:
        send_text(sender, "No te entendí 🤔. Probá reformular o pedí *menu* para opciones.")

# ==== FLASK ====
@app.route("/health")
def health():
    db = "off"
    if DB_URL:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            conn.close()
            db = "on"
        except Exception as e:
            print("[DB] error en health:", e)
    return jsonify({"ok": True, "status": "healthy", "db": db})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("==> Webhook payload:", data)
    sender = None
    text = None

    if "from" in data and "text" in data:
        sender = data["from"]; text = data["text"]
    elif "event" in data and data.get("data", {}).get("messages"):
        msg = data["data"]["messages"]
        if isinstance(msg, dict):
            sender = msg.get("key", {}).get("remoteJid", "").split("@")[0]
            if "conversation" in msg.get("message", {}):
                text = msg["message"]["conversation"]

    if not sender or not text:
        print("[WH] sender o text faltante")
        return jsonify({"ok": False})

    intent, prob = nlu_predict(text)
    print(f"[WH] from={sender} intent={intent} prob={prob:.2f} | text={text}")
    handle_intent(sender, intent, text)
    return jsonify({"ok": True})

# ==== MAIN ====
if __name__ == "__main__":
    ensure_schema()
    nlu_retrain()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
