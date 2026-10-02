"""Load demo data: python seed.py  (wipes the configured database first)."""
from datetime import timedelta

from app import create_app, services as svc
from app.db import ensure_indexes, get_client, get_db

USERS = [("Ada Lovelace", "ada@example.com"), ("Grace Hopper", "grace@example.com"), ("Alan Turing", "alan@example.com")]
BOOKS = [
    ("The Left Hand of Darkness", "Ursula K. Le Guin", "978-0441478125", "Science fiction", 2),
    ("Dune", "Frank Herbert", "978-0441172719", "Science fiction", 3),
    ("Beloved", "Toni Morrison", "978-1400033416", "Literary fiction", 1),
    ("Gödel, Escher, Bach", "Douglas Hofstadter", "978-0465026562", "Nonfiction", 1),
    ("The Name of the Rose", "Umberto Eco", "978-0156001311", "Mystery", 2),
]

app = create_app()
with app.app_context():
    get_client().drop_database(app.config["MONGO_DB"])
    db = get_db()
    ensure_indexes(db)
    users = [svc.create_user(db, {"name": n, "email": e}) for n, e in USERS]
    books = [svc.create_book(db, dict(zip(("title", "author", "isbn", "genre", "total_copies"), b))) for b in BOOKS]
    days = app.config["LOAN_DAYS"]
    late = svc.borrow(db, {"user_id": str(users[0]["_id"]), "book_id": str(books[2]["_id"])}, days)
    svc.borrow(db, {"user_id": str(users[1]["_id"]), "book_id": str(books[1]["_id"])}, days)
    svc.borrow(db, {"user_id": str(users[2]["_id"]), "book_id": str(books[3]["_id"])}, days)
    # make one loan overdue so the notification shows up
    db.transactions.update_one({"_id": late["_id"]}, {"$set": {"due_date": svc.now() - timedelta(days=4)}})
    print(f"Seeded {len(users)} patrons, {len(books)} books, 3 loans (1 overdue).")
