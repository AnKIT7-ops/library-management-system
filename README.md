# Library Management System

A data-centric Flask + MongoDB web app for running a library's circulation desk. It has RESTful CRUD APIs for patrons, books and loans, indexed MongoDB queries, live search, and overdue notifications.

**Stack:** Python, Flask, MongoDB (PyMongo), HTML/CSS/vanilla JS

## Run it

```bash
docker compose up -d                 # MongoDB 7 on localhost:27017
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python seed.py                       # optional demo data (wipes the DB)
python run.py                        # http://127.0.0.1:5000
```

Tests (need the Docker Mongo running; they use a throwaway `library_test` DB):

```bash
pytest
```

Overdue reminders from the command line:

```bash
flask --app run notify-overdue
```

## Architecture

```
app/
  api/            HTTP layer: thin Flask blueprints (parse input, return JSON)
  services.py     business rules: validation, borrow/return, search, overdue
  db.py           Mongo client (one pooled client per process) + index definitions
  views.py        HTML pages (Catalog, Patrons, Loans)
  templates/ static/
```

Routes never touch Mongo directly, and services never touch Flask. Errors come back as `{"error": "..."}` with the right status code: 400 for invalid input, 404 for not found, 409 for conflicts.

## API

| Method | Path | Description |
|---|---|---|
| GET / POST | `/api/users` | List (`?page=&limit=`) / register a patron |
| GET / PUT / PATCH / DELETE | `/api/users/<id>` | Read / update / remove a patron (blocked while they hold loans) |
| GET | `/api/users/<id>/transactions` | A patron's loan history |
| GET / POST | `/api/books` | List or search (`?q=&page=&limit=`) / add a book |
| GET / PUT / PATCH / DELETE | `/api/books/<id>` | Read / update / remove a book (blocked while copies are on loan) |
| GET / POST | `/api/transactions` | List loans (`?status=active\|returned`) / check out `{user_id, book_id}` |
| POST | `/api/transactions/<id>/return` | Check a book back in |
| GET | `/api/transactions/overdue` | Overdue loans with patron and book names and days late |

## Data and query design

| Collection | Index | Serves |
|---|---|---|
| users | `email` unique | duplicate-registration guard |
| books | `isbn` unique | duplicate-book guard |
| books | text `title`×3, `author`×2, `genre`×1 | ranked full-text search |
| books | `keywords` (multikey) | search-as-you-type on word prefixes |
| books | `title` | sorted catalog listing |
| transactions | `(status, due_date)` | overdue scan (equality → range) |
| transactions | `(user_id, borrowed_at desc)` | patron history |
| transactions | `(book_id, status)` | "copies on loan?" check before delete |
| transactions | `(user_id, book_id)` unique where `status: "active"` | one active loan per patron per book, enforced by the DB |

- **Search** tries `$text` first, so whole words come back ranked by relevance. If that finds nothing, it falls back to anchored prefix regexes on a lowercased `keywords` array. For example, `le gu` finds *Ursula K. Le Guin*. Because the regexes are anchored and case-sensitive, Mongo uses tight index bounds: `explain()` shows `IXSCAN ["herb","herc")`, examining 1 document out of 3,000.
- **Check-out** decrements stock with one conditional `find_one_and_update` (`available_copies > 0`), so two people can't both take the last copy. If the loan insert then fails, the copy is put back.
- **Check-in** only matches `status: "active"`, so returning twice can't add a phantom copy.
- **Overdue notifications**: an aggregation with `$lookup` joins patron and book names. The UI shows a banner on every page, and a CLI command prints reminders.

## Not included (yet)
Auth, email delivery for reminders (the CLI command is the hook for it), and pagination on the overdue list (capped at 100).
