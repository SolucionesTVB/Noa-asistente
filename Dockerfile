FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render inyecta $PORT. Usamos gunicorn con gthread (estable para I/O).
CMD ["bash","-lc","gunicorn -w 2 -k gthread --threads 8 -b 0.0.0.0:$PORT app:app"]
