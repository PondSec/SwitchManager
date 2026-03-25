from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests


requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

_SESSION_TTL_SECONDS = 900
_ASSET_PREFIXES = (
    "cgi-bin/",
    "css/",
    "js/",
    "image/",
    "admin/",
    "html/",
    "favicon.ico",
)


@dataclass
class ProxyState:
    session: requests.Session
    base_url: str
    last_used_at: float


_SESSION_CACHE: dict[str, ProxyState] = {}
_CACHE_LOCK = threading.Lock()


def proxy_zyxel_request(
    *,
    cache_key: str,
    host: str,
    username: str,
    password: str,
    proxy_root: str,
    proxy_path: str,
    method: str,
    query_string: bytes,
    body: bytes | None,
    content_type: str | None,
) -> requests.Response:
    state = _get_or_create_session(cache_key, host, username, password)
    response = _perform_request(state.session, state.base_url, proxy_path, method, query_string, body, content_type)

    if _looks_like_login_page(response):
        session, base_url = _login(host, username, password)
        with _CACHE_LOCK:
            state = ProxyState(session=session, base_url=base_url, last_used_at=time.time())
            _SESSION_CACHE[cache_key] = state
        response = _perform_request(state.session, state.base_url, proxy_path, method, query_string, body, content_type)

    return _rewrite_response(response, state.base_url, host, proxy_root)


def _get_or_create_session(cache_key: str, host: str, username: str, password: str) -> ProxyState:
    with _CACHE_LOCK:
        state = _SESSION_CACHE.get(cache_key)
        if state and time.time() - state.last_used_at < _SESSION_TTL_SECONDS:
            state.last_used_at = time.time()
            return state

    session, base_url = _login(host, username, password)
    state = ProxyState(session=session, base_url=base_url, last_used_at=time.time())
    with _CACHE_LOCK:
        _SESSION_CACHE[cache_key] = state
    return state


def _login(host: str, username: str, password: str) -> tuple[requests.Session, str]:
    if not password:
        raise RuntimeError("Für die native Zyxel-Web-Bridge ist ein Gerätepasswort erforderlich.")

    last_error: Exception | None = None
    for base_url in (f"https://{host}", f"http://{host}"):
        session = requests.Session()
        try:
            session.get(f"{base_url}/cgi-bin/dispatcher.cgi?cmd=0", timeout=10, verify=False)

            auth_id = session.post(
                f"{base_url}/cgi-bin/dispatcher.cgi",
                data={"username": username, "password": _encode_password(password), "login": "true;"},
                timeout=10,
                verify=False,
            ).text.strip()

            if not auth_id:
                raise RuntimeError("Zyxel-Weblogin konnte kein Auth-ID-Ticket erzeugen.")

            status = session.post(
                f"{base_url}/cgi-bin/dispatcher.cgi",
                data={"authId": auth_id, "login_chk": "true"},
                timeout=10,
                verify=False,
            ).text

            if "OK" not in status:
                raise RuntimeError("Zyxel-Weblogin fehlgeschlagen.")

            session.get(f"{base_url}/cgi-bin/dispatcher.cgi?cmd=1", timeout=10, verify=False)
            return session, base_url
        except Exception as exc:  # noqa: BLE001
            session.close()
            last_error = exc

    raise RuntimeError(f"Zyxel-Weblogin fehlgeschlagen: {last_error}")


def _perform_request(
    session: requests.Session,
    base_url: str,
    proxy_path: str,
    method: str,
    query_string: bytes,
    body: bytes | None,
    content_type: str | None,
) -> requests.Response:
    target_path = proxy_path.lstrip("/")
    target_url = urljoin(f"{base_url}/", target_path)
    if query_string:
        target_url = f"{target_url}?{query_string.decode('utf-8', errors='ignore')}"

    headers = {}
    if content_type:
        headers["Content-Type"] = content_type

    return session.request(
        method=method.upper(),
        url=target_url,
        data=body if method.upper() != "GET" else None,
        headers=headers,
        timeout=25,
        verify=False,
        allow_redirects=True,
    )


def _looks_like_login_page(response: requests.Response) -> bool:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "text/html" not in content_type:
        return False

    sample = response.text[:1200]
    return "Enter User Name/Password and click to login." in sample or "login_content_bg" in sample


def _rewrite_response(response: requests.Response, base_url: str, host: str, proxy_root: str) -> requests.Response:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if not any(token in content_type for token in ("text/html", "javascript", "text/css", "application/javascript")):
        return response

    encoding = response.encoding or "utf-8"
    text = response.content.decode(encoding, errors="replace")
    text = _rewrite_payload(text, base_url, host, proxy_root.rstrip("/"))

    cloned = requests.Response()
    cloned.status_code = response.status_code
    cloned.headers = response.headers.copy()
    cloned._content = text.encode(encoding, errors="replace")
    cloned.encoding = encoding
    cloned.url = response.url
    cloned.request = response.request
    return cloned


def _rewrite_payload(text: str, base_url: str, host: str, proxy_root: str) -> str:
    proxy_prefix = proxy_root.lstrip("/")
    base_urls = [f"{base_url.rstrip('/')}/"]
    for candidate in (f"http://{host}/", f"https://{host}/"):
        if candidate not in base_urls:
            base_urls.append(candidate)
    for candidate in base_urls:
        text = text.replace(candidate, f"{proxy_root}/")

    for prefix in _ASSET_PREFIXES:
        for marker in ('"/', "'/", "(/", "url(/", 'url("/', "url('/"):
            text = text.replace(f"{marker}{prefix}", f"{marker}{proxy_prefix}/{prefix}")

    return text


def _encode_password(password: str) -> str:
    possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    password_length = len(password)
    remaining = len(password)
    encoded = []

    for index in range(1, 321 - password_length + 1):
        if index % 5 == 0 and remaining > 0:
            remaining -= 1
            encoded.append(password[remaining])
        elif index == 123:
            encoded.append("0" if password_length < 10 else str(password_length // 10))
        elif index == 289:
            encoded.append(str(password_length % 10))
        else:
            encoded.append(secrets.choice(possible))

    return "".join(encoded)
