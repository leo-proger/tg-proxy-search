from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
import warnings

from telethon import TelegramClient
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate
from telethon.sessions import StringSession

from .models import Proxy
from .secret import FAKETLS, parse_secret

logging.getLogger("telethon").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", category=UserWarning, module="telethon")


async def check_proxy(proxy: Proxy, api_id: int, api_hash: str, timeout: float) -> bool:
    """
    Проверяет прокси полным подключением, выбирая путь по типу секрета.

    Большинство публичных прокси сегодня используют fake-TLS (ee-секреты), а Telethon
    не умеет этот протокол: он срезает ee/домен и говорит randomized-intermediate,
    поэтому рабочий fake-TLS прокси молчит и выглядит мёртвым.
    Такие прокси идут через faketls_check (настоящий fake-TLS handshake); dd/plain
    по-прежнему через MTProto-соединение Telethon.

    Результат False здесь не окончательный: вызывающий код перепроверяет провалы
    при более низкой конкурентности, так как медленный прокси может истечь по таймауту,
    когда много handshake-ов одновременно конкурируют за полосу.
    """
    try:
        parsed = parse_secret(proxy.secret)
    except Exception:
        return False
    if parsed.kind == FAKETLS:
        sni = parsed.domain or proxy.server
        return await faketls_check(proxy.server, proxy.port, parsed.key, sni, timeout)
    return await mtproto_check(proxy.server, proxy.port, parsed.telethon_secret(), api_id, api_hash, timeout)


async def mtproto_check(
    server: str, port: int, secret: str, api_id: int, api_hash: str, timeout: float
) -> bool:
    """
    Открывает настоящее MTProto-соединение через dd/plain прокси и завершает handshake.
    Одно TCP-соединение без предварительной проверки, чтобы не штрафовать
    высоколатентные прокси лишним коннектом.
    """
    try:
        client = TelegramClient(
            StringSession(),
            api_id,
            api_hash,
            connection=ConnectionTcpMTProxyRandomizedIntermediate,
            proxy=(server, port, secret),
        )
    except Exception:
        return False
    try:
        await asyncio.wait_for(client.connect(), timeout=timeout)
        return client.is_connected()
    except Exception:
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# Fake-TLS handshake
# Fake-TLS прокси аутентифицирует клиента по HMAC-SHA256 дайджесту в 32-байтовом поле
# random TLS ClientHello (ключ: 16-байтовый секрет; поле при расчёте обнуляется,
# последние 4 байта содержат Unix timestamp). Правильный дайджест заставляет прокси
# ответить камуфляжными ServerHello + ChangeCipherSpec + ApplicationData,
# подписанными своим дайджестом по (client_digest || response).
# Неправильный дайджест: прокси форвардит запрос на настоящий upstream или молчит.
# Проверка дайджеста ответа позволяет отличить настоящий MTProto прокси от обычного TLS.
#
# Реализация: github.com/alexbers/mtprotoproxy (handle_fake_tls_handshake).

_DIGEST_POS = 11
_DIGEST_LEN = 32
_HELLO_LEN = 517  # общий размер ClientHello в байтах, до которого дополняется настоящий Chrome/tdlib

# Нужен точный Chrome/tdlib-подобный ClientHello, а не минимальный самодельный:
# mtg-прокси отклоняет hello без non-GREASE шифров или без SNI,
# а DPI в цензурируемых сетях режет соединения с нетипичным fingerprint.
# Ниже фиксированные cipher-suite и расширения из реального hello (9seconds/mtg testdata);
# варьируются только SNI, session id, key-share, random/digest и паддинг.
_CIPHER_SUITES = bytes.fromhex(
    "0034130313011302c02cc02bc024c023c00ac009cca9c030c02fc028c027c014c013cca8009d009c003d003c0035002fc008c012000a"
)
_EXT_RENEGO = bytes.fromhex("ff01000100")
_EXT_EXT_MASTER_SECRET = bytes.fromhex("00170000")
_EXT_SIG_ALGS = bytes.fromhex("000d0018001604030804040105030203080508050501080606010201")
_EXT_STATUS_REQ = bytes.fromhex("000500050100000000")
_EXT_TOKEN_BINDING = bytes.fromhex("33740000")
_EXT_SCT = bytes.fromhex("00120000")
_EXT_ALPN = bytes.fromhex(
    "00100030002e0268320568322d31360568322d31350568322d313408737064792f332e3106737064792f3308687474702f312e31"
)
_EXT_EC_POINT = bytes.fromhex("000b00020100")
_EXT_PSK_MODES = bytes.fromhex("002d00020101")
_EXT_SUPPORTED_VERSIONS = bytes.fromhex("002b0009080304030303020301")
_EXT_SUPPORTED_GROUPS = bytes.fromhex("000a000a0008001d001700180019")


