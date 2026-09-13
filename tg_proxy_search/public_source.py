from __future__ import annotations

import asyncio
from urllib.error import URLError
from urllib.request import urlopen

from .models import Proxy
from .parser import proxy_from_url
from .public_list import validate_proxy_urls

PUBLIC_PROXY_LIST_URL = (
    "https://raw.githubusercontent.com/leo-proger/tg-proxy-search/main/proxies.txt"
)


def parse_public_proxy_list(text: str) -> list[Proxy]:
    urls = [line.strip() for line in text.splitlines() if line.strip()]
    validate_proxy_urls(urls, limit=1000)

    proxies: list[Proxy] = []
    for url in urls:
        proxy = proxy_from_url(url)
        if proxy is None:
            raise ValueError("validated proxy URL could not be parsed")
        proxies.append(proxy)
    return proxies


def _download_text(url: str, timeout: float) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


async def download_public_proxies(
    url: str = PUBLIC_PROXY_LIST_URL,
    timeout: float = 15.0,
) -> list[Proxy]:
    try:
        text = await asyncio.to_thread(_download_text, url, timeout)
        return parse_public_proxy_list(text)
    except (OSError, URLError, UnicodeDecodeError, ValueError) as error:
        raise RuntimeError(f"Не удалось скачать публичный список прокси: {error}") from error
