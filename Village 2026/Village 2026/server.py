#!/usr/bin/env python3
import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import smtplib
import sqlite3
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "registrations.sqlite3"
MAIL_LOG = DATA_DIR / "mail.log"
MAX_BODY = 35 * 1024 * 1024
MAX_PHOTOS = 8
SESSION_COOKIE = "village_admin_session"

ADMIN_USER = os.environ.get("ADMIN_USER", "VillageAdmin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Village2026!?")
FROM_EMAIL = os.environ.get("SMTP_FROM", "Village Car Event <noreply@villagecarevent.com>")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_storage():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            create table if not exists registrations (
                id integer primary key autoincrement,
                token text not null unique,
                status text not null default 'pending',
                owner_name text not null,
                email text not null,
                phone text,
                car_make text not null,
                car_model text not null,
                car_year text,
                plate text,
                instagram text,
                description text not null,
                admin_note text,
                created_at text not null,
                reviewed_at text
            )
            """
        )
        db.execute(
            """
            create table if not exists photos (
                id integer primary key autoincrement,
                registration_id integer not null,
                filename text not null,
                original_name text not null,
                content_type text not null,
                created_at text not null,
                foreign key (registration_id) references registrations(id)
            )
            """
        )
        db.execute(
            """
            create table if not exists sessions (
                token text primary key,
                created_at text not null
            )
            """
        )


def db_connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def safe_next_path(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/admin"
    if value.startswith("/admin") or value.startswith("/uploads/"):
        return value
    return "/admin"


def create_admin_session():
    token = secrets.token_urlsafe(32)
    with db_connect() as db:
        db.execute("insert into sessions (token, created_at) values (?, ?)", (token, now_iso()))
    return token


def is_valid_admin_session(token):
    with db_connect() as db:
        row = db.execute("select token from sessions where token = ?", (token,)).fetchone()
    return row is not None


def delete_admin_session(token):
    with db_connect() as db:
        db.execute("delete from sessions where token = ?", (token,))


def session_cookie_header(token):
    return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax"


def expired_session_cookie_header():
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def e(value):
    return html.escape(str(value or ""), quote=True)


def site_shell(title, body, extra_class="admin-page"):
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{e(title)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&family=Oswald:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/style.css">
  </head>
  <body class="{extra_class}">
    {body}
  </body>
</html>"""


def registration_form(message=""):
    notice = f'<div class="form-notice">{e(message)}</div>' if message else ""
    return site_shell(
        "Register your car - Village 2026",
        f"""
<main class="form-page">
  <section class="form-hero">
    <img class="logo" src="https://villagecarevent.com/images/village/village_logo_2017.png" alt="Village Car Event">
    <h1>Register your car</h1>
    <p>Village Car Event - September 6th 2026</p>
  </section>
  <section class="form-wrap">
    {notice}
    <form class="registration-form" action="/register" method="post" enctype="multipart/form-data">
      <div class="field-grid">
        <label>Full name <input name="owner_name" required autocomplete="name"></label>
        <label>Email <input type="email" name="email" required autocomplete="email"></label>
        <label>Phone <input name="phone" autocomplete="tel"></label>
        <label>Instagram <input name="instagram" placeholder="@username"></label>
        <label>Car make <input name="car_make" required placeholder="BMW"></label>
        <label>Car model <input name="car_model" required placeholder="E36"></label>
        <label>Year <input name="car_year" inputmode="numeric" placeholder="1998"></label>
        <label>Number plate <input name="plate"></label>
      </div>
      <label>Tell us about the car
        <textarea name="description" required rows="8" placeholder="Build details, wheels, suspension, interior, paint, special work..."></textarea>
      </label>
      <label>Photos
        <input type="file" name="photos" accept="image/*" multiple required>
      </label>
      <p class="form-help">Upload up to {MAX_PHOTOS} photos. Your registration will be reviewed before it appears on the website.</p>
      <button class="button button-primary" type="submit">Send registration <span class="button-icon">›</span></button>
      <a class="back-link" href="/">Back to event page</a>
    </form>
  </section>
</main>""",
        "register-page",
    )


