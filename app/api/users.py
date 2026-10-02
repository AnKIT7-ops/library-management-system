from flask import Blueprint, jsonify

from .. import services as svc
from ..db import get_db, to_json
from . import int_arg, json_body

bp = Blueprint("users", __name__, url_prefix="/api/users")


@bp.get("")
def list_users():
    users = svc.list_users(get_db(), int_arg("page", 1), int_arg("limit", 20))
    return jsonify([to_json(u) for u in users])


@bp.post("")
def create_user():
    return jsonify(to_json(svc.create_user(get_db(), json_body()))), 201


@bp.get("/<user_id>")
def get_user(user_id):
    return jsonify(to_json(svc.get_user(get_db(), svc.object_id(user_id))))


@bp.route("/<user_id>", methods=["PUT", "PATCH"])
def update_user(user_id):
    return jsonify(to_json(svc.update_user(get_db(), svc.object_id(user_id), json_body())))


@bp.delete("/<user_id>")
def delete_user(user_id):
    svc.delete_user(get_db(), svc.object_id(user_id))
    return "", 204


@bp.get("/<user_id>/transactions")
def user_transactions(user_id):
    rows = svc.list_transactions(get_db(), user_id=svc.object_id(user_id),
                                 page=int_arg("page", 1), limit=int_arg("limit", 20))
    return jsonify([to_json(r) for r in rows])
