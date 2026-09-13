"""
Интерактивный поиск MTProto-прокси.

Сначала выберите источник: свежий парсинг Telegram-канала или публичный
proxies.txt. Затем выберите, сколько прокси проверить.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

import tg_proxy_search as api

load_dotenv()


class C:
    OK   = "\033[32m"
    FAIL = "\033[31m"
    WARN = "\033[33m"
    INFO = "\033[36m"
    DIM  = "\033[2m"
    BOLD = "\033[1m"
    RST  = "\033[0m"


# ── Выбор режима ──────────────────────────────────────────────────────────────

SOURCE_TELEGRAM = 1
SOURCE_PUBLIC_LIST = 2

MODE_FIND_TARGET = 1
MODE_CHECK_ALL = 2
MODE_RECHECK_CACHE = 3

@dataclass
class RunSettings:
    source: int
    mode: int
    target_working: int | None  # N (режим 1)
    since_hours: float | None   # X (режим 2)


def _ask_int(prompt: str, minimum: int = 1) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
            if value >= minimum:
                return value
        except ValueError:
            pass
        print(f"{C.FAIL}  Введите целое число ≥ {minimum}.{C.RST}")


def _ask_float(prompt: str, minimum: float = 0.0) -> float:
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            value = float(raw)
            if value > minimum:
                return value
        except ValueError:
            pass
        print(f"{C.FAIL}  Введите число > {minimum}.{C.RST}")


def _progress_bar(current: int, total: int, *, width: int = 24) -> str:
    safe_total = max(total, 1)
    displayed_current = min(max(current, 0), max(total, 0))
    ratio = displayed_current / safe_total
    filled = int(ratio * width)
    percent = int(ratio * 100)
    return f"[{'█' * filled}{'░' * (width - filled)}] {percent:3d}% {displayed_current}/{total}"


def _show_progress(label: str, current: int, total: int, *, suffix: str = "") -> None:
    details = f"  {suffix}" if suffix else ""
    print(
        f"\r  {C.INFO}{label:<13}{C.RST} {C.OK}{_progress_bar(current, total)}{C.RST}{details}\033[K",
        end="",
        flush=True,
    )


def prompt_settings(*, has_working_cache: bool = False) -> RunSettings:
    print(f"{C.BOLD}Откуда взять прокси?{C.RST}")
    print(f"  {C.BOLD}1{C.RST}  Спарсить свежие из Telegram-канала {C.DIM}(нужен VPN){C.RST}")
    print(f"  {C.BOLD}2{C.RST}  Скачать из публичного proxies.txt {C.DIM}(VPN не нужен){C.RST}")
    print(f"     {C.DIM}Список скачивается заново перед каждой проверкой{C.RST}\n")

    while True:
        choice = input("Источник [1/2]: ").strip()
        if choice in ("1", "2"):
            source = int(choice)
            break
        print(f"{C.FAIL}  Введите 1 или 2.{C.RST}")

    print(f"\n{C.BOLD}Что сделать?{C.RST}")
    print(f"  {C.BOLD}1{C.RST}  Найти N рабочих прокси")
    if source == SOURCE_TELEGRAM:
        print(f"  {C.BOLD}2{C.RST}  Проверить прокси из постов за последние X часов")
        if has_working_cache:
            print(f"  {C.BOLD}3{C.RST}  Перепроверить прокси из кэша {C.DIM}(VPN не нужен){C.RST}")
    else:
        print(f"  {C.BOLD}2{C.RST}  Проверить весь публичный список")
    print()

    valid_modes = {MODE_FIND_TARGET, MODE_CHECK_ALL}
    if source == SOURCE_TELEGRAM and has_working_cache:
        valid_modes.add(MODE_RECHECK_CACHE)
    choices = "/".join(str(mode) for mode in sorted(valid_modes))
    while True:
        choice = input(f"Действие [{choices}]: ").strip()
        if choice.isdigit() and int(choice) in valid_modes:
            mode = int(choice)
            break
        print(f"{C.FAIL}  Введите {', '.join(str(mode) for mode in sorted(valid_modes))}.{C.RST}")

    target_working: int | None = None
    since_hours: float | None = None
    if mode == MODE_FIND_TARGET:
        target_working = _ask_int("Сколько прокси найти? ")
    if source == SOURCE_TELEGRAM and mode == MODE_CHECK_ALL:
        since_hours = _ask_float("За сколько последних часов брать посты? ")

    print()
    return RunSettings(
        source=source,
        mode=mode,
        target_working=target_working,
        since_hours=since_hours,
    )


# ── Вспомогательная функция для URL ──────────────────────────────────────────

def _open_url(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    elif sys.platform == "win32":
        subprocess.run(["start", url], shell=True, check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


async def _auto_add_proxies(proxies: list[api.Proxy]) -> None:
    loop = asyncio.get_running_loop()
    print(f"\n{C.BOLD}── Добавление прокси в Telegram{C.RST}\n")
    for i, proxy in enumerate(proxies, 1):
        print(f"  [{i}/{len(proxies)}] {proxy.server}:{proxy.port}")
        await loop.run_in_executor(None, _open_url, proxy.tg_link())
        await loop.run_in_executor(None, input, "  Нажмите «Подключиться» в Telegram, затем Enter...")
        print()


# ── Фазы ─────────────────────────────────────────────────────────────────────

async def _run_fetch(config: api.Config, settings: RunSettings) -> api.FetchResult:
    print(f"{C.BOLD}── Шаг 1: парсится канал{C.RST}")
    print(f"{C.WARN}  VPN должен быть ВКЛЮЧЁН (Telegram должен быть доступен){C.RST}")
    input(f"{C.DIM}  Включите VPN и нажмите Enter...{C.RST} ")
    print()

    if settings.since_hours is not None:
        print(f"{C.DIM}  Парсится @{config.channel}, посты за последние {settings.since_hours:g}ч{C.RST}\n")
    else:
        print(f"{C.DIM}  Парсится @{config.channel}{C.RST}\n")

    def on_progress(event: api.FetchProgress) -> None:
        _show_progress(
            "Сканирование",
            event.scanned,
            config.max_scan_messages,
            suffix=f"найдено: {event.found}",
        )

    _show_progress("Сканирование", 0, config.max_scan_messages, suffix="найдено: 0")
    result = await api.fetch(config, since_hours=settings.since_hours, on_progress=on_progress)

    print()
    print(f"  {C.OK}Кандидатов найдено: {result.found}{C.RST}  {C.DIM}(просмотрено {result.scanned} постов){C.RST}")
    if result.limit_reached:
        print(f"{C.WARN}  ⚠ Лимит сканирования достигнут ({config.max_scan_messages} постов) — "
              f"увеличьте MAX_SCAN_MESSAGES в .env.{C.RST}")
    if result.found == 0:
        window = f" за последние {settings.since_hours:g}ч" if settings.since_hours else ""
        print(f"{C.WARN}  ⚠ Прокси-кандидаты не найдены{window}.{C.RST}")
    print()
    return result


async def _run_public_fetch(config: api.Config) -> list[api.Proxy]:
    print(f"{C.BOLD}── Шаг 1: скачивается публичный список{C.RST}")
    print(f"{C.DIM}  Источник: {api.PUBLIC_PROXY_LIST_URL}{C.RST}\n")
    _show_progress("Скачивание", 0, 1)
    candidates = await api.download_public_proxies(timeout=config.tcp_timeout)
    _show_progress("Скачивание", 1, 1, suffix=f"загружено: {len(candidates)}")
    print("\n")
    return candidates


async def _run_check(
    config: api.Config,
    settings: RunSettings,
    *,
    candidates: list[api.Proxy] | None = None,
) -> api.CheckResult:
    print(f"{C.BOLD}── Шаг 2: проверяется{C.RST}")
    print(f"{C.WARN}  VPN должен быть ВЫКЛЮЧЁН (подключение идёт с вашего реального IP){C.RST}")
    target = settings.target_working
    target_label = str(target) if target is not None else "все"
    print(f"{C.DIM}  Цель: {target_label}  |  таймаут: {config.tcp_timeout:g}с{C.RST}\n")

    return await _do_check(config, target_working=target, candidates=candidates)


async def _run_recheck(config: api.Config) -> api.CheckResult:
    print(f"{C.BOLD}── Перепроверяется кэш{C.RST}")
    print(f"{C.DIM}  VPN не нужен — проверка идёт с реального IP{C.RST}\n")

    return await _do_recheck(config)


async def _do_check(
    config: api.Config,
    *,
    target_working: int | None = None,
    candidates: list[api.Proxy] | None = None,
) -> api.CheckResult:
    def on_event(event: api.ProxyChecked) -> None:
        cached = "  кэш" if event.from_cache else ""
        if target_working is None:
            current, total = event.checked, event.total
            suffix = f"рабочих: {event.working}{cached}"
        else:
            current, total = event.working, target_working
            suffix = f"проверено: {event.checked}/{event.total}{cached}"
        _show_progress(
            "Проверка",
            current,
            total,
            suffix=suffix,
        )

    result = await api.check(config, candidates=candidates, target_working=target_working, on_event=on_event)

    if result.checked:
        print()
    print(f"\n  {C.OK}Рабочих: {len(result.working)}{C.RST}  {C.DIM}(проверено {result.checked}/{result.total}){C.RST}\n")
    return result


async def _do_recheck(config: api.Config) -> api.CheckResult:
    def on_event(event: api.ProxyChecked) -> None:
        _show_progress(
            "Перепроверка",
            event.checked,
            event.total,
            suffix=f"рабочих: {event.working}",
        )

    result = await api.recheck(config, on_event=on_event)

    if result.checked:
        print()
    if result.total == 0:
        print(f"{C.WARN}  Кэш пустой — сначала запустите режим 1 или 2.{C.RST}\n")
    else:
        print(f"\n  {C.OK}Рабочих: {len(result.working)}{C.RST}  {C.DIM}(проверено {result.checked}/{result.total}){C.RST}\n")
    return result


# ── Оркестрация ───────────────────────────────────────────────────────────────

async def run(settings: RunSettings, *, config: api.Config | None = None) -> None:
    config = config or api.Config.from_env()

    if settings.mode == MODE_RECHECK_CACHE:
        check_result = await _run_recheck(config)
        working = check_result.working
    elif settings.source == SOURCE_PUBLIC_LIST:
        candidates = await _run_public_fetch(config)
        check_result = await _run_check(config, settings, candidates=candidates)
        working = check_result.working
    else:
        fetch_result = await _run_fetch(config, settings)
        if fetch_result.found == 0:
            return

        print("─" * 55)
        print(f"{C.WARN}Выключите VPN и нажмите Enter для начала проверки...{C.RST}")
        await asyncio.get_running_loop().run_in_executor(None, input)
        print()

        check_result = await _run_check(config, settings)
        working = check_result.working

    if settings.target_working is not None and len(working) < settings.target_working:
        print(f"{C.WARN}  ⚠ Найдено только {len(working)} из {settings.target_working} — "
              f"кандидаты закончились.{C.RST}\n")

    if not working:
        if settings.mode != 3:
            print(f"{C.WARN}  Рабочих прокси не найдено. Попробуйте расширить диапазон или увеличить N.{C.RST}")
        return

    print(f"{C.BOLD}── Результат{C.RST}  {C.DIM}(ссылки вставлять в браузер){C.RST}\n")
    for proxy in working:
        print(f"   {proxy.tg_link()}")

    if config.auto_add_to_telegram:
        await _auto_add_proxies(working)


async def interactive_loop(config: api.Config | None = None) -> None:
    config = config or api.Config.from_env()
    while True:
        settings = prompt_settings(has_working_cache=api.has_working_cache(config))
        await run(settings, config=config)

        print(f"\n{C.BOLD}Нажмите Enter, чтобы вернуться в меню, или q, чтобы выйти.{C.RST}")
        choice = input(f"{C.DIM}> {C.RST}").strip().lower()
        if choice == "q":
            return
        print("\n" + "─" * 55 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(interactive_loop())
    except KeyboardInterrupt:
        print(f"\n{C.WARN}  Прервано.{C.RST}")
    except RuntimeError as e:
        print(f"\n{C.FAIL}  Ошибка: {e}{C.RST}")
        if "Session not authorized" in str(e):
            print(f"{C.DIM}  Запустите авторизацию из README и повторите.{C.RST}")
    except Exception as e:
        print(f"\n{C.FAIL}  Неожиданная ошибка: {e}{C.RST}")
