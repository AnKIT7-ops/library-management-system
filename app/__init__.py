import os

import click
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from . import services as svc
from .db import ensure_indexes, get_client, get_db


def create_app(overrides=None):
    load_dotenv()
    app = Flask(__name__)
    app.config.update(
        MONGO_URI=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        MONGO_DB=os.getenv("MONGO_DB", "library"),
        LOAN_DAYS=int(os.getenv("LOAN_DAYS", "14")),
    )
    app.config.update(overrides or {})

    from .api import books, transactions, users
    from . import views

    for module in (users, books, transactions, views):
        app.register_blueprint(module.bp)

    @app.errorhandler(svc.ServiceError)
    def service_error(e):
        return jsonify(error=e.message), e.status

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    @app.cli.command("notify-overdue")
    def notify_overdue():
        """Print a reminder for every overdue loan."""
        rows = svc.overdue(get_db())
        for r in rows:
            click.echo(f"Reminder to {r['user_name']} <{r['user_email']}>: "
                       f"'{r['book_title']}' is {r['days_overdue']} day(s) overdue.")
        click.echo(f"{len(rows)} overdue loan(s).")

    with app.app_context():
        ensure_indexes(get_client()[app.config["MONGO_DB"]])

    return app
