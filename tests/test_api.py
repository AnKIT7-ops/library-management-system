"""Runs against the Docker Mongo using a throwaway database (dropped before and after each test)."""
from datetime import timedelta

import pytest

from app import create_app
from app.db import get_client
from app.services import now

TEST_DB = "library_test"


@pytest.fixture
def client():
    app = create_app({"MONGO_DB": TEST_DB, "TESTING": True})
    with app.app_context():
        mongo = get_client()
        mongo.drop_database(TEST_DB)
        from app.db import ensure_indexes
        ensure_indexes(mongo[TEST_DB])
        yield app.test_client()
        mongo.drop_database(TEST_DB)


def make_user(c, email="ada@example.com", name="Ada Lovelace"):
    r = c.post("/api/users", json={"name": name, "email": email})
    assert r.status_code == 201, r.json
    return r.json


def make_book(c, isbn="978-0", copies=1, title="The Left Hand of Darkness", author="Ursula Le Guin"):
    r = c.post("/api/books", json={"title": title, "author": author, "isbn": isbn,
                                   "genre": "science fiction", "total_copies": copies})
    assert r.status_code == 201, r.json
    return r.json


def test_user_crud_and_duplicate_email(client):
    u = make_user(client)
    assert client.get(f"/api/users/{u['id']}").json["email"] == "ada@example.com"
    assert client.patch(f"/api/users/{u['id']}", json={"name": "Ada K."}).json["name"] == "Ada K."
    assert client.post("/api/users", json={"name": "X", "email": "ADA@example.com"}).status_code == 409
    assert client.post("/api/users", json={"name": "X", "email": "nope"}).status_code == 400
    assert client.delete(f"/api/users/{u['id']}").status_code == 204
    assert client.get(f"/api/users/{u['id']}").status_code == 404
    assert client.get("/api/users/not-an-id").status_code == 404


def test_book_crud_and_validation(client):
    b = make_book(client, copies=2)
    assert b["available_copies"] == 2
    assert client.post("/api/books", json={"title": "T", "author": "A", "isbn": "978-0", "total_copies": 1}).status_code == 409
    assert client.post("/api/books", json={"title": "T", "author": "A", "isbn": "1", "total_copies": 0}).status_code == 400
    assert client.post("/api/books", json={"title": "T", "author": "A", "isbn": "1", "total_copies": True}).status_code == 400
    client.patch(f"/api/books/{b['id']}", json={"author": "Octavia Butler"})
    assert [x["title"] for x in client.get("/api/books?q=octav").json] == [b["title"]]  # keywords rebuilt on edit
    r = client.put(f"/api/books/{b['id']}", json={"total_copies": 5})
    assert (r.json["total_copies"], r.json["available_copies"]) == (5, 5)
    assert client.delete(f"/api/books/{b['id']}").status_code == 204


def test_borrow_last_copy_then_return(client):
    u1, u2 = make_user(client), make_user(client, "grace@example.com", "Grace Hopper")
    b = make_book(client, copies=1)

    tx = client.post("/api/transactions", json={"user_id": u1["id"], "book_id": b["id"]})
    assert tx.status_code == 201
    assert client.get(f"/api/books/{b['id']}").json["available_copies"] == 0

    # last copy is gone
    assert client.post("/api/transactions", json={"user_id": u2["id"], "book_id": b["id"]}).status_code == 409
    # can't delete a book/user with active loans
    assert client.delete(f"/api/books/{b['id']}").status_code == 409
    assert client.delete(f"/api/users/{u1['id']}").status_code == 409

    tx_id = tx.json["id"]
    assert client.post(f"/api/transactions/{tx_id}/return").status_code == 200
    assert client.get(f"/api/books/{b['id']}").json["available_copies"] == 1
    # returning twice does not add a phantom copy
    assert client.post(f"/api/transactions/{tx_id}/return").status_code == 409
    assert client.get(f"/api/books/{b['id']}").json["available_copies"] == 1


def test_same_user_cannot_hold_two_copies(client):
    u = make_user(client)
    b = make_book(client, copies=3)
    assert client.post("/api/transactions", json={"user_id": u["id"], "book_id": b["id"]}).status_code == 201
    assert client.post("/api/transactions", json={"user_id": u["id"], "book_id": b["id"]}).status_code == 409
    # the rejected borrow gave its copy back
    assert client.get(f"/api/books/{b['id']}").json["available_copies"] == 2
    # can't shrink stock below what's on loan
    u2 = make_user(client, "grace@example.com", "Grace Hopper")
    client.post("/api/transactions", json={"user_id": u2["id"], "book_id": b["id"]})
    assert client.patch(f"/api/books/{b['id']}", json={"total_copies": 1}).status_code == 409
    r = client.patch(f"/api/books/{b['id']}", json={"total_copies": 2})
    assert (r.json["total_copies"], r.json["available_copies"]) == (2, 0)


def test_search_full_text_and_prefix(client):
    make_book(client, "1", title="The Left Hand of Darkness", author="Ursula Le Guin")
    make_book(client, "2", title="Dune", author="Frank Herbert")
    titles = lambda q: [b["title"] for b in client.get(f"/api/books?q={q}").json]
    assert titles("guin") == ["The Left Hand of Darkness"]   # author word via $text
    assert titles("Du") == ["Dune"]                          # partial word via prefix fallback
    assert titles("le gu") == ["The Left Hand of Darkness"]  # prefixes of several words, any field
    assert titles("frank") == ["Dune"]
    assert titles("zzz") == []
    assert len(client.get("/api/books").json) == 2


def test_overdue(client):
    u = make_user(client)
    b = make_book(client, copies=2)
    tx = client.post("/api/transactions", json={"user_id": u["id"], "book_id": b["id"]}).json
    assert client.get("/api/transactions/overdue").json == []

    from bson import ObjectId
    from app.db import get_db
    get_db().transactions.update_one({"_id": ObjectId(tx["id"])}, {"$set": {"due_date": now() - timedelta(days=3)}})

    rows = client.get("/api/transactions/overdue").json
    assert len(rows) == 1
    assert rows[0]["user_name"] == "Ada Lovelace" and rows[0]["days_overdue"] == 3
    assert client.get("/api/transactions?status=active").json[0]["book_title"] == b["title"]
