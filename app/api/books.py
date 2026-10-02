from flask import Blueprint, jsonify, request

from .. import services as svc
from ..db import get_db, to_json
from . import int_arg, json_body

bp = Blueprint("books", __name__, url_prefix="/api/books")


@bp.get("")
def list_books():
    books = svc.search_books(get_db(), request.args.get("q"), int_arg("page", 1), int_arg("limit", 20))
    return jsonify([to_json(b) for b in books])


@bp.post("")
def create_book():
    return jsonify(to_json(svc.create_book(get_db(), json_body()))), 201


@bp.get("/<book_id>")
def get_book(book_id):
    return jsonify(to_json(svc.get_book(get_db(), svc.object_id(book_id))))


@bp.route("/<book_id>", methods=["PUT", "PATCH"])
def update_book(book_id):
    return jsonify(to_json(svc.update_book(get_db(), svc.object_id(book_id), json_body())))


@bp.delete("/<book_id>")
def delete_book(book_id):
    svc.delete_book(get_db(), svc.object_id(book_id))
    return "", 204
