from flask import Flask, jsonify
from flask_cors import CORS
import config

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY

    CORS(app, origins=config.ALLOWED_ORIGINS, supports_credentials=True)

    from routes.contas import bp as contas_bp
    from routes.repasses import bp as repasses_bp
    from routes.fornecedores import bp as fornecedores_bp
    from routes.dashboard import bp as dashboard_bp
    from routes.usuarios import bp as usuarios_bp

    app.register_blueprint(contas_bp, url_prefix="/api/contas")
    app.register_blueprint(repasses_bp, url_prefix="/api/repasses")
    app.register_blueprint(fornecedores_bp, url_prefix="/api/fornecedores")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(usuarios_bp, url_prefix="/api/usuarios")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    return app

if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
