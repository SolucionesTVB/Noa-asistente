# Imagen base de Python ligera
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY . .

# Exponer puerto (Render lo sobreescribe con $PORT)
EXPOSE 5000

# Comando de arranque
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
