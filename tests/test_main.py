from __future__ import annotations

import io
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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
    def prompt(self, answers: list[str]) -> tuple[main.RunSettings, str]:
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            settings = main.prompt_settings()
        return settings, output.getvalue()

    def test_public_source_rejects_check_all_and_offers_only_find_or_update(self) -> None:
        settings, output = self.prompt(["2", "2"])

        self.assertEqual(settings.source, main.SOURCE_PUBLIC_LIST)
        self.assertEqual(settings.mode, main.MODE_UPDATE_PUBLIC_LIST)
        self.assertNotEqual(settings.mode, main.MODE_CHECK_ALL)
        self.assertNotIn("Проверить весь публичный список", output)
        self.assertNotIn("Перепроверить", output)

    def test_public_source_can_limit_number_of_successful_proxies(self) -> None:
        settings, _output = self.prompt(["2", "1", "5"])

        self.assertEqual(settings.source, main.SOURCE_PUBLIC_LIST)
        self.assertEqual(settings.mode, main.MODE_FIND_TARGET)
        self.assertEqual(settings.target_working, 5)

    def test_public_source_can_select_local_list_update(self) -> None:
        settings, output = self.prompt(["2", "2"])

        self.assertEqual(settings.source, main.SOURCE_PUBLIC_LIST)
        self.assertEqual(settings.mode, main.MODE_UPDATE_PUBLIC_LIST)
        self.assertIn("Обновить локальный proxies.txt", output)

    def test_public_source_describes_the_local_list(self) -> None:
        _settings, output = self.prompt(["2", "1", "1"])

        self.assertIn("Использовать публичный proxies.txt", output)
        self.assertNotIn("Скачать из публичного proxies.txt", output)

    def test_missing_local_list_has_clear_update_status(self) -> None:
        formatter = getattr(main, "_format_last_updated", None)
        self.assertIsNotNone(formatter)

        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "proxies.txt"
            self.assertEqual(formatter(missing), "файл отсутствует")

class RunSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_source_rejects_check_all_mode_even_when_constructed_directly(self) -> None:
        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=main.MODE_CHECK_ALL,
            target_working=None,
            since_hours=None,
        )

        with (
            patch("main._run_public_fetch", side_effect=AssertionError("public fetch must not run")),
            self.assertRaisesRegex(ValueError, "недоступен для публичного списка"),
        ):
            await main.run(settings, config=api.Config(api_id=1, api_hash="hash"))

    async def test_update_mode_replaces_local_public_list_without_checking(self) -> None:
        async def update_local(path: Path, *, timeout: float) -> int:
            path.write_text("fresh\n", encoding="utf-8")
            return 1

        async def no_candidates(_config: api.Config) -> list[api.Proxy]:
            return []

        async def no_results(*_args, **_kwargs) -> api.CheckResult:
            return api.CheckResult()

        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=3,
            target_working=None,
            since_hours=None,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.txt"
            with (
                patch("main.PUBLIC_PROXY_LIST_PATH", path, create=True),
                patch("main.api.update_local_public_proxies", new=update_local),
                patch("main._run_public_fetch", new=no_candidates),
                patch("main._run_check", new=no_results),
                redirect_stdout(io.StringIO()),
            ):
                await main.run(settings, config=api.Config(api_id=1, api_hash="hash"))

            self.assertTrue(path.exists(), "update mode did not create proxies.txt")
            self.assertEqual(path.read_text(encoding="utf-8"), "fresh\n")

    async def test_public_source_loads_candidates_from_local_file_without_download(self) -> None:
        local_proxy = api.Proxy("local.example", 443, "local-secret")

        async def reject_remote_download(*_args, **_kwargs) -> list[api.Proxy]:
            raise AssertionError("ordinary public checks must not download proxies.txt")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.txt"
            original_contents = f"{local_proxy.tg_link()}\n"
            path.write_text(original_contents, encoding="utf-8")
            with (
                patch("main.PUBLIC_PROXY_LIST_PATH", path),
                patch("main.api.download_public_proxies", new=reject_remote_download),
                redirect_stdout(io.StringIO()),
            ):
                candidates = await main._run_public_fetch(api.Config(api_id=1, api_hash="hash"))

            self.assertEqual(path.read_text(encoding="utf-8"), original_contents)

        self.assertEqual(candidates, [local_proxy])

    async def test_public_source_waits_for_vpn_to_be_disabled_before_checking(self) -> None:
        public_proxy = api.Proxy("local.example", 443, "local-secret")
        confirmed = False

        async def local_candidates(_config: api.Config) -> list[api.Proxy]:
            return [public_proxy]

        async def check_after_confirmation(
            _config: api.Config,
            _settings: main.RunSettings,
            *,
            candidates: list[api.Proxy] | None = None,
        ) -> api.CheckResult:
            self.assertTrue(confirmed, "checking started before VPN confirmation")
            self.assertEqual(candidates, [public_proxy])
            return api.CheckResult(working=[], total=1, checked=1)

        def confirm_vpn_disabled(*_args: object, **_kwargs: object) -> str:
            nonlocal confirmed
            confirmed = True
            return ""

        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=main.MODE_FIND_TARGET,
            target_working=1,
            since_hours=None,
        )

        with (
            patch("main._run_public_fetch", new=local_candidates),
            patch("main._run_check", new=check_after_confirmation),
            patch("builtins.input", new=confirm_vpn_disabled),
            redirect_stdout(output := io.StringIO()),
        ):
            await main.run(settings, config=api.Config(api_id=1, api_hash="hash"))

        self.assertTrue(confirmed)
        self.assertIn("Выключите VPN и нажмите Enter для начала проверки", output.getvalue())

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
            return api.CheckResult(
                working=[api.CheckedProxy(public_proxy, 87)],
                target=3,
                total=1,
                checked=1,
            )

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
            patch("builtins.input", return_value=""),
            redirect_stdout(output),
        ):
            await main.run(settings, config=api.Config(api_id=1, api_hash="hash"))

        self.assertIn("Найдено только 1 из 3", output.getvalue())

    async def test_final_result_displays_unmodified_urls_with_latency(self) -> None:
        fast = api.Proxy("fast.example", 443, "fast-secret")
        slow = api.Proxy("slow.example", 443, "slow-secret")
        results = [api.CheckedProxy(fast, 87), api.CheckedProxy(slow, 291)]

        async def local_candidates(_config: api.Config) -> list[api.Proxy]:
            return [fast, slow]

        async def checked_results(*_args: object, **_kwargs: object) -> api.CheckResult:
            return api.CheckResult(working=results, total=2, checked=2)

        async def vpn_is_disabled() -> None:
            return None

        settings = main.RunSettings(
            source=main.SOURCE_PUBLIC_LIST,
            mode=main.MODE_FIND_TARGET,
            target_working=2,
            since_hours=None,
        )

        with (
            patch("main._run_public_fetch", new=local_candidates),
            patch("main._wait_for_vpn_disabled", new=vpn_is_disabled),
            patch("main._run_check", new=checked_results),
            redirect_stdout(output := io.StringIO()),
        ):
            await main.run(settings, config=api.Config(api_id=1, api_hash="hash"))

        rendered = output.getvalue()
        self.assertIn(f"{fast.tg_link()} (87мс)", rendered)
        self.assertIn(f"{slow.tg_link()} (291мс)", rendered)
        self.assertLess(rendered.index(fast.tg_link()), rendered.index(slow.tg_link()))
        self.assertNotIn("мс", fast.tg_link())


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
    async def test_local_public_list_load_moves_from_empty_to_full_bar(self) -> None:
        proxy = api.Proxy("public.example", 443, "secret")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.txt"
            path.write_text(f"{proxy.tg_link()}\n", encoding="utf-8")
            with (
                patch("main.PUBLIC_PROXY_LIST_PATH", path),
                redirect_stdout(output := io.StringIO()),
            ):
                await main._run_public_fetch(api.Config(api_id=1, api_hash="hash"))

        rendered = output.getvalue()
        self.assertIn("0% 0/1", rendered)
        self.assertIn("100% 1/1", rendered)

    async def test_local_list_update_moves_from_empty_to_full_bar(self) -> None:
        async def update_local(_path: Path, *, timeout: float) -> int:
            return 25

        with (
            patch("main.api.update_local_public_proxies", new=update_local),
            redirect_stdout(output := io.StringIO()),
        ):
            await main._run_public_update(api.Config(api_id=1, api_hash="hash"))

        rendered = output.getvalue()
        self.assertIn("0% 0/1", rendered)
        self.assertIn("100% 1/1", rendered)
        self.assertIn("сохранено: 25", rendered)

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