def _sni_extension(sni: str) -> bytes:
    host = sni.encode("ascii", "ignore")
    name = b"\x00" + len(host).to_bytes(2, "big") + host          # host_name entry
    name_list = len(name).to_bytes(2, "big") + name               # server_name_list
    return b"\x00\x00" + len(name_list).to_bytes(2, "big") + name_list


def _build_client_hello(key: bytes, sni: str) -> tuple[bytes, bytes]:
    key_share = b"\x00\x33\x00\x26\x00\x24\x00\x1d\x00\x20" + os.urandom(32)
    extensions = (
        _EXT_RENEGO
        + _sni_extension(sni)
        + _EXT_EXT_MASTER_SECRET
        + _EXT_SIG_ALGS
        + _EXT_STATUS_REQ
        + _EXT_TOKEN_BINDING
        + _EXT_SCT
        + _EXT_ALPN
        + _EXT_EC_POINT
        + key_share
        + _EXT_PSK_MODES
        + _EXT_SUPPORTED_VERSIONS
        + _EXT_SUPPORTED_GROUPS
    )
    prefix = (
        b"\x03\x03"                       # client_version (TLS 1.2)
        + b"\x00" * _DIGEST_LEN           # random -- здесь будет записан дайджест
        + b"\x20" + os.urandom(32)        # session_id (32 байта)
        + _CIPHER_SUITES
        + b"\x01\x00"                     # compression: null
    )
    # Добавляем паддинг (расширение 0x0015), чтобы весь record был ровно _HELLO_LEN байт,
    # как в настоящем браузерном hello.
    overhead = 5 + 4 + len(prefix) + 2 + len(extensions) + 4  # record+handshake hdrs, ext-len field, padding hdr
    pad_len = max(0, _HELLO_LEN - overhead)
    extensions += b"\x00\x15" + pad_len.to_bytes(2, "big") + b"\x00" * pad_len

    body = prefix + len(extensions).to_bytes(2, "big") + extensions
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    hello = b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake

    computed = hmac.new(key, hello, hashlib.sha256).digest()
    timestamped = (int.from_bytes(computed[28:32], "little") ^ int(time.time())).to_bytes(4, "little")
    digest = computed[:28] + timestamped
    hello = hello[:_DIGEST_POS] + digest + hello[_DIGEST_POS + _DIGEST_LEN:]
    return hello, digest


async def _read_record(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(5)
    length = int.from_bytes(header[3:5], "big")
    return header + await reader.readexactly(length)


async def faketls_check(server: str, port: int, key: bytes, sni: str, timeout: float) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout)
    except Exception:
        return False
    try:
        hello, client_digest = _build_client_hello(key, sni)
        writer.write(hello)
        await writer.drain()

        async def read_response() -> bytes:
            buf = b""
            for _ in range(3):  # ServerHello, ChangeCipherSpec, ApplicationData
                buf += await _read_record(reader)
            return buf

        response = await asyncio.wait_for(read_response(), timeout)
        server_digest = response[_DIGEST_POS:_DIGEST_POS + _DIGEST_LEN]
        zeroed = response[:_DIGEST_POS] + b"\x00" * _DIGEST_LEN + response[_DIGEST_POS + _DIGEST_LEN:]
        expected = hmac.new(key, client_digest + zeroed, hashlib.sha256).digest()
        return hmac.compare_digest(expected, server_digest)
    except Exception:
        return False
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
