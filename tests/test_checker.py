from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from tg_proxy_search.checker import check_proxy
from tg_proxy_search.models import Proxy


class CheckProxyLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_mtproto_check_returns_elapsed_milliseconds(self) -> None:
        proxy = Proxy("proxy.example", 443, "00112233445566778899aabbccddeeff")

        mtproto_check = AsyncMock(return_value=True)
        with (
            patch("tg_proxy_search.checker.mtproto_check", new=mtproto_check),
            patch("tg_proxy_search.checker.time.perf_counter", side_effect=[10.0, 10.0879]),
        ):
            latency = await check_proxy(proxy, api_id=1, api_hash="hash", timeout=15)

        self.assertEqual(latency, 87)
        mtproto_check.assert_awaited_once_with(
            "proxy.example", 443, "00112233445566778899aabbccddeeff", 1, "hash", 15,
        )

    async def test_failed_mtproto_check_returns_no_latency(self) -> None:
        proxy = Proxy("proxy.example", 443, "00112233445566778899aabbccddeeff")

        with patch("tg_proxy_search.checker.mtproto_check", new=AsyncMock(return_value=False)):
            latency = await check_proxy(proxy, api_id=1, api_hash="hash", timeout=15)

        self.assertIsNone(latency)

    async def test_successful_faketls_check_returns_elapsed_milliseconds(self) -> None:
        proxy = Proxy(
            "proxy.example",
            443,
            "ee00112233445566778899aabbccddeeff6578616d706c652e636f6d",
        )

        with (
            patch("tg_proxy_search.checker.faketls_check", new=AsyncMock(return_value=True)),
            patch("tg_proxy_search.checker.time.perf_counter", side_effect=[20.0, 20.0439]),
        ):
            latency = await check_proxy(proxy, api_id=1, api_hash="hash", timeout=15)

        self.assertEqual(latency, 43)


if __name__ == "__main__":
    unittest.main()
