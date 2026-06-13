"""
Interactive proxy finder.

On start you pick a mode:
  1. Find until N working proxies are collected.
  2. Take all proxies posted in the last X hours.
  3. Both — up to N working proxies, looking only at the last X hours.

Then: fetch with VPN ON → switch VPN OFF → verify from your real IP.
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


# ── Mode selection ────────────────────────────────────────────────────────────

@dataclass
class RunSettings:
    mode: int
    target_working: int | None  # N (modes 1, 3)
    since_hours: float | None   # X (modes 2, 3)


def _ask_int(prompt: str, minimum: int = 1) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
            if value >= minimum:
                return value
        except ValueError:
            pass
        print(f"{C.FAIL}  Enter an integer ≥ {minimum}.{C.RST}")


def _ask_float(prompt: str, minimum: float = 0.0) -> float:
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            value = float(raw)
            if value > minimum:
                return value
        except ValueError:
            pass
        print(f"{C.FAIL}  Enter a number > {minimum}.{C.RST}")


def prompt_settings() -> RunSettings:
    print(f"{C.BOLD}Select mode:{C.RST}")
    print(f"  {C.BOLD}1{C.RST}  Find until N working proxies are collected")
    print(f"  {C.BOLD}2{C.RST}  Take all proxies from the last X hours")
    print(f"  {C.BOLD}3{C.RST}  Both — up to N working, within the last X hours\n")

    while True:
        choice = input("Mode [1/2/3]: ").strip()
        if choice in ("1", "2", "3"):
            mode = int(choice)
            break
        print(f"{C.FAIL}  Type 1, 2 or 3.{C.RST}")

    target_working: int | None = None
    since_hours: float | None = None
    if mode in (1, 3):
        target_working = _ask_int("How many working proxies to find? ")
    if mode in (2, 3):
        since_hours = _ask_float("Look at posts from the last how many hours? ")

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
    print(f"\n{C.BOLD}── Adding proxies to Telegram{C.RST}\n")
    for i, proxy in enumerate(proxies, 1):
        print(f"  [{i}/{len(proxies)}] {proxy.server}:{proxy.port}")
        await loop.run_in_executor(None, _open_url, proxy.tg_link())
        await loop.run_in_executor(None, input, "  Click 'Connect' in Telegram, then press Enter...")
        print()


# ── Phases ────────────────────────────────────────────────────────────────────

async def _run_fetch(config: api.Config, settings: RunSettings) -> api.FetchResult:
    print(f"{C.BOLD}── Step 1: collecting candidates{C.RST}")
    print(f"{C.WARN}  VPN must be ON (Telegram must be accessible){C.RST}")
    if settings.since_hours is not None:
        print(f"{C.DIM}  Reading @{config.channel}, posts from the last {settings.since_hours:g}h{C.RST}\n")
    else:
        print(f"{C.DIM}  Reading @{config.channel}{C.RST}\n")

    def on_progress(event: api.FetchProgress) -> None:
        print(f"\r  Scanned: {event.scanned}  |  found: {event.found}", end="", flush=True)

    result = await api.fetch(config, since_hours=settings.since_hours, on_progress=on_progress)

    print(f"\r  {C.OK}Candidates found: {result.found}{C.RST}  {C.DIM}(scanned {result.scanned} posts){C.RST}")
    if result.limit_reached:
        print(f"{C.WARN}  ⚠ Scan limit reached ({config.max_scan_messages} posts) — "
              f"raise MAX_SCAN_MESSAGES in .env to look further back.{C.RST}")
    if result.found == 0:
        window = f" in the last {settings.since_hours:g}h" if settings.since_hours else ""
        print(f"{C.WARN}  ⚠ No proxy candidates{window}.{C.RST}")
    print()
    return result


async def _run_check(config: api.Config, settings: RunSettings) -> api.CheckResult:
    print(f"{C.BOLD}── Step 2: verifying proxies{C.RST}")
    print(f"{C.WARN}  VPN must be OFF (connections go from your real IP){C.RST}")
    target = settings.target_working
    target_label = str(target) if target is not None else "all"
    print(f"{C.DIM}  Target working: {target_label}  |  timeout: {config.tcp_timeout:g}s{C.RST}\n")

    consecutive_fails = 0
    has_collapsed_line = False

    def on_event(event: api.ProxyChecked) -> None:
        nonlocal consecutive_fails, has_collapsed_line
        cached_tag = f" {C.DIM}(cached){C.RST}" if event.from_cache else ""
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
                    f"\r{C.DIM}  ...{event.checked}/{event.total} tested, all failed{C.RST}   ",
                    end="", flush=True,
                )
                has_collapsed_line = True

    result = await api.check(config, target_working=target, on_event=on_event)

    if has_collapsed_line:
        print()
    print(f"\n  {C.OK}Working: {len(result.working)}{C.RST}  {C.DIM}(checked {result.checked}/{result.total}){C.RST}")

    if target is not None and not result.target_met:
        print(f"{C.WARN}  ⚠ Found only {len(result.working)} of {target} requested — "
              f"candidates exhausted.{C.RST}")
    print()
    return result


# ── Orchestration ─────────────────────────────────────────────────────────────

async def run(settings: RunSettings) -> None:
    config = api.Config.from_env()

    fetch_result = await _run_fetch(config, settings)
    if fetch_result.found == 0:
        return

    print("─" * 55)
    print(f"{C.WARN}Turn OFF VPN, then press Enter to start verification...{C.RST}")
    await asyncio.get_running_loop().run_in_executor(None, input)
    print()

    check_result = await _run_check(config, settings)
    if not check_result.working:
        print(f"{C.WARN}  No working proxies found. Try a wider time window or a larger N.{C.RST}")
        return

    print(f"{C.BOLD}── Result{C.RST}  {C.DIM}(click a link to add the proxy in Telegram Desktop){C.RST}\n")
    for proxy in check_result.working:
        print(f"  {proxy.tg_link()}\n")

    if config.auto_add_to_telegram:
        await _auto_add_proxies(check_result.working)


if __name__ == "__main__":
    settings = prompt_settings()
    asyncio.run(run(settings))
