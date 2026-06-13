"""
Интерактивный поиск MTProto-прокси.

Выберите режим:
  1. Найти N рабочих прокси (парсится партиями по 50 постов).
  2. Взять все прокси за последние X часов.
  3. Оба условия — до N рабочих за последние X часов.

Этапы: включить VPN → парсится канал → выключить VPN → проверяются прокси.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

import tg_proxy_search as api

load_dotenv()

BATCH_SIZE = 50  # постов за одну итерацию в режиме пагинации


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

def _prompt_vpn_on(found: int = 0, target: int | None = None) -> None:
    print("─" * 55)
    if found > 0 and target is not None:
        print(f"{C.WARN}  Найдено {found}/{target}. Включите VPN и нажмите Enter для следующей партии...{C.RST}")
    else:
        print(f"{C.WARN}  Включите VPN и нажмите Enter...{C.RST}")
    input()
    print()


def _prompt_vpn_off() -> None:
    print("─" * 55)
    print(f"{C.WARN}  Выключите VPN и нажмите Enter для проверки...{C.RST}")
    input()
    print()


async def _fetch_batch(
    config: api.Config,
    settings: RunSettings,
    offset_id: int = 0,
    batch_size: int | None = None,
) -> api.FetchResult:
    label = f"за последние {settings.since_hours:g}ч" if settings.since_hours else f"канал @{config.channel}"
    print(f"{C.BOLD}── Парсится{C.RST} {C.DIM}{label}{C.RST}")

    def on_progress(event: api.FetchProgress) -> None:
        print(f"\r  Гуглится: {event.scanned} постов  |  найдено: {event.found}", end="", flush=True)

    result = await api.fetch(
        config,
        since_hours=settings.since_hours,
        on_progress=on_progress,
        offset_id=offset_id,
        batch_size=batch_size,
    )

    print(f"\r  {C.OK}Кандидатов: {result.found}{C.RST}  {C.DIM}(просмотрено {result.scanned} постов){C.RST}")
    if result.limit_reached:
        print(f"{C.WARN}  ⚠ Лимит сканирования достигнут ({config.max_scan_messages} постов) — "
              f"увеличьте MAX_SCAN_MESSAGES в .env.{C.RST}")
    if result.found == 0:
        window = f" за последние {settings.since_hours:g}ч" if settings.since_hours else ""
        print(f"{C.WARN}  ⚠ Прокси-кандидаты не найдены{window}.{C.RST}")
    print()
    return result


async def _check_batch(
    config: api.Config,
    candidates: list[api.Proxy],
    target_working: int | None,
) -> api.CheckResult:
    target_label = str(target_working) if target_working is not None else "все"
    print(f"{C.BOLD}── Проверяется{C.RST}  {C.DIM}цель: {target_label}  |  таймаут: {config.tcp_timeout:g}с{C.RST}\n")

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
                    f"\r{C.DIM}  ...{event.checked}/{event.total} проверено, нерабочие{C.RST}   ",
                    end="", flush=True,
                )
                has_collapsed_line = True

    result = await api.check(config, candidates=candidates, target_working=target_working, on_event=on_event)

    if has_collapsed_line:
        print()
    print(f"\n  {C.OK}Рабочих: {len(result.working)}{C.RST}  {C.DIM}(проверено {result.checked}/{result.total}){C.RST}\n")
    return result


# ── Оркестрация ───────────────────────────────────────────────────────────────

async def _run_paginated(config: api.Config, settings: RunSettings) -> list[api.Proxy]:
    """Режим 1: парсим партиями по BATCH_SIZE постов, проверяем каждую, пока не наберём N рабочих."""
    target = settings.target_working
    assert target is not None
    working: list[api.Proxy] = []
    offset_id = 0
    batch = 0

    while len(working) < target:
        batch += 1
        _prompt_vpn_on(found=len(working), target=target if batch > 1 else None)

        fetch_result = await _fetch_batch(config, settings, offset_id=offset_id, batch_size=BATCH_SIZE)

        if fetch_result.found == 0:
            print(f"{C.WARN}  Посты в канале закончились.{C.RST}\n")
            break

        offset_id = fetch_result.last_message_id or 0

        _prompt_vpn_off()

        need = target - len(working)
        check_result = await _check_batch(config, fetch_result.candidates, target_working=need)
        working.extend(check_result.working)

        if fetch_result.last_message_id is None:
            break

    return working


async def run(settings: RunSettings) -> None:
    config = api.Config.from_env()

    if settings.mode == 1:
        working = await _run_paginated(config, settings)
    else:
        _prompt_vpn_on()
        fetch_result = await _fetch_batch(config, settings)
        if fetch_result.found == 0:
            return

        _prompt_vpn_off()
        check_result = await _check_batch(config, fetch_result.candidates, settings.target_working)
        working = check_result.working

        if settings.target_working is not None and len(working) < settings.target_working:
            print(f"{C.WARN}  ⚠ Найдено только {len(working)} из {settings.target_working} — "
                  f"кандидаты закончились.{C.RST}\n")

    if not working:
        print(f"{C.WARN}  Рабочих прокси не найдено. Попробуйте расширить диапазон или увеличить N.{C.RST}")
        return

    print(f"{C.BOLD}── Результат{C.RST}  {C.DIM}(кликните ссылку чтобы добавить прокси в Telegram Desktop){C.RST}\n")
    for proxy in working:
        print(f"  {proxy.tg_link()}\n")

    if config.auto_add_to_telegram:
        await _auto_add_proxies(working)


if __name__ == "__main__":
    settings = prompt_settings()
    asyncio.run(run(settings))
