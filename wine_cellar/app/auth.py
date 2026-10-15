"""Login for direct access (the app's own port, outside Home Assistant ingress).

Ingress requests are already authenticated by Home Assistant. Requests on the direct port must log in with a
Home Assistant user named in the `allowed_users` option. Passwords are checked by Home Assistant through the
Supervisor auth API; the app never stores them. A signed cookie keeps the browser logged in.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import threading
import time
import urllib.error
import urllib.request

OPTIONS_FILE = os.environ.get("WINE_OPTIONS", "/data/options.json")
SECRET_FILE = os.environ.get("WINE_SESSION_SECRET", "/data/session_secret")
COOKIE = "wc_session"
LIFETIME = 90 * 24 * 3600  # stay logged in for 90 days
MAX_FAILS, FAIL_WINDOW = 5, 15 * 60  # per client address

_secret_lock = threading.Lock()
_fails, _fails_lock = {}, threading.Lock()


def allowed_users():
    try:
        with open(OPTIONS_FILE) as f:
            users = json.load(f).get("allowed_users") or []
    except (OSError, ValueError):
        users = []
    return {str(u).strip().lower() for u in users if str(u).strip()}


def _secret():
    with _secret_lock:
        try:
            with open(SECRET_FILE, "rb") as f:
                s = f.read()
            if len(s) >= 32:
                return s
        except OSError:
            pass
        s = os.urandom(32)
        fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(s)
        return s


def _sign(payload):
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def make_cookie(user):
    payload = base64.urlsafe_b64encode(json.dumps([user, int(time.time()) + LIFETIME]).encode()).decode()
    return (f"{COOKIE}={payload}.{_sign(payload.encode())}; Path=/; Max-Age={LIFETIME}; HttpOnly; SameSite=Lax")


def clear_cookie():
    return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def session_user(cookie_header):
    """The logged-in user, or None. A user removed from allowed_users is logged out at once."""
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name != COOKIE or "." not in value:
            continue
        payload, sig = value.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload.encode())):
            return None
        try:
            user, exp = json.loads(base64.urlsafe_b64decode(payload.encode()))
        except (ValueError, TypeError):
            return None
        if exp < time.time() or user not in allowed_users():
            return None
        return user
    return None


def locked_out(addr):
    with _fails_lock:
        recent = [t for t in _fails.get(addr, []) if time.time() - t < FAIL_WINDOW]
        _fails[addr] = recent
        return len(recent) >= MAX_FAILS


def _failed(addr):
    with _fails_lock:
        _fails.setdefault(addr, []).append(time.time())


def login(addr, username, password):
    """Check the credentials with Home Assistant. Returns (user, error message)."""
    user = (username or "").strip().lower()
    if locked_out(addr):
        return None, "Too many failed attempts. Try again in 15 minutes."
    if not user or not password or user not in allowed_users():
        _failed(addr)
        time.sleep(1)
        return None, "Wrong username or password."
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None, "Login is not available (no Supervisor token)."
    req = urllib.request.Request("http://supervisor/auth", method="POST",
                                 data=json.dumps({"username": user, "password": password}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            _failed(addr)
            time.sleep(1)
            return None, "Wrong username or password."
        print("Login check failed:", e, flush=True)
        return None, "Home Assistant could not check the login. Try again."
    except urllib.error.URLError as e:
        print("Login check failed:", e, flush=True)
        return None, "Home Assistant could not be reached. Try again."
    with _fails_lock:
        _fails.pop(addr, None)
    print(f"Direct access: {user} logged in from {addr}", flush=True)
    return user, None


def login_page(error=None, version=""):
    if not allowed_users():
        body = ('<p class="muted">Direct access is not set up. Add the Home Assistant users who may log in '
                'under <b>allowed_users</b> in the app configuration.</p>')
    else:
        err = f'<p class="loginerr">{html.escape(error)}</p>' if error else ""
        body = f"""{err}<form method="post" action="login">
  <label>Username<input name="username" autocomplete="username" autocapitalize="none" required autofocus></label>
  <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
  <button class="btn primary" type="submit">Log in</button>
</form>
<p class="muted small">Log in with your Home Assistant user.</p>"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wine Cellar</title>
<link rel="icon" href="wc/glass.svg?v={version}" type="image/svg+xml">
<link rel="stylesheet" href="wc/style.css?v={version}">
</head><body class="loginbody"><main class="loginbox">
<h1><img src="wc/glass.svg?v={version}" alt="" width="22" height="22"> Wine Cellar</h1>
{body}
</main></body></html>"""
