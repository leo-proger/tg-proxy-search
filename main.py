"""
Интерактивный поиск MTProto-прокси.

Выберите режим:
  1. Найти N рабочих прокси.
  2. Взять все прокси за последние X часов.
  3. Оба условия — до N рабочих за последние X часов.

Этапы: включить ВПН → собрать прокси → выключить ВПН → проверить.
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

@dataclass
class RunSettings:
    mode: int
    target_working: int | None  # N (режимы 1, 3)
    since_hours: float | None   # X (режимы 2, 3)


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


def prompt_settings() -> RunSettings:
    print(f"{C.BOLD}Выберите режим:{C.RST}")
    print(f"  {C.BOLD}1{C.RST}  Найти N рабочих прокси")
    print(f"  {C.BOLD}2{C.RST}  Взять все прокси за последние X часов")
    print(f"  {C.BOLD}3{C.RST}  Оба условия — до N рабочих за последние X часов\n")

    while True:
        choice = input("Режим [1/2/3]: ").strip()
        if choice in ("1", "2", "3"):
            mode = int(choice)
            break
        print(f"{C.FAIL}  Введите 1, 2 или 3.{C.RST}")

    target_working: int | None = None
    since_hours: float | None = None
    if mode in (1, 3):
        target_working = _ask_int("Сколько рабочих прокси найти? ")
    if mode in (2, 3):
        since_hours = _ask_float("За сколько последних часов брать посты? ")

    print()
    return RunSettings(mode=mode, target_working=target_working, since_hours=since_hours)


# ── URL helper ────────────────────────────────────────────────────────────────

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
    print(f"{C.BOLD}── Шаг 1: сбор кандидатов{C.RST}")
    print(f"{C.WARN}  ВПН должен быть ВКЛЮЧЁН (Telegram должен быть доступен){C.RST}")
    input(f"{C.DIM}  Включите ВПН и нажмите Enter...{C.RST} ")
    print()

    if settings.since_hours is not None:
        print(f"{C.DIM}  Читаем @{config.channel}, посты за последние {settings.since_hours:g}ч{C.RST}\n")
    else:
        print(f"{C.DIM}  Читаем @{config.channel}{C.RST}\n")

    def on_progress(event: api.FetchProgress) -> None:
        print(f"\r  Просмотрено: {event.scanned}  |  найдено: {event.found}", end="", flush=True)

    result = await api.fetch(config, since_hours=settings.since_hours, on_progress=on_progress)

    print(f"\r  {C.OK}Кандидатов найдено: {result.found}{C.RST}  {C.DIM}(просмотрено {result.scanned} постов){C.RST}")
    if result.limit_reached:
        print(f"{C.WARN}  ⚠ Достигнут лимит сканирования ({config.max_scan_messages} постов) — "
              f"увеличьте MAX_SCAN_MESSAGES в .env чтобы смотреть глубже.{C.RST}")
    if result.found == 0:
        window = f" за последние {settings.since_hours:g}ч" if settings.since_hours else ""
        print(f"{C.WARN}  ⚠ Прокси-кандидаты не найдены{window}.{C.RST}")
    print()
    return result


async def _run_check(config: api.Config, settings: RunSettings) -> api.CheckResult:
    print(f"{C.BOLD}── Шаг 2: проверка прокси{C.RST}")
    print(f"{C.WARN}  ВПН должен быть ВЫКЛЮЧЕН (подключение идёт с вашего реального IP){C.RST}")
    target = settings.target_working
    target_label = str(target) if target is not None else "все"
    print(f"{C.DIM}  Цель: {target_label}  |  таймаут: {config.tcp_timeout:g}с{C.RST}\n")

    consecutive_fails = 0
    has_collapsed_line = False

    def on_event(event: api.ProxyChecked) -> None:
        nonlocal consecutive_fails, has_collapsed_line
        cached_tag = f" {C.DIM}(кэш){C.RST}" if event.from_cache else ""
        if event.ok:
            if has_collapsed_line:
                print()
                has_collapsed_line = False
            consecutive_fails = 0
            print(f"{C.OK}  ✓{C.RST} {event.proxy.server}:{event.proxy.port}{cached_tag}")
        else:
            consecutive_fails += 1
            if consecutive_fails <= 2:
                print(f"{C.FAIL}  ✗{C.RST} {event.proxy.server}:{event.proxy.port}{cached_tag}")
            else:
                print(
                    f"\r{C.DIM}  ...{event.checked}/{event.total} проверено, все нерабочие{C.RST}   ",
                    end="", flush=True,
                )
                has_collapsed_line = True

    result = await api.check(config, target_working=target, on_event=on_event)

    if has_collapsed_line:
        print()
    print(f"\n  {C.OK}Рабочих: {len(result.working)}{C.RST}  {C.DIM}(проверено {result.checked}/{result.total}){C.RST}")

    if target is not None and not result.target_met:
        print(f"{C.WARN}  ⚠ Найдено только {len(result.working)} из {target} запрошенных — "
              f"кандидаты закончились.{C.RST}")
    print()
    return result


# ── Оркестрация ───────────────────────────────────────────────────────────────

async def run(settings: RunSettings) -> None:
    config = api.Config.from_env()

    fetch_result = await _run_fetch(config, settings)
    if fetch_result.found == 0:
        return

    print("─" * 55)
    print(f"{C.WARN}Выключите ВПН и нажмите Enter для начала проверки...{C.RST}")
    await asyncio.get_running_loop().run_in_executor(None, input)
    print()

    check_result = await _run_check(config, settings)
    if not check_result.working:
        print(f"{C.WARN}  Рабочих прокси не найдено. Попробуйте расширить временной диапазон или увеличить N.{C.RST}")
        return

    print(f"{C.BOLD}── Результат{C.RST}  {C.DIM}(кликните ссылку чтобы добавить прокси в Telegram Desktop){C.RST}\n")
    for proxy in check_result.working:
        print(f"  {proxy.tg_link()}\n")

    if config.auto_add_to_telegram:
        await _auto_add_proxies(check_result.working)


if __name__ == "__main__":
    settings = prompt_settings()
    asyncio.run(run(settings))
