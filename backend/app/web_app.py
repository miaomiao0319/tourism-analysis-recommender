import os
from pathlib import Path

import pymysql
from dotenv import dotenv_values
from flask import Flask, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .errors import AppError, STATUS
from .repositories.attractions import AttractionRepository
from .repositories.error_adapter import RepositoryAdapter
from .routes.recommendations import api, envelope
from .services.recommender import RecommendationError


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend/dist"


def database_connection(config):
    user = config.get("DB_USER")
    if not user or user.lower() == "root":
        raise AppError("DEPENDENCY_UNAVAILABLE", "请配置数据库只读账号。")
    options = dict(user=user, password=config.get("DB_PASSWORD") or "",
                   database=config["DB_NAME"], charset="utf8mb4", autocommit=True,
                   connect_timeout=4, read_timeout=15, init_command="SET time_zone = '+00:00'")
    if config.get("DB_UNIX_SOCKET"):
        options["unix_socket"] = config["DB_UNIX_SOCKET"]
    else:
        options.update(host=config["DB_HOST"], port=int(config["DB_PORT"]))
    return pymysql.connect(**options)


def create_app(config=None, repository=None):
    app = Flask(__name__, static_folder=None)
    defaults = {"DB_HOST": "127.0.0.1", "DB_PORT": "3306", "DB_NAME": "tourism_recommender",
                "DB_USER": "", "DB_PASSWORD": "", "DB_UNIX_SOCKET": "", "ACTIVE_BATCH_ID": "",
                "FLASK_HOST": "127.0.0.1", "FLASK_PORT": "5000"}
    local = dotenv_values(ROOT / ".env", interpolate=False)
    app.config.update({k: os.getenv(k, local.get(k, v)) for k, v in defaults.items()})
    app.config.update(config or {})
    app.json.ensure_ascii = False
    if repository is None:
        repository = AttractionRepository(lambda: database_connection(app.config))
    app.extensions["tourism_repository"] = RepositoryAdapter(
        repository, AppError, (pymysql.err.OperationalError, pymysql.err.InterfaceError))
    app.register_blueprint(api)

    @app.errorhandler(AppError)
    @app.errorhandler(RecommendationError)
    def controlled(error):
        return envelope(error={"code": error.code, "message": getattr(error, "message", str(error)), "details": error.details}), STATUS[error.code]

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path == "/api/v1" or request.path.startswith("/api/v1/"):
            choices = {404: ("NOT_FOUND", "接口不存在。"), 405: ("METHOD_NOT_ALLOWED", "请求方法不正确。")}
            code, msg = choices.get(error.code, ("INVALID_PARAMETER", "请求无效。"))
            response = envelope(error={"code": code, "message": msg, "details": {}})
            if error.code == 405:
                response.headers["Allow"] = error.get_response().headers.get("Allow", "")
            return response, error.code
        return error

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Website request failed")
        return envelope(error={"code": "INTERNAL_ERROR", "message": "服务暂时无法完成请求。", "details": {}}), 500

    @app.get("/")
    def index():
        return send_from_directory(DIST, "index.html")

    @app.get("/assets/<path:name>")
    def asset(name):
        return send_from_directory(DIST / "assets", name)

    return app
