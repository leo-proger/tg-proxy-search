"""
Диагностика одного прокси с подробным пошаговым выводом, минуя кэш.

Использование:
    python diagnose.py "tg://proxy?server=...&port=...&secret=..."
    python diagnose.py <server> <port> <secret>

Запускать против прокси, который ВИДЕН как рабочий в Telegram прямо сейчас.
Попробуйте с VPN включённым и выключенным -- сырые байты точно покажут,
где (и случается ли) handshake ломается.
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
            sys.exit("Не удалось разобрать ссылку tg://proxy.")
        return proxy.server, proxy.port, proxy.secret
    if len(sys.argv) == 4:
        return sys.argv[1], int(sys.argv[2]), sys.argv[3]
    sys.exit(__doc__)


async def diagnose_faketls(server: str, port: int, key: bytes, sni: str, timeout: float) -> None:
    print(f"  системное время (UTC): {datetime.now(timezone.utc).isoformat()}")
    print(f"  подключаемся к {server}:{port} ...")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout)
    except Exception as e:
        print(f"  x TCP подключение ПРОВАЛИЛОСЬ: {type(e).__name__}: {e}")
        return
    print("  v TCP подключено")

    hello, client_digest = _build_client_hello(key, sni)
    writer.write(hello)
    await writer.drain()
    print(f"  -> отправлен fake-TLS ClientHello ({len(hello)} байт), SNI={sni!r}")

    try:
        data = await asyncio.wait_for(reader.read(16384), timeout)
    except Exception as e:
        print(f"  x нет ответа: {type(e).__name__}: {e}")
        print("    (тишина обычно означает: дайджест отклонён -> прокси перенаправил на свой")
        print("     камуфляжный upstream, или соединение заблокировано/отфильтровано в этой сети)")
        writer.close()
        return

    print(f"  <- получено {len(data)} байт")
    if not data:
        print("  x сервер закрыл соединение без данных")
        writer.close()
        return
    print(f"    первый байт: 0x{data[0]:02x} (0x16 = TLS handshake, ожидается)")
    print(f"    первые 16 байт: {data[:16].hex()}")

    if len(data) >= _DIGEST_POS + _DIGEST_LEN:
        server_digest = data[_DIGEST_POS:_DIGEST_POS + _DIGEST_LEN]
        zeroed = data[:_DIGEST_POS] + b"\x00" * _DIGEST_LEN + data[_DIGEST_POS + _DIGEST_LEN:]
        expected = hmac.new(key, client_digest + zeroed, hashlib.sha256).digest()
        match = hmac.compare_digest(expected, server_digest)
        print(f"    дайджест сервера верен (по всем {len(data)} прочитанным байтам): {match}")
        if not match:
            print("    ЗАМЕЧАНИЕ: настоящий прокси может разбить ответ на несколько read;")
            print("    продакшн-проверка читает ровно ServerHello+ChangeCipherSpec+AppData записи.")
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
        print("FAKE-TLS проверка:")
        await diagnose_faketls(server, port, parsed.key, parsed.domain or server, cfg.tcp_timeout)
    else:
        print(f"{parsed.kind.upper()} проверка (через Telethon MTProto):")
        ts = time.monotonic()
        ok = await mtproto_check(
            server, port, parsed.telethon_secret(), cfg.api_id, cfg.api_hash, cfg.tcp_timeout
        )
        print(f"  результат: {'РАБОЧИЙ' if ok else 'ПРОВАЛ'}  ({time.monotonic() - ts:.1f}с)")

    print("─" * 60)


if __name__ == "__main__":
    asyncio.run(main())
