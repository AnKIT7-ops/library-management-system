from flask import Blueprint, render_template

bp = Blueprint("views", __name__)


@bp.get("/")
def books():
    return render_template("books.html", page="books")


@bp.get("/users")
def users():
    return render_template("users.html", page="users")


@bp.get("/transactions")
def transactions():
    return render_template("transactions.html", page="transactions")
