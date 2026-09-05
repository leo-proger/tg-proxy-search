from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tg_proxy_search.cache import ProxyCache
from tg_proxy_search.config import Config
from tg_proxy_search.core import has_working_cache
from tg_proxy_search.models import Proxy


def config_with_cache(path: Path) -> Config:
    return Config(api_id=1, api_hash="hash", check_cache_file=str(path))


class HasWorkingCacheTests(unittest.TestCase):
    def test_missing_cache_is_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = config_with_cache(Path(directory) / "missing.json")

            self.assertFalse(has_working_cache(config))

    def test_cache_with_only_failed_entries_is_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            config = config_with_cache(path)
            cache = ProxyCache(path=str(path), working_recheck_hours=48, failed_recheck_hours=24)
            cache.set(Proxy("failed.example", 443, "secret"), False)
            cache.save()

            self.assertFalse(has_working_cache(config))

    def test_cache_with_working_entry_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            config = config_with_cache(path)
            cache = ProxyCache(path=str(path), working_recheck_hours=48, failed_recheck_hours=24)
            cache.set(Proxy("working.example", 443, "secret"), True)
            cache.save()

            self.assertTrue(has_working_cache(config))

    def test_malformed_cache_is_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text("not-json", encoding="utf-8")

            self.assertFalse(has_working_cache(config_with_cache(path)))

    def test_cache_with_invalid_schema_is_not_available(self) -> None:
        invalid_caches = (
            "[]",
            "null",
            '{"proxy": null}',
            '{"proxy": {"server": "example.com"}}',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            config = config_with_cache(path)

            for raw_cache in invalid_caches:
                with self.subTest(raw_cache=raw_cache):
                    path.write_text(raw_cache, encoding="utf-8")
                    self.assertFalse(has_working_cache(config))


if __name__ == "__main__":
    unittest.main()
