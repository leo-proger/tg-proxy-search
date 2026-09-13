from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main
import tg_proxy_search as api


class ProgressBarTests(unittest.TestCase):
    def test_bar_shows_filled_share_percentage_and_count(self) -> None:
        renderer = getattr(main, "_progress_bar", None)
        self.assertIsNotNone(renderer)

        self.assertEqual(renderer(3, 10, width=10), "[███░░░░░░░]  30% 3/10")

    def test_bar_caps_completed_count_at_total(self) -> None:
        self.assertEqual(main._progress_bar(12, 10, width=10), "[██████████] 100% 10/10")


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

    def test_public_source_does_not_offer_local_list_update(self) -> None:
        settings, output = self.prompt(["2", "3", "2"], has_working_cache=False)

        self.assertEqual(settings.source, main.SOURCE_PUBLIC_LIST)
        self.assertEqual(settings.mode, main.MODE_CHECK_ALL)
        self.assertNotIn("Обновить локальный proxies.txt", output)
        self.assertIn("Введите 1, 2.", output)

    def test_public_source_explains_that_it_downloads_a_fresh_list(self) -> None:
        _settings, output = self.prompt(["2", "2"], has_working_cache=False)

        self.assertIn("Список скачивается заново перед каждой проверкой", output)

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


class InteractiveLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_returns_to_menu_and_q_exits(self) -> None:
        interactive_loop = getattr(main, "interactive_loop", None)
        self.assertIsNotNone(interactive_loop)

        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=main.MODE_CHECK_ALL,
            target_working=None,
            since_hours=None,
        )
        completed: list[main.RunSettings] = []

        async def complete_run(selected: main.RunSettings, *, config: api.Config) -> None:
            completed.append(selected)

        with (
            patch("main.prompt_settings", side_effect=[settings, settings]),
            patch("main.api.has_working_cache", return_value=False),
            patch("main.run", new=complete_run),
            patch("builtins.input", side_effect=["", "q"]),
            redirect_stdout(output := io.StringIO()),
        ):
            await interactive_loop(api.Config(api_id=1, api_hash="hash"))

        self.assertEqual(completed, [settings, settings])
        self.assertIn("Нажмите Enter, чтобы вернуться в меню", output.getvalue())


class CheckProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_redraws_progress_until_all_candidates_are_done(self) -> None:
        failed = api.Proxy("failed.example", 443, "failed")
        working = api.Proxy("working.example", 443, "working")

        async def check_with_events(
            _config: api.Config,
            *,
            candidates=None,
            target_working=None,
            on_event=None,
        ) -> api.CheckResult:
            on_event(api.ProxyChecked(failed, False, checked=1, working=0, total=2))
            on_event(api.ProxyChecked(working, True, checked=2, working=1, total=2))
            return api.CheckResult(working=[working], total=2, checked=2)

        output = io.StringIO()
        with patch("main.api.check", new=check_with_events), redirect_stdout(output):
            await main._do_check(
                api.Config(api_id=1, api_hash="hash"),
                candidates=[failed, working],
            )

        rendered = output.getvalue()
        self.assertIn("50% 1/2", rendered)
        self.assertIn("100% 2/2", rendered)

    async def test_targeted_check_fills_bar_when_requested_working_count_is_found(self) -> None:
        working = api.Proxy("working.example", 443, "working")

        async def check_with_target(
            _config: api.Config,
            *,
            candidates=None,
            target_working=None,
            on_event=None,
        ) -> api.CheckResult:
            on_event(api.ProxyChecked(working, True, checked=7, working=1, total=50))
            return api.CheckResult(working=[working], target=1, total=50, checked=7)

        output = io.StringIO()
        with patch("main.api.check", new=check_with_target), redirect_stdout(output):
            await main._do_check(
                api.Config(api_id=1, api_hash="hash"),
                candidates=[working],
                target_working=1,
            )

        rendered = output.getvalue()
        self.assertIn("100% 1/1", rendered)
        self.assertIn("проверено: 7/50", rendered)


class PhaseProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_download_moves_from_empty_to_full_bar(self) -> None:
        proxy = api.Proxy("public.example", 443, "secret")

        with (
            patch("main.api.download_public_proxies", return_value=[proxy]),
            redirect_stdout(output := io.StringIO()),
        ):
            await main._run_public_fetch(api.Config(api_id=1, api_hash="hash"))

        rendered = output.getvalue()
        self.assertIn("0% 0/1", rendered)
        self.assertIn("100% 1/1", rendered)

    async def test_telegram_fetch_shows_scan_limit_progress(self) -> None:
        proxy = api.Proxy("telegram.example", 443, "secret")

        async def fetch_with_progress(_config, *, since_hours, on_progress):
            on_progress(api.FetchProgress(found=1, scanned=250))
            return api.FetchResult(candidates=[proxy], scanned=250)

        settings = main.RunSettings(
            source=main.SOURCE_TELEGRAM,
            mode=main.MODE_FIND_TARGET,
            target_working=1,
            since_hours=None,
        )
        with (
            patch("builtins.input", return_value=""),
            patch("main.api.fetch", new=fetch_with_progress),
            redirect_stdout(output := io.StringIO()),
        ):
            await main._run_fetch(api.Config(api_id=1, api_hash="hash"), settings)

        rendered = output.getvalue()
        self.assertIn("Сканирование", rendered)
        self.assertIn("25% 250/1000", rendered)
        self.assertIn("найдено: 1", rendered)


if __name__ == "__main__":
    unittest.main()
