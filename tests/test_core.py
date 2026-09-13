from __future__ import annotations

import unittest
from unittest.mock import patch

from tg_proxy_search.config import Config
from tg_proxy_search.core import check
from tg_proxy_search.models import Proxy


class CheckResultLatencyTests(unittest.IsolatedAsyncioTestCase):
    def config(self) -> Config:
        return Config(api_id=1, api_hash="hash", proxy_check_concurrency=1)

    async def test_successful_check_keeps_proxy_with_latency(self) -> None:
        proxy = Proxy("working.example", 443, "secret")

        async def successful_check(*_args: object) -> int:
            return 87

        with patch("tg_proxy_search.core.check_proxy", new=successful_check):
            result = await check(self.config(), candidates=[proxy])

        self.assertEqual(result.working[0].proxy, proxy)
        self.assertEqual(result.working[0].latency_ms, 87)

    async def test_failed_check_has_no_working_proxy_with_latency(self) -> None:
        proxy = Proxy("failed.example", 443, "secret")

        async def failed_check(*_args: object) -> None:
            return None

        with patch("tg_proxy_search.core.check_proxy", new=failed_check):
            result = await check(self.config(), candidates=[proxy])

        self.assertEqual(result.working, [])

    async def test_retry_uses_latency_of_successful_attempt(self) -> None:
        proxy = Proxy("retry.example", 443, "secret")
        attempts = iter([None, 143])

        async def retrying_check(*_args: object) -> int | None:
            return next(attempts)

        with patch("tg_proxy_search.core.check_proxy", new=retrying_check):
            result = await check(self.config(), candidates=[proxy])

        self.assertEqual(result.working[0].latency_ms, 143)

    async def test_working_proxies_are_sorted_by_latency(self) -> None:
        slow = Proxy("slow.example", 443, "secret")
        fast = Proxy("fast.example", 443, "secret")
        latencies = iter([291, 87])

        async def successful_check(*_args: object) -> int:
            return next(latencies)

        with patch("tg_proxy_search.core.check_proxy", new=successful_check):
            result = await check(self.config(), candidates=[slow, fast])

        self.assertEqual([item.proxy for item in result.working], [fast, slow])
        self.assertEqual([item.latency_ms for item in result.working], [87, 291])

    async def test_targeted_result_is_sorted_by_latency(self) -> None:
        slow = Proxy("slow.example", 443, "secret")
        fast = Proxy("fast.example", 443, "secret")
        latencies = iter([291, 87])

        async def successful_check(*_args: object) -> int:
            return next(latencies)

        with patch("tg_proxy_search.core.check_proxy", new=successful_check):
            result = await check(self.config(), candidates=[slow, fast], target_working=2)

        self.assertEqual([item.proxy for item in result.working], [fast, slow])


if __name__ == "__main__":
    unittest.main()
