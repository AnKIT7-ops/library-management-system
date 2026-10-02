from flask import Blueprint, current_app, jsonify, request

from .. import services as svc
from ..db import get_db, to_json
from . import int_arg, json_body

bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")


@bp.get("")
def list_transactions():
    rows = svc.list_transactions(get_db(), request.args.get("status"),
                                 page=int_arg("page", 1), limit=int_arg("limit", 20))
    return jsonify([to_json(r) for r in rows])


@bp.post("")
def borrow():
    tx = svc.borrow(get_db(), json_body(), current_app.config["LOAN_DAYS"])
    return jsonify(to_json(tx)), 201


@bp.post("/<tx_id>/return")
def return_book(tx_id):
    return jsonify(to_json(svc.return_book(get_db(), svc.object_id(tx_id))))


@bp.get("/overdue")
def overdue():
    return jsonify([to_json(r) for r in svc.overdue(get_db())])
