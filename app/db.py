from bson import ObjectId
from flask import current_app, g
from pymongo import ASCENDING, DESCENDING, TEXT, MongoClient

_client = None


def get_client():
    # One client per process: it owns the connection pool and is thread-safe.
    # Pool size is left at the driver default (maxPoolSize=100): assumes a single
    # Flask process with modest concurrency. Revisit if you run many workers.
    global _client
    if _client is None:
        _client = MongoClient(
            current_app.config["MONGO_URI"],
            serverSelectionTimeoutMS=5000,  # fail fast if Mongo isn't running instead of the 30s default
            tz_aware=True,  # return UTC-aware datetimes so comparisons with now(utc) work
        )
    return _client


def get_db():
    if "db" not in g:
        g.db = get_client()[current_app.config["MONGO_DB"]]
    return g.db


def ensure_indexes(db):
    db.users.create_index("email", unique=True)

    db.books.create_index("isbn", unique=True)
    db.books.create_index(
        [("title", TEXT), ("author", TEXT), ("genre", TEXT)],
        weights={"title": 3, "author": 2, "genre": 1},
        name="books_text",
    )
    db.books.create_index("keywords")  # multikey: word-prefix search-as-you-type
    db.books.create_index("title")     # catalog listing sort

    # Overdue scan: equality on status, range on due_date (ESR rule).
    db.transactions.create_index([("status", ASCENDING), ("due_date", ASCENDING)])
    db.transactions.create_index([("user_id", ASCENDING), ("borrowed_at", DESCENDING)])
    db.transactions.create_index([("book_id", ASCENDING), ("status", ASCENDING)])
    # DB-enforced rule: a user can hold at most one active loan of the same book.
    db.transactions.create_index(
        [("user_id", ASCENDING), ("book_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "active"},
        name="one_active_loan_per_book",
    )


def to_json(doc):
    """Convert ObjectIds/datetimes in a Mongo doc to JSON-safe values."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            v = str(v)
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        elif isinstance(v, dict):
            v = to_json(v)
        out["id" if k == "_id" else k] = v
    return out
