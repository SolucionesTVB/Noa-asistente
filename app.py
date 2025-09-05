from flask import Flask

# Crear la aplicación
app = Flask(__name__)

# Ruta de prueba
@app.route('/')
def home():
    return "Noa Asistente está en línea 🚀"

# Punto de entrada
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
