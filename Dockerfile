# Imagen base
FROM python:3.11-slim

# Crear directorio
WORKDIR /app

# Copiar archivos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Puerto para Render
EXPOSE 5000

# Comando para iniciar
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