def success_page():
    return site_shell(
        "Registration received - Village 2026",
        """
<main class="form-page">
  <section class="form-hero">
    <img class="logo" src="https://villagecarevent.com/images/village/village_logo_2017.png" alt="Village Car Event">
    <h1>Registration received</h1>
    <p>Thanks, we will review your car and send you an email when a decision has been made.</p>
    <a class="button button-success" href="/">Back to event page <span class="button-icon">›</span></a>
  </section>
</main>""",
        "register-page",
    )


def login_page(message="", next_path="/admin"):
    notice = f'<div class="form-notice">{e(message)}</div>' if message else ""
    return site_shell(
        "Admin login - Village 2026",
        f"""
<main class="form-page login-page">
  <section class="form-hero login-hero">
    <img class="logo" src="https://villagecarevent.com/images/village/village_logo_2017.png" alt="Village Car Event">
    <h1>Admin login</h1>
    <p>Village Car Event registrations</p>
  </section>
  <section class="form-wrap login-wrap">
    {notice}
    <form class="registration-form login-form" action="/admin/login" method="post">
      <input type="hidden" name="next" value="{e(next_path)}">
      <label>Username <input name="username" required autocomplete="username"></label>
      <label>Password <input type="password" name="password" required autocomplete="current-password"></label>
      <button class="button button-primary" type="submit">Log in <span class="button-icon">›</span></button>
      <a class="back-link" href="/">Back to event page</a>
    </form>
  </section>
</main>""",
        "register-page",
    )


def parse_multipart(headers, body):
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Expected multipart form data.")
    parser = BytesParser(policy=default)
    message = parser.parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body)
    fields = {}
    files = []
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            if payload:
                files.append(
                    {
                        "name": name,
                        "filename": filename,
                        "content_type": part.get_content_type(),
                        "data": payload,
                    }
                )
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace").strip()
    return fields, files


def safe_extension(filename, content_type):
    ext = Path(filename).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    if ext in allowed:
        return ext
    guessed = mimetypes.guess_extension(content_type or "")
    return guessed if guessed in allowed else ".jpg"


