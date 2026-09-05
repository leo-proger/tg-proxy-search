from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tg_proxy_search.models import Proxy
from tg_proxy_search.public_list import (
    merge_proxy_urls,
    read_proxy_urls,
    validate_proxy_urls,
    write_proxy_urls,
)


def proxy(server: str) -> Proxy:
    return Proxy(server=server, port=443, secret=f"secret-{server}")


class MergeProxyUrlsTests(unittest.TestCase):
    def test_new_urls_precede_retained_old_urls_without_duplicates(self) -> None:
        new = [proxy("new.example"), proxy("duplicate.example")]
        old = [
            "tg://proxy?server=duplicate.example&port=443&secret=secret-duplicate.example",
            "tg://proxy?server=old.example&port=443&secret=secret-old.example",
        ]

        self.assertEqual(
            merge_proxy_urls(new, old),
            [
                "tg://proxy?server=new.example&port=443&secret=secret-new.example",
                "tg://proxy?server=duplicate.example&port=443&secret=secret-duplicate.example",
                "tg://proxy?server=old.example&port=443&secret=secret-old.example",
            ],
        )

    def test_oldest_urls_are_trimmed_at_limit(self) -> None:
        new = [proxy("new.example")]
        old = [f"tg://proxy?server=old-{index}.example&port=443&secret={index}" for index in range(1000)]

        result = merge_proxy_urls(new, old, limit=1000)

        self.assertEqual(len(result), 1000)
        self.assertEqual(result[0], "tg://proxy?server=new.example&port=443&secret=secret-new.example")
        self.assertNotIn("tg://proxy?server=old-999.example&port=443&secret=999", result)

    def test_non_positive_limit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit must be at least 1"):
            merge_proxy_urls([proxy("new.example")], [], limit=0)


class ProxyUrlFileTests(unittest.TestCase):
    def test_missing_file_is_an_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.txt"

            self.assertEqual(read_proxy_urls(path), [])

    def test_read_ignores_blank_lines_and_surrounding_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.txt"
            path.write_text("  first\n\nsecond  \n", encoding="utf-8")

            self.assertEqual(read_proxy_urls(path), ["first", "second"])

    def test_write_replaces_contents_with_one_url_per_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.txt"
            path.write_text("stale\n", encoding="utf-8")

            write_proxy_urls(path, ["first", "second"])

            self.assertEqual(path.read_text(encoding="utf-8"), "first\nsecond\n")


class ValidateProxyUrlsTests(unittest.TestCase):
    def test_valid_proxy_url_is_accepted(self) -> None:
        validate_proxy_urls(["tg://proxy?server=proxy.example&port=443&secret=abc123"])

    def test_empty_list_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            validate_proxy_urls([])

    def test_list_larger_than_limit_is_rejected(self) -> None:
        urls = [f"tg://proxy?server={index}.example&port=443&secret={index}" for index in range(1001)]

        with self.assertRaisesRegex(ValueError, "more than 1000"):
            validate_proxy_urls(urls)

    def test_duplicate_urls_are_rejected(self) -> None:
        url = "tg://proxy?server=proxy.example&port=443&secret=abc123"

        with self.assertRaisesRegex(ValueError, "duplicate proxy URLs"):
            validate_proxy_urls([url, url])

    def test_url_without_required_parameters_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid proxy URL at line 1"):
            validate_proxy_urls(["tg://proxy?server=proxy.example&port=443"])

    def test_url_with_invalid_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid proxy URL at line 1"):
            validate_proxy_urls(["tg://proxy?server=proxy.example&port=not-a-port&secret=abc123"])


if __name__ == "__main__":
    unittest.main()
