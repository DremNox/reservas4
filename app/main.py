from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    @app.get("/")
    def index():
        return jsonify(status="ok", message="Hola Reservas 4.0")

    @app.get("/healthz")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    return app

app = create_app()

if __name__ == "__main__":
    # Modo desarrollo (no se usará en producción porque arrancaremos con gunicorn)
    app.run(host="0.0.0.0", port=8080)
