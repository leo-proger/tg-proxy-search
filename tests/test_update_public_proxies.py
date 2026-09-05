from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tg_proxy_search.core import FetchResult
from tg_proxy_search.models import Proxy
from tg_proxy_search.update_public_proxies import update_public_proxies


class UpdatePublicProxiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_fetch_updates_txt_without_touching_local_json(self) -> None:
        captured: dict[str, object] = {}

        async def fake_fetch(config, *, session_file, **_kwargs):
            captured["cache_file"] = config.cache_file
            captured["max_scan_messages"] = config.max_scan_messages
            captured["session_file"] = session_file
            return FetchResult(
                candidates=[Proxy("new.example", 443, "new-secret")],
                scanned=5,
            )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proxies.txt"
            output.write_text(
                "tg://proxy?server=old.example&port=443&secret=old-secret\n",
                encoding="utf-8",
            )

            with patch("tg_proxy_search.update_public_proxies.fetch", new=fake_fetch):
                count = await update_public_proxies("/tmp/test.session", output, limit=1000)

            self.assertEqual(count, 2)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "tg://proxy?server=new.example&port=443&secret=new-secret\n"
                "tg://proxy?server=old.example&port=443&secret=old-secret\n",
            )

        self.assertEqual(captured["session_file"], "/tmp/test.session")
        self.assertEqual(captured["max_scan_messages"], 1000)
        self.assertNotEqual(captured["cache_file"], "proxies.json")
        self.assertFalse(Path(str(captured["cache_file"])).exists())

    async def test_empty_fetch_preserves_existing_public_list(self) -> None:
        async def empty_fetch(_config, *, session_file, **_kwargs):
            return FetchResult(candidates=[], scanned=0)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proxies.txt"
            output.write_text("last-known-good\n", encoding="utf-8")

            with patch("tg_proxy_search.update_public_proxies.fetch", new=empty_fetch):
                with self.assertRaisesRegex(RuntimeError, "returned no proxies"):
                    await update_public_proxies("/tmp/test.session", output)

            self.assertEqual(output.read_text(encoding="utf-8"), "last-known-good\n")

    async def test_invalid_merged_list_is_not_published(self) -> None:
        async def successful_fetch(_config, *, session_file, **_kwargs):
            return FetchResult(
                candidates=[Proxy("new.example", 443, "new-secret")],
                scanned=1,
            )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proxies.txt"
            output.write_text("not-a-proxy-url\n", encoding="utf-8")

            with patch("tg_proxy_search.update_public_proxies.fetch", new=successful_fetch):
                with self.assertRaisesRegex(ValueError, "invalid proxy URL at line 2"):
                    await update_public_proxies("/tmp/test.session", output)

            self.assertEqual(output.read_text(encoding="utf-8"), "not-a-proxy-url\n")


if __name__ == "__main__":
    unittest.main()
