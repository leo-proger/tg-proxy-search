from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import URLError

from tg_proxy_search.public_source import (
    PUBLIC_PROXY_LIST_URL,
    download_public_proxies,
    parse_public_proxy_list,
)


class ParsePublicProxyListTests(unittest.TestCase):
    def test_all_urls_are_converted_to_proxies_in_source_order(self) -> None:
        text = (
            "tg://proxy?server=first.example&port=443&secret=first-secret\n"
            "tg://proxy?server=second.example&port=8443&secret=second-secret\n"
        )

        proxies = parse_public_proxy_list(text)

        self.assertEqual(
            [(proxy.server, proxy.port, proxy.secret) for proxy in proxies],
            [
                ("first.example", 443, "first-secret"),
                ("second.example", 8443, "second-secret"),
            ],
        )

    def test_empty_list_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            parse_public_proxy_list("\n")

    def test_invalid_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid proxy URL at line 2"):
            parse_public_proxy_list(
                "tg://proxy?server=valid.example&port=443&secret=valid\n"
                "not-a-proxy\n"
            )


class DownloadPublicProxiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloaded_text_is_parsed(self) -> None:
        captured: dict[str, object] = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b"tg://proxy?server=public.example&port=443&secret=raw\n"

        def fake_urlopen(url: str, *, timeout: float):
            captured["url"] = url
            captured["timeout"] = timeout
            return Response()

        with patch("tg_proxy_search.public_source.urlopen", new=fake_urlopen):
            proxies = await download_public_proxies(timeout=7.5)

        self.assertEqual(captured, {"url": PUBLIC_PROXY_LIST_URL, "timeout": 7.5})
        self.assertEqual(proxies[0].server, "public.example")

    async def test_network_error_is_reported_as_runtime_error(self) -> None:
        with patch(
            "tg_proxy_search.public_source.urlopen",
            side_effect=URLError("offline"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Не удалось скачать публичный список"):
                await download_public_proxies()


if __name__ == "__main__":
    unittest.main()