def create_registration(fields, files):
    required = ["owner_name", "email", "car_make", "car_model", "description"]
    missing = [key for key in required if not fields.get(key)]
    if missing:
        raise ValueError("Please fill in all required fields.")
    image_files = [item for item in files if item["name"] == "photos" and item["content_type"].startswith("image/")]
    if not image_files:
        raise ValueError("Please upload at least one photo.")
    if len(image_files) > MAX_PHOTOS:
        raise ValueError(f"Please upload no more than {MAX_PHOTOS} photos.")

    token = secrets.token_urlsafe(16)
    with db_connect() as db:
        cursor = db.execute(
            """
            insert into registrations (
                token, owner_name, email, phone, car_make, car_model, car_year,
                plate, instagram, description, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                fields["owner_name"],
                fields["email"],
                fields.get("phone", ""),
                fields["car_make"],
                fields["car_model"],
                fields.get("car_year", ""),
                fields.get("plate", ""),
                fields.get("instagram", ""),
                fields["description"],
                now_iso(),
            ),
        )
        registration_id = cursor.lastrowid
        target_dir = UPLOAD_DIR / str(registration_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(image_files, start=1):
            ext = safe_extension(item["filename"], item["content_type"])
            filename = f"{index:02d}-{secrets.token_hex(8)}{ext}"
            path = target_dir / filename
            path.write_bytes(item["data"])
            db.execute(
                "insert into photos (registration_id, filename, original_name, content_type, created_at) values (?, ?, ?, ?, ?)",
                (registration_id, filename, item["filename"], item["content_type"], now_iso()),
            )
    return registration_id


def registration_rows(status=None):
    sql = "select * from registrations"
    params = []
    if status:
        sql += " where status = ?"
        params.append(status)
    sql += " order by created_at desc"
    with db_connect() as db:
        rows = [dict(row) for row in db.execute(sql, params).fetchall()]
        for row in rows:
            row["photos"] = [dict(photo) for photo in db.execute("select * from photos where registration_id = ? order by id", (row["id"],)).fetchall()]
    return rows


def render_admin():
    rows = registration_rows()
    cards = []
    for row in rows:
        photos = "".join(
            f'<a href="/uploads/{row["id"]}/{e(photo["filename"])}" target="_blank"><img src="/uploads/{row["id"]}/{e(photo["filename"])}" alt=""></a>'
            for photo in row["photos"]
        )
        status_class = f'status-{e(row["status"])}'
        cards.append(
            f"""
<article class="admin-card">
  <div class="admin-card-head">
    <div>
      <span class="status-pill {status_class}">{e(row["status"])}</span>
      <h2>{e(row["car_year"])} {e(row["car_make"])} {e(row["car_model"])}</h2>
      <p>{e(row["owner_name"])} - <a href="mailto:{e(row["email"])}">{e(row["email"])}</a></p>
    </div>
    <time>{e(row["created_at"])}</time>
  </div>
  <dl class="admin-details">
    <div><dt>Phone</dt><dd>{e(row["phone"])}</dd></div>
    <div><dt>Plate</dt><dd>{e(row["plate"])}</dd></div>
    <div><dt>Instagram</dt><dd>{e(row["instagram"])}</dd></div>
  </dl>
  <p class="admin-description">{e(row["description"])}</p>
  <div class="admin-photos">{photos}</div>
  <form class="review-form" method="post" action="/admin/registrations/{row["id"]}/accept">
    <textarea name="admin_note" rows="3" placeholder="Optional message for the email">{e(row["admin_note"])}</textarea>
    <button class="button button-success button-small" type="submit">Accept</button>
  </form>
  <form class="review-form" method="post" action="/admin/registrations/{row["id"]}/reject">
    <textarea name="admin_note" rows="3" placeholder="Reason or message for the email">{e(row["admin_note"])}</textarea>
    <button class="button button-primary button-small" type="submit">Reject</button>
  </form>
</article>"""
        )
    content = "".join(cards) or '<p class="admin-empty">No registrations yet.</p>'
    return site_shell(
        "Admin - Village 2026",
        f"""
<main class="admin-shell">
  <header class="admin-top">
    <div>
      <h1>Village registrations</h1>
      <p>Review submitted cars, photos and owner notes.</p>
    </div>
    <div class="admin-actions">
      <a class="button button-success button-small" href="/">Open website</a>
      <form method="post" action="/admin/logout">
        <button class="button button-primary button-small" type="submit">Log out</button>
      </form>
    </div>
  </header>
  {content}
</main>""",
    )


def accepted_api():
    rows = registration_rows("accepted")
    data = []
    for row in rows:
        first_photo = row["photos"][0] if row["photos"] else None
        data.append(
            {
                "id": row["id"],
                "car_make": row["car_make"],
                "car_model": row["car_model"],
                "car_year": row["car_year"],
                "photo_url": f'/uploads/{row["id"]}/{first_photo["filename"]}' if first_photo else "",
            }
        )
    return {"count": len(rows), "registrations": data}


def send_decision_email(row, decision, note):
    accepted = decision == "accepted"
    subject = "Village 2026 registration accepted" if accepted else "Village 2026 registration update"
    intro = (
        "Good news, your car has been accepted for Village 2026."
        if accepted
        else "Thank you for registering your car. Unfortunately, your car has not been accepted for Village 2026."
    )
    body = f"""Hi {row['owner_name']},

{intro}

Car: {row['car_year']} {row['car_make']} {row['car_model']}
Event date: September 6th 2026

{note or ''}

Kind regards,
Village Car Event
"""
    host = os.environ.get("SMTP_HOST")
    if not host:
        DATA_DIR.mkdir(exist_ok=True)
        with MAIL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n--- {now_iso()} ---\nTo: {row['email']}\nSubject: {subject}\n{body}\n")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = FROM_EMAIL
    message["To"] = row["email"]
    message.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    use_tls = os.environ.get("SMTP_TLS", "1") != "0"
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls(context=ssl.create_default_context())
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


class Handler(BaseHTTPRequestHandler):
    server_version = "VillageServer/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self.serve_file(ROOT / "index.html", "text/html; charset=utf-8")
        if path == "/healthz":
            return self.send_json({"ok": True})
        if path == "/register":
            return self.send_html(registration_form())
        if path == "/register/success":
            return self.send_html(success_page())
        if path == "/admin/login":
            query = parse_qs(parsed.query)
            next_path = safe_next_path(query.get("next", ["/admin"])[0])
            return self.send_html(login_page(next_path=next_path))
        if path == "/admin":
            if not self.require_admin():
                return
            return self.send_html(render_admin())
        if path == "/api/registrations":
            return self.send_json(accepted_api())
        if path.startswith("/uploads/"):
            return self.serve_upload(path)
        if path in {"/style.css", "/script.js"}:
            return self.serve_file(ROOT / path.lstrip("/"))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/register":
            return self.handle_register()
        if path == "/admin/login":
            return self.handle_login()
        if path == "/admin/logout":
            return self.handle_logout()
        match = re.fullmatch(r"/admin/registrations/(\d+)/(accept|reject)", path)
        if match:
            if not self.require_admin():
                return
            return self.handle_review(int(match.group(1)), match.group(2))
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_register(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                raise ValueError("The upload is too large.")
            body = self.rfile.read(length)
            fields, files = parse_multipart(self.headers, body)
            create_registration(fields, files)
            self.redirect("/register/success")
        except ValueError as exc:
            self.send_html(registration_form(str(exc)), HTTPStatus.BAD_REQUEST)

    def handle_review(self, registration_id, action):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        note = parse_qs(body).get("admin_note", [""])[0].strip()
        status = "accepted" if action == "accept" else "rejected"
        with db_connect() as db:
            row = db.execute("select * from registrations where id = ?", (registration_id,)).fetchone()
            if not row:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            db.execute(
                "update registrations set status = ?, admin_note = ?, reviewed_at = ? where id = ?",
                (status, note, now_iso(), registration_id),
            )
            row = dict(db.execute("select * from registrations where id = ?", (registration_id,)).fetchone())
        send_decision_email(row, status, note)
        self.redirect("/admin")

    def handle_login(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        fields = parse_qs(body)
        username = fields.get("username", [""])[0]
        password = fields.get("password", [""])[0]
        next_path = safe_next_path(fields.get("next", ["/admin"])[0])
        if secrets.compare_digest(username, ADMIN_USER) and secrets.compare_digest(password, ADMIN_PASSWORD):
            token = create_admin_session()
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", next_path)
            self.send_header("Set-Cookie", session_cookie_header(token))
            self.end_headers()
            return
        self.send_html(login_page("Wrong username or password.", next_path), HTTPStatus.UNAUTHORIZED)

    def handle_logout(self):
        token = self.session_token()
        if token:
            delete_admin_session(token)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/admin/login")
        self.send_header("Set-Cookie", expired_session_cookie_header())
        self.end_headers()

    def serve_upload(self, path):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 3:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, registration_id, filename = parts
        if not registration_id.isdigit() or "/" in filename or filename.startswith("."):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with db_connect() as db:
            row = db.execute(
                """
                select registrations.status, photos.content_type
                from photos join registrations on registrations.id = photos.registration_id
                where photos.registration_id = ? and photos.filename = ?
                """,
                (int(registration_id), filename),
            ).fetchone()
        if not row:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if row["status"] != "accepted" and not self.is_admin_authorized():
            if not self.require_admin():
                return
        self.serve_file(UPLOAD_DIR / registration_id / filename, row["content_type"])

    def serve_file(self, path, content_type=None):
        resolved = path.resolve()
        if not str(resolved).startswith(str(ROOT)) or not resolved.exists() or not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = content_type or mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(resolved.stat().st_size))
        self.end_headers()
        with resolved.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def send_html(self, content, status=HTTPStatus.OK):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, location):
        if location == "/register/success":
            self.send_html(success_page())
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def session_token(self):
        cookie_header = self.headers.get("Cookie", "")
        cookies = {}
        for item in cookie_header.split(";"):
            key, _, value = item.strip().partition("=")
            if key:
                cookies[key] = value
        return cookies.get(SESSION_COOKIE)

    def is_admin_authorized(self):
        token = self.session_token()
        if not token:
            return False
        return is_valid_admin_session(token)

    def require_admin(self):
        if self.is_admin_authorized():
            return True
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/admin/login?next={quote(self.path, safe='')}")
        self.end_headers()
        return False

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    ensure_storage()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Village 2026 server running on {host}:{port}")
    print("Admin path: /admin")
    server.serve_forever()


if __name__ == "__main__":
    main()
