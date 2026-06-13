"""
Декодирование и классификация секретов MTProto прокси.

Секрет ``tg://proxy`` может прийти в нескольких кодировках и видах,
причём один и тот же прокси может рекламироваться в нескольких сразу
(например, текст поста в hex, кнопка "Подключиться" в base64url -- это одни и те же байты).
Встроенный нормализатор Telethon срезает префикс ``ee``/``dd`` только если секрет
в виде hex-строки, поэтому base64url-закодированный ee/dd секрет в Telethon
оставляет маркерный байт в ключе и теряет последний байт ключа -- ошибка без предупреждений.
Поэтому мы сами декодируем в сырые байты и классифицируем по маркерному байту,
что работает независимо от исходной кодировки.

Виды (по первому сырому байту):
  0xEE  fake-TLS    -- ключ = bytes[1:17], остаток -- камуфляжный домен (SNI).
                       Telethon НЕ УМЕЕТ этот протокол; использовать faketls_check.
  0xDD  randomized  -- ключ = bytes[1:17] (ConnectionTcpMTProxyRandomizedIntermediate).
  иначе plain       -- ключ = bytes[0:16].
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import unquote

FAKETLS = "faketls"
DD = "dd"
PLAIN = "plain"


@dataclass(frozen=True)
class ParsedSecret:
    kind: str          # FAKETLS | DD | PLAIN
    key: bytes         # 16-байтовый MTProto ключ
    domain: str        # камуфляжный домен для fake-TLS (пусто, если kind != FAKETLS)

    def telethon_secret(self) -> str:
        """
        Канонический hex-секрет, который нормализатор Telethon обрабатывает правильно.
        Актуально только для DD / PLAIN прокси (fake-TLS проверяется отдельно).
        """
        return ("dd" if self.kind == DD else "") + self.key.hex()


def decode_secret(secret: str) -> bytes:
    """
    Преобразует строку секрета в сырые байты, принимая все форматы из реальных постов:
    hex, hex с префиксом ee/dd, base64url и URL-encoded base64url
    (``%3D`` паддинг из percent-encoded ссылок).

    Следует логике Telegram-клиентов: hex сначала, base64url как запасной вариант,
    чтобы hex-похожий секрет не был прочитан как base64.
    """
    secret = unquote(secret).strip()
    try:
        return bytes.fromhex(secret)
    except ValueError:
        pass
    # base64url, терпим к отсутствующему паддингу
    return base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))


def parse_secret(secret: str) -> ParsedSecret:
    raw = decode_secret(secret)
    if raw[:1] == b"\xee":
        return ParsedSecret(FAKETLS, raw[1:17], raw[17:].decode("ascii", "ignore"))
    if raw[:1] == b"\xdd":
        return ParsedSecret(DD, raw[1:17], "")
    return ParsedSecret(PLAIN, raw[:16], "")
