const $ = (sel) => document.querySelector(sel);

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  const msg = data.error || `Request failed (${res.status})`;
  if (!res.ok) throw new Error(msg[0].toUpperCase() + msg.slice(1));
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 3000);
}

// Run an action, toast its success message or its error.
async function act(fn, okMsg) {
  try {
    const out = await fn();
    if (okMsg) toast(okMsg);
    return out;
  } catch (e) {
    toast(e.message, true);
  }
}

function formData(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const [k, v] of Object.entries(data)) {
    if (v === "") delete data[k];
    else if (form.elements[k].type === "number") data[k] = Number(v);
  }
  return data;
}

function dueStamp(tx) {
  if (tx.status === "returned") return `<span class="stamp done">In ${fmtDate(tx.returned_at)}</span>`;
  const late = new Date(tx.due_date) < new Date();
  return `<span class="stamp${late ? " late" : ""}">Due ${fmtDate(tx.due_date)}</span>`;
}

async function refreshOverdueBar() {
  const rows = await api("GET", "/api/transactions/overdue").catch(() => []);
  const bar = $("#overdue-bar");
  bar.hidden = rows.length === 0;
  bar.textContent = `${rows.length} ${rows.length === 1 ? "loan is" : "loans are"} overdue. View loans`;
  return rows;
}

// ---------- catalog ----------

function initBooks() {
  const search = $("#book-search");
  const dialog = $("#checkout-dialog");
  let current = null;
  let seq = 0;

  async function load() {
    const mine = ++seq; // ignore responses that arrive after a newer search
    const q = search.value.trim();
    const books = await act(() => api("GET", `/api/books?limit=100&q=${encodeURIComponent(q)}`));
    if (!books || mine !== seq) return;
    $("#book-rows").innerHTML = books
      .map(
        (b) => `<tr>
          <td class="mono">${esc(b.isbn)}</td>
          <td class="title">${esc(b.title)}</td>
          <td>${esc(b.author)}</td>
          <td>${esc(b.genre)}</td>
          <td class="shelf${b.available_copies ? "" : " out"}">${b.available_copies} of ${b.total_copies}</td>
          <td><button data-id="${b.id}" data-title="${esc(b.title)}" ${b.available_copies ? "" : "disabled"}>Check out</button></td>
        </tr>`
      )
      .join("");
    const empty = $("#book-empty");
    empty.hidden = books.length > 0;
    empty.textContent = q ? `Nothing in the catalog matches “${q}”.` : "The catalog is empty. Add a book above.";
  }

  let timer;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(load, 200);
  });

  $("#book-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const book = await act(() => api("POST", "/api/books", formData(e.target)), "Added to catalog");
    if (book) {
      e.target.reset();
      load();
    }
  });

  $("#book-rows").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-id]");
    if (!btn) return;
    current = btn.dataset.id;
    $("#checkout-title").textContent = btn.dataset.title;
    const users = await act(() => api("GET", "/api/users?limit=100"));
    if (!users) return;
    if (!users.length) return toast("Register a patron before checking out books", true);
    $("#checkout-user").innerHTML = users.map((u) => `<option value="${u.id}">${esc(u.name)} · ${esc(u.email)}</option>`).join("");
    dialog.showModal();
  });

  // method="dialog" closes it; submit (not "close") fires synchronously with the clicked button.
  $("#checkout-form").addEventListener("submit", async (e) => {
    if (e.submitter?.value !== "confirm") return;
    const tx = await act(
      () => api("POST", "/api/transactions", { book_id: current, user_id: $("#checkout-user").value }),
      "Checked out"
    );
    if (tx) load();
  });

  load();
}

// ---------- patrons ----------

function initUsers() {
  async function load() {
    const users = await act(() => api("GET", "/api/users?limit=100"));
    if (!users) return;
    $("#user-rows").innerHTML = users
      .map(
        (u) => `<tr>
          <td class="title">${esc(u.name)}</td>
          <td>${esc(u.email)}</td>
          <td class="mono">${fmtDate(u.created_at)}</td>
          <td><button class="danger" data-id="${u.id}">Remove</button></td>
        </tr>`
      )
      .join("");
    $("#user-empty").hidden = users.length > 0;
  }

  $("#user-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const user = await act(() => api("POST", "/api/users", formData(e.target)), "Patron registered");
    if (user) {
      e.target.reset();
      load();
    }
  });

  // Two-step remove: first click arms the button, second click removes.
  $("#user-rows").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-id]");
    if (!btn) return;
    if (!btn.dataset.armed) {
      btn.dataset.armed = "1";
      btn.textContent = "Confirm remove";
      return;
    }
    const ok = await act(() => api("DELETE", `/api/users/${btn.dataset.id}`), "Patron removed");
    if (ok !== undefined) load();
    else {
      delete btn.dataset.armed;
      btn.textContent = "Remove";
    }
  });

  load();
}

// ---------- loans ----------

function initTransactions() {
  let status = "active";

  const row = (tx, cells) => `<tr>
    <td class="title">${esc(tx.book_title ?? "Deleted book")}</td>
    <td>${esc(tx.user_name ?? "Removed patron")}</td>
    ${cells}
    <td>${tx.status === "active" ? `<button data-id="${tx.id}">Check in</button>` : ""}</td>
  </tr>`;

  async function load() {
    const [loans, overdue] = await Promise.all([
      act(() => api("GET", `/api/transactions?limit=100&status=${status}`)),
      refreshOverdueBar(),
    ]);
    $("#overdue").hidden = overdue.length === 0;
    $("#overdue-rows").innerHTML = overdue
      .map((tx) => row(tx, `<td>${dueStamp(tx)}</td><td class="mono">${tx.days_overdue} day${tx.days_overdue === 1 ? "" : "s"}</td>`))
      .join("");
    if (!loans) return;
    $("#loan-rows").innerHTML = loans
      .map((tx) => row(tx, `<td class="mono">${fmtDate(tx.borrowed_at)}</td><td>${dueStamp(tx)}</td>`))
      .join("");
    $("#loan-empty").hidden = loans.length > 0;
  }

  document.querySelectorAll(".tabs button").forEach((b) =>
    b.addEventListener("click", () => {
      status = b.dataset.status;
      document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      load();
    })
  );

  document.querySelector("main").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-id]");
    if (!btn) return;
    btn.disabled = true;
    const tx = await act(() => api("POST", `/api/transactions/${btn.dataset.id}/return`), "Checked in");
    if (tx) load();
    else btn.disabled = false;
  });

  load();
}

const page = document.body.dataset.page;
({ books: initBooks, users: initUsers, transactions: initTransactions })[page]?.();
if (page !== "transactions") refreshOverdueBar();
