import json
import os
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import Flask, g, render_template
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

csrf = CSRFProtect()


def create_app(config=None):
    app = Flask(__name__)
    config_path = Path(os.environ.get("ENGLISHWORDS_CONFIG", ".local/settings.json"))
    local = json.loads(config_path.read_text()) if config_path.is_file() else {}
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", local.get("SECRET_KEY")),
        DATABASE_URL=os.environ.get("DATABASE_URL", local.get("DATABASE_URL", "")),
        ADMIN_PASSWORD_HASH=os.environ.get("ADMIN_PASSWORD_HASH", local.get("ADMIN_PASSWORD_HASH", "")),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        MAX_FORM_PARTS=12000,
        MAX_FORM_MEMORY_SIZE=4 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        WTF_CSRF_TIME_LIMIT=8 * 3600,
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"] or not app.config["ADMIN_PASSWORD_HASH"]:
        raise RuntimeError("请配置 SECRET_KEY 和 ADMIN_PASSWORD_HASH，或运行 scripts/dev_setup.py。")
    url = app.config["DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL 必须使用 postgresql+psycopg://。")
    engine = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2)
    app.extensions["engine"] = engine
    csrf.init_app(app)

    @app.template_filter('local_datetime')
    def local_datetime(value):
        return value.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')

    @app.before_request
    def open_session():
        g.db = Session(engine)

    @app.teardown_request
    def close_session(error):
        if "db" in g:
            g.db.rollback()
            g.db.close()

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; script-src 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    @app.errorhandler(503)
    def expected_error(error):
        return render_template("error.html", error=error), error.code

    @app.cli.command("migrate")
    def migrate():
        from alembic import command
        from alembic.config import Config
        cfg = Config("alembic.ini")
        cfg.attributes["engine"] = engine
        command.upgrade(cfg, "head")
        click.echo("数据库迁移完成。")

    @app.cli.command("password-hash")
    @click.password_option()
    def password_hash(password):
        click.echo(generate_password_hash(password))

    from .views import bp
    app.register_blueprint(bp)
    return app
