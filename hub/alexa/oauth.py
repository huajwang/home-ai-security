"""Authorization-code login for one Alexa Smart Home skill."""

from __future__ import annotations

import hmac
import html
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

from hub import config

_CODE_SECONDS = 300
_AMAZON_HOSTS = (
    "amazon.com",
    "amazon.ca",
    "amazon.co.jp",
    "amazon.co.uk",
    "amazon.com.au",
    "amazon.de",
    "amazon.es",
    "amazon.fr",
    "amazon.in",
    "amazon.it",
)


def configured() -> bool:
    return bool(config.ALEXA_CLIENT_ID and config.ALEXA_CLIENT_SECRET)


def client_matches(client_id: str, client_secret: str | None = None) -> bool:
    if not configured() or not _same(client_id, config.ALEXA_CLIENT_ID):
        return False
    if client_secret is None:
        return True
    return _same(client_secret, config.ALEXA_CLIENT_SECRET)


def amazon_redirect(url: str) -> bool:
    if not url or any(char in url for char in "\r\n\\ "):
        return False
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.port not in {None, 443}:
        return False
    if not parts.path.startswith("/api/skill/link/"):
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in _AMAZON_HOSTS)


def safe_state(state: str) -> bool:
    return len(state) <= 4096 and state.isascii() and "\r" not in state and "\n" not in state


def save_code(app: Any, user_id: int, device_id: int, redirect_uri: str) -> str:
    codes = _codes(app)
    now = time.time()
    expired = [key for key, row in codes.items() if row["exp"] <= now]
    for key in expired:
        codes.pop(key, None)
    code = secrets.token_urlsafe(32)
    codes[code] = {
        "user_id": user_id,
        "device_id": device_id,
        "redirect_uri": redirect_uri,
        "exp": now + _CODE_SECONDS,
    }
    return code


def take_code(app: Any, code: str, redirect_uri: str) -> dict[str, Any] | None:
    row = _codes(app).pop(code, None)
    if row is None or row["exp"] <= time.time() or row["redirect_uri"] != redirect_uri:
        return None
    return row


def login_page(
    client_id: str,
    redirect_uri: str,
    state: str,
    error: str = "",
) -> str:
    message = f"<p>{html.escape(error)}</p>" if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Link Alexa</title>
</head>
<body>
<main>
<h1>Link Alexa to this hub</h1>
<p>Alexa can turn lights on and off. It cannot unlock, lock, arm, or disarm.</p>
{message}
<form method="post" action="/alexa/oauth/authorize">
<input type="hidden" name="client_id" value="{html.escape(client_id)}">
<input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri)}">
<input type="hidden" name="state" value="{html.escape(state)}">
<input type="hidden" name="response_type" value="code">
<label>Username <input name="username" autocomplete="username" required></label>
<label>Password <input name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">Link</button>
</form>
</main>
</body>
</html>
"""


def redirect_target(redirect_uri: str, code: str, state: str) -> str:
    query = urlencode({"code": code, "state": state})
    join = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{join}{query}"


def _codes(app: Any) -> dict[str, dict[str, Any]]:
    codes = getattr(app.state, "alexa_codes", None)
    if codes is None:
        codes = {}
        app.state.alexa_codes = codes
    return codes


def _same(left: str, right: str) -> bool:
    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except Exception:
        return False
