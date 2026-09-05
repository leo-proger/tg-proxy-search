from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main
import tg_proxy_search as api


class PromptSettingsTests(unittest.TestCase):
    def prompt(self, answers: list[str], *, has_working_cache: bool) -> tuple[main.RunSettings, str]:
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            settings = main.prompt_settings(has_working_cache=has_working_cache)
        return settings, output.getvalue()

    def test_public_source_never_shows_cache_mode(self) -> None:
        settings, output = self.prompt(["2", "2"], has_working_cache=True)

        self.assertEqual(settings.source, main.SOURCE_PUBLIC_LIST)
        self.assertEqual(settings.mode, main.MODE_CHECK_ALL)
        self.assertIsNone(settings.target_working)
        self.assertIsNone(settings.since_hours)
        self.assertNotIn("Перепроверить", output)

    def test_public_source_can_limit_number_of_successful_proxies(self) -> None:
        settings, _output = self.prompt(["2", "1", "5"], has_working_cache=False)

        self.assertEqual(settings.source, main.SOURCE_PUBLIC_LIST)
        self.assertEqual(settings.mode, main.MODE_FIND_TARGET)
        self.assertEqual(settings.target_working, 5)

    def test_telegram_source_hides_cache_mode_without_working_cache(self) -> None:
        settings, output = self.prompt(["1", "2", "24"], has_working_cache=False)

        self.assertEqual(settings.source, main.SOURCE_TELEGRAM)
        self.assertEqual(settings.mode, main.MODE_CHECK_ALL)
        self.assertEqual(settings.since_hours, 24)
        self.assertNotIn("Перепроверить", output)

    def test_telegram_source_shows_cache_mode_when_working_cache_exists(self) -> None:
        settings, output = self.prompt(["1", "3"], has_working_cache=True)

        self.assertEqual(settings.source, main.SOURCE_TELEGRAM)
        self.assertEqual(settings.mode, main.MODE_RECHECK_CACHE)
        self.assertIn("Перепроверить", output)


class RunSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_source_downloads_fresh_candidates_and_checks_them(self) -> None:
        public_proxy = api.Proxy("public.example", 443, "secret")
        checked_candidates: list[api.Proxy] = []

        async def download_public(_config: api.Config) -> list[api.Proxy]:
            return [public_proxy]

        async def reject_telegram_fetch(*_args, **_kwargs):
            raise AssertionError("Telegram fetch must not run for the public source")

        async def check_candidates(
            _config: api.Config,
            _settings: main.RunSettings,
            *,
            candidates: list[api.Proxy] | None = None,
        ) -> api.CheckResult:
            checked_candidates.extend(candidates or [])
            return api.CheckResult(working=[], total=len(candidates or []), checked=len(candidates or []))

        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=main.MODE_CHECK_ALL,
            target_working=None,
            since_hours=None,
        )
        config = api.Config(api_id=1, api_hash="hash")

        with (
            patch("main._run_public_fetch", new=download_public),
            patch("main._run_fetch", new=reject_telegram_fetch),
            patch("main._run_check", new=check_candidates),
            redirect_stdout(io.StringIO()),
        ):
            await main.run(settings, config=config)

        self.assertEqual(checked_candidates, [public_proxy])

    async def test_public_source_reports_when_target_is_not_met(self) -> None:
        public_proxy = api.Proxy("public.example", 443, "secret")

        async def download_public(_config: api.Config) -> list[api.Proxy]:
            return [public_proxy]

        async def check_candidates(
            _config: api.Config,
            _settings: main.RunSettings,
            *,
            candidates: list[api.Proxy] | None = None,
        ) -> api.CheckResult:
            return api.CheckResult(working=[public_proxy], target=3, total=1, checked=1)

        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=main.MODE_FIND_TARGET,
            target_working=3,
            since_hours=None,
        )
        output = io.StringIO()

        with (
            patch("main._run_public_fetch", new=download_public),
            patch("main._run_check", new=check_candidates),
            redirect_stdout(output),
        ):
            await main.run(settings, config=api.Config(api_id=1, api_hash="hash"))

        self.assertIn("Найдено только 1 из 3", output.getvalue())


if __name__ == "__main__":
    unittest.main()
