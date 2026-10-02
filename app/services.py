"""Business logic. Routes call these; these talk to Mongo. No Flask request objects in here."""
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from bson.regex import Regex
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

MAX_PAGE_SIZE = 100


class ServiceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now():
    return datetime.now(timezone.utc)


# ---------- validation ----------

def _str(data, field, required):
    value = data.get(field)
    if value is None:
        if required:
            raise ServiceError(400, f"'{field}' is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(400, f"'{field}' must be a non-empty string")
    return value.strip()


def _pos_int(data, field, required):
    value = data.get(field)
    if value is None:
        if required:
            raise ServiceError(400, f"'{field}' is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ServiceError(400, f"'{field}' must be a positive integer")
    return value


def object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise ServiceError(404, "not found")


def _clean(fields):
    return {k: v for k, v in fields.items() if v is not None}


def _get_or_404(coll, _id, label):
    doc = coll.find_one({"_id": _id})
    if doc is None:
        raise ServiceError(404, f"{label} not found")
    return doc


def page_args(page, limit):
    page = max(page or 1, 1)
    limit = min(max(limit or 20, 1), MAX_PAGE_SIZE)
    return (page - 1) * limit, limit


# ---------- users ----------

def user_fields(data, partial=False):
    fields = _clean({"name": _str(data, "name", not partial), "email": _str(data, "email", not partial)})
    if "email" in fields:
        fields["email"] = fields["email"].lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]):
            raise ServiceError(400, "'email' is not valid")
    return fields


def create_user(db, data):
    doc = {**user_fields(data), "created_at": now()}
    try:
        doc["_id"] = db.users.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise ServiceError(409, "email already registered")
    return doc


def list_users(db, page=1, limit=20):
    skip, limit = page_args(page, limit)
    return list(db.users.find().sort("name", 1).skip(skip).limit(limit))


def get_user(db, user_id):
    return _get_or_404(db.users, user_id, "user")


def update_user(db, user_id, data):
    fields = user_fields(data, partial=True)
    if not fields:
        raise ServiceError(400, "nothing to update")
    try:
        doc = db.users.find_one_and_update(
            {"_id": user_id}, {"$set": fields}, return_document=ReturnDocument.AFTER
        )
    except DuplicateKeyError:
        raise ServiceError(409, "email already registered")
    if doc is None:
        raise ServiceError(404, "user not found")
    return doc


def delete_user(db, user_id):
    if db.transactions.find_one({"user_id": user_id, "status": "active"}, {"_id": 1}):
        raise ServiceError(409, "user still has books on loan")
    if db.users.delete_one({"_id": user_id}).deleted_count == 0:
        raise ServiceError(404, "user not found")


# ---------- books ----------

def book_fields(data, partial=False):
    req = not partial
    fields = _clean({
        "title": _str(data, "title", req),
        "author": _str(data, "author", req),
        "isbn": _str(data, "isbn", req),
        "genre": _str(data, "genre", False),
        "total_copies": _pos_int(data, "total_copies", req),
    })
    return fields


def _words(text):
    return re.findall(r"\w+", text.lower())


def keywords(book):
    """Lowercased words of title/author/genre, multikey-indexed for search-as-you-type."""
    return sorted(set(_words(" ".join(book.get(f) or "" for f in ("title", "author", "genre")))))


def create_book(db, data):
    doc = book_fields(data)
    doc["available_copies"] = doc["total_copies"]
    doc["keywords"] = keywords(doc)
    try:
        doc["_id"] = db.books.insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise ServiceError(409, "a book with this ISBN already exists")
    return doc


def get_book(db, book_id):
    return _get_or_404(db.books, book_id, "book")


