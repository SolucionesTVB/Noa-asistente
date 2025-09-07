FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
# 1 worker + threads: estable si falta DB; PORT lo inyecta Render
ENV GUNICORN_CMD_ARGS="--workers 1 --threads 8 --timeout 120"
CMD ["gunicorn", "-b", "0.0.0.0:${PORT}", "app:app"]
