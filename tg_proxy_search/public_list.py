from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Sequence
from itertools import chain
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import Proxy


def merge_proxy_urls(
    new_proxies: Iterable[Proxy],
    existing_urls: Iterable[str],
    limit: int = 1000,
) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    new_urls = (proxy.tg_link() for proxy in new_proxies)
    return list(dict.fromkeys(chain(new_urls, existing_urls)))[:limit]


def read_proxy_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_proxy_urls(urls: Sequence[str], limit: int = 1000) -> None:
    if not urls:
        raise ValueError("proxy list must not be empty")
    if len(urls) > limit:
        raise ValueError(f"proxy list contains more than {limit} URLs")
    if len(urls) != len(set(urls)):
        raise ValueError("proxy list contains duplicate proxy URLs")

    for line_number, url in enumerate(urls, start=1):
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        required = {"server", "port", "secret"}
        try:
            port = int(query["port"][0])
            valid = (
                url.startswith("tg://proxy?")
                and parsed.scheme == "tg"
                and parsed.netloc == "proxy"
                and parsed.path == ""
                and parsed.fragment == ""
                and set(query) == required
                and all(len(query[name]) == 1 and query[name][0] for name in required)
                and 1 <= port <= 65535
            )
        except (KeyError, ValueError):
            valid = False
        if not valid:
            raise ValueError(f"invalid proxy URL at line {line_number}")


def write_proxy_urls(path: Path, urls: Sequence[str]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write("".join(f"{url}\n" for url in urls))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
