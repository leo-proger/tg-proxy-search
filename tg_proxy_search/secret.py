"""
Decode and classify MTProto proxy secrets.

A ``tg://proxy`` secret can arrive in several encodings and flavours, and the
same proxy may be advertised in more than one of them (e.g. the post text uses
hex while the inline "Connect" button uses base64url — those are the *same*
bytes). Telethon's own normaliser only strips the ``ee``/``dd`` prefix when the
secret is a *hex string*, so a base64url-encoded ee/dd secret ends up with the
marker byte kept as part of the key and the last key byte dropped — a silently
wrong key. We therefore decode to raw bytes ourselves and classify by the
marker byte, which works regardless of the original encoding.

Flavours (by the first raw byte):
  0xEE  fake-TLS   — key = bytes[1:17], the rest is the camouflage domain (SNI).
                     Telethon CANNOT speak this protocol; use faketls_check.
  0xDD  randomized — key = bytes[1:17] (ConnectionTcpMTProxyRandomizedIntermediate).
  else  plain      — key = bytes[0:16].
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
    key: bytes         # the 16-byte MTProto key
    domain: str        # fake-TLS camouflage host (empty unless kind == FAKETLS)

    def telethon_secret(self) -> str:
        """
        Canonical hex secret that Telethon's normaliser handles correctly.
        Only meaningful for DD / PLAIN proxies (fake-TLS is checked separately).
        """
        return ("dd" if self.kind == DD else "") + self.key.hex()


def decode_secret(secret: str) -> bytes:
    """
    Turn a secret string into its raw bytes, accepting every form seen in the
    wild: hex, hex with an ee/dd prefix, base64url, and URL-encoded base64url
    (``%3D`` padding from links that were percent-encoded).

    Mirrors the hex-first / base64url-fallback convention used by Telegram
    clients, so a hex-looking secret is never mis-read as base64.
    """
    secret = unquote(secret).strip()
    try:
        return bytes.fromhex(secret)
    except ValueError:
        pass
    # base64url, tolerant of missing padding
    return base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))


def parse_secret(secret: str) -> ParsedSecret:
    raw = decode_secret(secret)
    if raw[:1] == b"\xee":
        return ParsedSecret(FAKETLS, raw[1:17], raw[17:].decode("ascii", "ignore"))
    if raw[:1] == b"\xdd":
        return ParsedSecret(DD, raw[1:17], "")
    return ParsedSecret(PLAIN, raw[:16], "")
