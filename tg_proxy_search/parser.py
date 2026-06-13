from __future__ import annotations

import re
from datetime import datetime

from telethon.tl.custom import Message

from .cache import MSK
from .models import Proxy

_PARAM_RE = re.compile(r"([a-z]+)=([^&\s]+)")
_SERVER_RE = re.compile(r"Server:\s*(\S+)", re.IGNORECASE)
_PORT_RE = re.compile(r"Port:\s*(\d+)", re.IGNORECASE)
_SECRET_RE = re.compile(r"Secret:\s*(\S+)", re.IGNORECASE)


def proxy_from_url(url: str, posted_at: str | None = None) -> Proxy | None:
    params: dict[str, str] = dict(_PARAM_RE.findall(url))
    server = params.get("server")
    port_str = params.get("port")
    secret = params.get("secret")
    if not (server and port_str and secret):
        return None
    try:
        return Proxy(server=server, port=int(port_str), secret=secret, posted_at=posted_at)
    except ValueError:
        return None


def extract_from_message(message: Message) -> list[Proxy]:
    # message.date is timezone-aware UTC; convert to MSK for consistency with the cache.
    date: datetime | None = getattr(message, "date", None)
    posted_at = date.astimezone(MSK).isoformat() if date else None

    # Priority: URL from "Connect" buttons — already a ready tg://proxy link
    if message.buttons:
        proxies: list[Proxy] = []
        for row in message.buttons:
            for button in row:
                url: str | None = getattr(button, "url", None)
                if url and "proxy" in url:
                    proxy = proxy_from_url(url, posted_at)
                    if proxy:
                        proxies.append(proxy)
        if proxies:
            return proxies

    # Fallback: text format "Server: / Port: / Secret:"
    if message.text:
        server_m = _SERVER_RE.search(message.text)
        port_m = _PORT_RE.search(message.text)
        secret_m = _SECRET_RE.search(message.text)
        if server_m and port_m and secret_m:
            try:
                return [Proxy(
                    server=server_m.group(1),
                    port=int(port_m.group(1)),
                    secret=secret_m.group(1),
                    posted_at=posted_at,
                )]
            except ValueError:
                pass

    return []
