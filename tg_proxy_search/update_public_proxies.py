from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from .config import Config
from .core import fetch
from .public_list import (
    merge_proxy_urls,
    read_proxy_urls,
    validate_proxy_urls,
    write_proxy_urls,
)


async def update_public_proxies(
    session_file: str,
    output_file: Path,
    limit: int = 1000,
) -> int:
    with tempfile.TemporaryDirectory(prefix="tg-proxy-search-") as directory:
        config = replace(
            Config.from_env(),
            cache_file=str(Path(directory) / "proxies.json"),
            max_scan_messages=limit,
        )
        result = await fetch(config, session_file=session_file)

    if not result.candidates:
        raise RuntimeError("Telegram fetch returned no proxies; keeping the existing public list")

    urls = merge_proxy_urls(result.candidates, read_proxy_urls(output_file), limit)
    validate_proxy_urls(urls, limit)
    write_proxy_urls(output_file, urls)
    print(
        f"Scanned {result.scanned} messages, "
        f"fetched {result.found} proxies, saved {len(urls)} URLs"
    )
    return len(urls)


def main() -> None:
    parser = argparse.ArgumentParser(description="Update the pipeline-managed public MTProto proxy list")
    parser.add_argument(
        "--session-file",
        default=os.environ.get("TELETHON_SESSION_FILE"),
        help="Telethon session path (default: TELETHON_SESSION_FILE)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("proxies.txt"),
        help="Public proxy list path (default: proxies.txt)",
    )
    args = parser.parse_args()
    if not args.session_file:
        parser.error("--session-file or TELETHON_SESSION_FILE is required")

    asyncio.run(update_public_proxies(args.session_file, args.output))


if __name__ == "__main__":
    main()
