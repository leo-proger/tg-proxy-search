"""
Diagnose a single proxy, bypassing the cache, with full step-by-step output.

Usage:
    python diagnose.py "tg://proxy?server=...&port=...&secret=..."
    python diagnose.py <server> <port> <secret>

Run it against a proxy you can SEE working in Telegram right now, and paste the
output. Try it both with your VPN on and off — the raw bytes tell us exactly
where (and whether) the handshake breaks.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from tg_proxy_search.checker import (
    _DIGEST_LEN,
    _DIGEST_POS,
    _build_client_hello,
    mtproto_check,
)
from tg_proxy_search.config import Config
from tg_proxy_search.parser import proxy_from_url
from tg_proxy_search.secret import FAKETLS, parse_secret

load_dotenv()


def parse_args() -> tuple[str, int, str]:
    if len(sys.argv) == 2 and sys.argv[1].startswith("tg://"):
        proxy = proxy_from_url(sys.argv[1])
        if not proxy:
            sys.exit("Could not parse the tg://proxy link.")
        return proxy.server, proxy.port, proxy.secret
    if len(sys.argv) == 4:
        return sys.argv[1], int(sys.argv[2]), sys.argv[3]
    sys.exit(__doc__)


async def diagnose_faketls(server: str, port: int, key: bytes, sni: str, timeout: float) -> None:
    print(f"  system clock (UTC): {datetime.now(timezone.utc).isoformat()}")
    print(f"  connecting to {server}:{port} ...")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout)
    except Exception as e:
        print(f"  ✗ TCP connect FAILED: {type(e).__name__}: {e}")
        return
    print("  ✓ TCP connected")

    hello, client_digest = _build_client_hello(key, sni)
    writer.write(hello)
    await writer.drain()
    print(f"  → sent fake-TLS ClientHello ({len(hello)} bytes), SNI={sni!r}")

    try:
        data = await asyncio.wait_for(reader.read(16384), timeout)
    except Exception as e:
        print(f"  ✗ no response: {type(e).__name__}: {e}")
        print("    (silence usually means the digest was rejected → proxy fell back to its")
        print("     camouflage upstream, OR the connection is blocked/filtered on this network)")
        writer.close()
        return

    print(f"  ← received {len(data)} bytes")
    if not data:
        print("  ✗ server closed without sending data")
        writer.close()
        return
    print(f"    first byte: 0x{data[0]:02x} (0x16 = TLS handshake, expected)")
    print(f"    first 16 bytes: {data[:16].hex()}")

    if len(data) >= _DIGEST_POS + _DIGEST_LEN:
        server_digest = data[_DIGEST_POS:_DIGEST_POS + _DIGEST_LEN]
        zeroed = data[:_DIGEST_POS] + b"\x00" * _DIGEST_LEN + data[_DIGEST_POS + _DIGEST_LEN:]
        expected = hmac.new(key, client_digest + zeroed, hashlib.sha256).digest()
        match = hmac.compare_digest(expected, server_digest)
        print(f"    server digest verifies (over full {len(data)}-byte read): {match}")
        if not match:
            print("    NOTE: a real proxy may split its reply across reads; the production")
            print("    check reads exactly ServerHello+ChangeCipherSpec+AppData records.")
    writer.close()


async def main() -> None:
    server, port, secret = parse_args()
    cfg = Config.from_env()
    parsed = parse_secret(secret)

    print("─" * 60)
    print(f"proxy : {server}:{port}")
    print(f"secret: {secret}")
    print(f"kind  : {parsed.kind}")
    print(f"key   : {parsed.key.hex()}")
    if parsed.domain:
        print(f"domain: {parsed.domain}")
    print(f"timeout: {cfg.tcp_timeout}s")
    print("─" * 60)

    if parsed.kind == FAKETLS:
        print("FAKE-TLS check:")
        await diagnose_faketls(server, port, parsed.key, parsed.domain or server, cfg.tcp_timeout)
    else:
        print(f"{parsed.kind.upper()} check (via Telethon MTProto):")
        ts = time.monotonic()
        ok = await mtproto_check(
            server, port, parsed.telethon_secret(), cfg.api_id, cfg.api_hash, cfg.tcp_timeout
        )
        print(f"  result: {'WORKING' if ok else 'FAILED'}  ({time.monotonic() - ts:.1f}s)")

    print("─" * 60)


if __name__ == "__main__":
    asyncio.run(main())
