from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from telethon import TelegramClient

from .checker import check_proxy
from .config import Config
from .models import Proxy
from .parser import extract_from_message

# Сортирует по возрастанию даты; прокси без даты уходят в конец
# (используется с reverse=True, чтобы новые посты оказались вверху).
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _posted_sort_key(proxy: Proxy) -> datetime:
    if not proxy.posted_at:
        return _EPOCH
    try:
        return datetime.fromisoformat(proxy.posted_at)
    except ValueError:
        return _EPOCH


# ── Events ────────────────────────────────────────────────────────────────────

@dataclass
class FetchProgress:
    found: int
    scanned: int


@dataclass
class ProxyChecked:
    proxy: Proxy
    ok: bool
    checked: int
    working: int
    total: int
    latency_ms: int | None = None


OnFetchProgress = Callable[[FetchProgress], None]
OnCheckEvent = Callable[[ProxyChecked], None]


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass
class FetchResult:
    candidates: list[Proxy] = field(default_factory=list)
    scanned: int = 0
    # True, если сканирование остановилось из-за лимита, а не дошло до конца.
    limit_reached: bool = False
    since_hours: float | None = None

    @property
    def found(self) -> int:
        return len(self.candidates)


@dataclass
class CheckedProxy:
    proxy: Proxy
    latency_ms: int


@dataclass
class CheckResult:
    working: list[CheckedProxy] = field(default_factory=list)
    target: int | None = None
    total: int = 0
    checked: int = 0

    @property
    def target_met(self) -> bool:
        return self.target is None or len(self.working) >= self.target


# ── API ───────────────────────────────────────────────────────────────────────

async def fetch(
    config: Config,
    *,
    since_hours: float | None = None,
    session_file: str = "telethon",
    on_progress: OnFetchProgress | None = None,
) -> FetchResult:
    """
    Шаг 1 (VPN включён): парсит канал с прокси от новых к старым, сохраняет кандидатов.

    - since_hours=None : сканирует до config.max_scan_messages сообщений.
    - since_hours=X    : сканирует до поста старше X часов
                         (также ограничено config.max_scan_messages).

    Бросает RuntimeError, если сессия не авторизована.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=since_hours)
        if since_hours is not None else None
    )

    async with TelegramClient(session_file, config.api_id, config.api_hash) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Session not authorized. The telethon.session file is missing or expired.")

        candidates: list[Proxy] = []
        seen: set[tuple[str, int, str]] = set()
        scanned = 0
        reached_cutoff = False

        # iter_messages отдаёт от новых к старым (reverse=False).
        async for message in client.iter_messages(
            config.channel, limit=config.max_scan_messages, reverse=False
        ):
            scanned += 1
            mdate: datetime | None = getattr(message, "date", None)
            if cutoff is not None and mdate is not None and mdate < cutoff:
                reached_cutoff = True
                break

            for proxy in extract_from_message(message):
                key = (proxy.server, proxy.port, proxy.secret)
                if key not in seen:
                    seen.add(key)
                    candidates.append(proxy)
                    if on_progress:
                        on_progress(FetchProgress(found=len(candidates), scanned=scanned))

    # Новые посты первыми; прокси без даты идут в конец.
    candidates.sort(key=_posted_sort_key, reverse=True)

    with open(config.candidates_file, "w") as f:
        json.dump([asdict(p) for p in candidates], f, indent=2)

    limit_reached = scanned >= config.max_scan_messages and not reached_cutoff
    return FetchResult(
        candidates=candidates,
        scanned=scanned,
        limit_reached=limit_reached,
        since_hours=since_hours,
    )


async def check(
    config: Config,
    candidates: list[Proxy] | None = None,
    *,
    target_working: int | None = None,
    on_event: OnCheckEvent | None = None,
) -> CheckResult:
    """
    Шаг 2 (VPN выключен): проверяет кандидатов реальным handshake.
    fake-TLS для ee-секретов, MTProto-соединение для dd/plain (см. check_proxy).

    - target_working=N    : остановиться, как только найдено N рабочих прокси.
    - target_working=None : проверить всех кандидатов.

    Производительность: прокси тестируются конкурентно,
    ограничено config.proxy_check_concurrency.
    """
    if candidates is None:
        with open(config.candidates_file) as f:
            raw: list[dict[str, str | int]] = json.load(f)
        candidates = [Proxy.from_dict(d) for d in raw]

    total = len(candidates)

    asyncio.get_running_loop().set_exception_handler(lambda _l, _c: None)  # подавляем шум Telethon

    working: list[CheckedProxy] = []
    checked = 0
    stop = asyncio.Event()

    def target_reached() -> bool:
        return target_working is not None and len(working) >= target_working

    def emit(proxy: Proxy, ok: bool, latency_ms: int | None = None) -> None:
        nonlocal checked
        checked += 1
        if on_event:
            on_event(ProxyChecked(
                proxy=proxy, ok=ok,
                checked=checked, working=len(working),
                total=total,
                latency_ms=latency_ms,
            ))

    # Провалы повторяем при низкой конкурентности.
    # Высоколатентный прокси может истечь по таймауту, когда много handshake-ов
    # одновременно конкурируют за полосу. Провалы получают вторую, более спокойную попытку.
    async def run_pass(proxies: list[Proxy], concurrency: int, *, defer_failures: bool) -> list[Proxy]:
        semaphore = asyncio.Semaphore(concurrency)
        failures: list[Proxy] = []

        async def test_one(proxy: Proxy) -> None:
            if stop.is_set():
                return
            async with semaphore:
                if stop.is_set():
                    return
                latency_ms = await check_proxy(proxy, config.api_id, config.api_hash, config.tcp_timeout)
                if latency_ms is not None:
                    working.append(CheckedProxy(proxy, latency_ms))
                    emit(proxy, True, latency_ms)
                    if target_reached():
                        stop.set()
                elif defer_failures:
                    failures.append(proxy)  # отложить на вторую попытку перед окончательным решением
                else:
                    emit(proxy, False)

        await asyncio.gather(*[asyncio.create_task(test_one(p)) for p in proxies], return_exceptions=True)
        return failures

    if candidates and not target_reached():
        failures = await run_pass(candidates, config.proxy_check_concurrency, defer_failures=True)
        if failures and not stop.is_set():
            retry_concurrency = max(2, config.proxy_check_concurrency // 4)
            await run_pass(failures, retry_concurrency, defer_failures=False)

    result_working = working[:target_working] if target_working is not None else working
    result_working.sort(key=lambda result: result.latency_ms)

    return CheckResult(
        working=result_working,
        target=target_working,
        total=total,
        checked=checked,
    )