def update_book(db, book_id, data):
    fields = book_fields(data, partial=True)
    if not fields:
        raise ServiceError(400, "nothing to update")
    query = {"_id": book_id}
    update = {}
    total = fields.pop("total_copies", None)
    current = None
    if total is not None or fields.keys() & {"title", "author", "genre"}:
        current = get_book(db, book_id)
    if fields.keys() & {"title", "author", "genre"}:
        fields["keywords"] = keywords({**current, **fields})
    if total is not None:
        delta = total - current["total_copies"]
        # Shift available by the same delta; refuse if that would drop below zero (copies on loan).
        query["total_copies"] = current["total_copies"]
        query["available_copies"] = {"$gte": -delta}
        update["$inc"] = {"total_copies": delta, "available_copies": delta}
    if fields:
        update["$set"] = fields
    try:
        doc = db.books.find_one_and_update(query, update, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        raise ServiceError(409, "a book with this ISBN already exists")
    if doc is None:
        get_book(db, book_id)  # 404 if it doesn't exist
        raise ServiceError(409, "cannot reduce copies below the number currently on loan")
    return doc


def delete_book(db, book_id):
    if db.transactions.find_one({"book_id": book_id, "status": "active"}, {"_id": 1}):
        raise ServiceError(409, "book has copies on loan")
    if db.books.delete_one({"_id": book_id}).deleted_count == 0:
        raise ServiceError(404, "book not found")


BOOK_LIST_FIELDS = {"keywords": 0}


def search_books(db, q=None, page=1, limit=20):
    """Full-text search on title/author/genre, ranked by relevance.
    Falls back to word-prefix matching so partial words ("le gu") still hit while typing."""
    skip, limit = page_args(page, limit)
    q = (q or "").strip()
    if not q:
        return list(db.books.find({}, BOOK_LIST_FIELDS).sort("title", 1).skip(skip).limit(limit))

    text_hits = list(
        db.books.find({"$text": {"$search": q}}, {**BOOK_LIST_FIELDS, "score": {"$meta": "textScore"}})
        .sort([("score", {"$meta": "textScore"})])
        .skip(skip)
        .limit(limit)
    )
    if text_hits:
        for b in text_hits:
            b.pop("score", None)
        return text_hits
    terms = _words(q)
    if not terms:
        return []
    # Anchored, case-sensitive regexes on a lowercased multikey field -> tight index bounds.
    prefixes = {"keywords": {"$all": [Regex("^" + re.escape(t)) for t in terms]}}
    return list(db.books.find(prefixes, BOOK_LIST_FIELDS).sort("title", 1).skip(skip).limit(limit))


# ---------- transactions ----------

def borrow(db, data, loan_days):
    user_id = object_id(_str(data, "user_id", True))
    book_id = object_id(_str(data, "book_id", True))
    get_user(db, user_id)

    # Atomic: only decrements if a copy is available, so two borrowers can't take the last one.
    book = db.books.find_one_and_update(
        {"_id": book_id, "available_copies": {"$gt": 0}},
        {"$inc": {"available_copies": -1}},
        return_document=ReturnDocument.AFTER,
    )
    if book is None:
        get_book(db, book_id)
        raise ServiceError(409, "no copies available")

    borrowed = now()
    tx = {
        "user_id": user_id,
        "book_id": book_id,
        "borrowed_at": borrowed,
        "due_date": borrowed + timedelta(days=loan_days),
        "returned_at": None,
        "status": "active",
    }
    try:
        tx["_id"] = db.transactions.insert_one(tx).inserted_id
    except DuplicateKeyError:
        db.books.update_one({"_id": book_id}, {"$inc": {"available_copies": 1}})  # give the copy back
        raise ServiceError(409, "user already has this book on loan")
    return tx


def return_book(db, tx_id):
    tx = db.transactions.find_one_and_update(
        {"_id": tx_id, "status": "active"},
        {"$set": {"status": "returned", "returned_at": now()}},
        return_document=ReturnDocument.AFTER,
    )
    if tx is None:
        _get_or_404(db.transactions, tx_id, "transaction")
        raise ServiceError(409, "already returned")
    db.books.update_one({"_id": tx["book_id"]}, {"$inc": {"available_copies": 1}})
    return tx


def _with_names(match, sort, skip=0, limit=MAX_PAGE_SIZE):
    """Aggregation that joins user/book names onto transactions."""
    return [
        {"$match": match},
        {"$sort": sort},
        {"$skip": skip},
        {"$limit": limit},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$lookup": {"from": "books", "localField": "book_id", "foreignField": "_id", "as": "book",
                     "pipeline": [{"$project": {"title": 1}}]}},
        {"$set": {
            "user_name": {"$first": "$user.name"},
            "user_email": {"$first": "$user.email"},
            "book_title": {"$first": "$book.title"},
        }},
        {"$unset": ["user", "book"]},
    ]


def list_transactions(db, status=None, user_id=None, page=1, limit=20):
    match = {}
    if status in ("active", "returned"):
        match["status"] = status
    elif status:
        raise ServiceError(400, "status must be 'active' or 'returned'")
    if user_id is not None:
        match["user_id"] = user_id
    skip, limit = page_args(page, limit)
    return list(db.transactions.aggregate(_with_names(match, {"borrowed_at": -1}, skip, limit)))


def overdue(db):
    # ponytail: capped at MAX_PAGE_SIZE rows; paginate if a library ever has more overdue loans.
    match = {"status": "active", "due_date": {"$lt": now()}}
    rows = list(db.transactions.aggregate(_with_names(match, {"due_date": 1})))
    t = now()
    for r in rows:
        r["days_overdue"] = (t - r["due_date"]).days
    return rows
