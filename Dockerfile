# Imagen base liviana de Python
FROM python:3.11-slim

# Evita buffer en logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Carpeta de trabajo
WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código
COPY . .

# Puerto (Render usa PORT de env, pero dejamos 5000 por defecto)
ENV PORT=5000

# Comando de arranque (Gunicorn en 0.0.0.0:PORT)
CMD ["bash", "-lc", "exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2 --threads 4"]
