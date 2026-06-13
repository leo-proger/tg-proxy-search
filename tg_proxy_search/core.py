from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from telethon import TelegramClient

from .cache import ProxyCache
from .checker import check_proxy
from .config import Config
from .models import Proxy
from .parser import extract_from_message

# Sorts oldest first; proxies without a parseable date sink to the bottom
# (used with reverse=True so the newest posts end up on top).
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
    from_cache: bool = False


OnFetchProgress = Callable[[FetchProgress], None]
OnCheckEvent = Callable[[ProxyChecked], None]


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass
class FetchResult:
    candidates: list[Proxy] = field(default_factory=list)
    scanned: int = 0
    # True if the scan stopped at the safety cap rather than naturally ending.
    limit_reached: bool = False
    since_hours: float | None = None

    @property
    def found(self) -> int:
        return len(self.candidates)


@dataclass
class CheckResult:
    working: list[Proxy] = field(default_factory=list)
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
    Step 1 (VPN on): read the proxy channel newest → oldest and save candidates.

    - since_hours=None : scan up to config.max_scan_messages messages.
    - since_hours=X    : scan until a post older than X hours is reached
                         (still bounded by config.max_scan_messages).

    Raises RuntimeError if the session is not authorized.
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

        # iter_messages yields newest → oldest (reverse=False).
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

    # Newest posts first; proxies without a date go to the end.
    candidates.sort(key=_posted_sort_key, reverse=True)

    with open(config.cache_file, "w") as f:
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
    Step 2 (VPN off): verify candidates by a real handshake — a fake-TLS
    handshake for ee-secrets, an MTProto connection for dd/plain (see check_proxy).

    - target_working=N    : stop as soon as N working proxies are found.
    - target_working=None : check every candidate.

    Performance: uncached proxies are tested concurrently, bounded by
    config.proxy_check_concurrency.

    Cache behaviour (working has priority — see ProxyCache.record):
    - Fresh cache hit (within TTL)      → returned immediately, not re-tested.
    - Expired, re-test works            → stored as working.
    - Expired working, re-test fails    → kept as working (no downgrade).
    - Expired failing, re-test fails    → confirmed dead → deleted.
    - New proxy (not in cache)          → tested; result stored.
    """
    if candidates is None:
        with open(config.cache_file) as f:
            raw: list[dict[str, str | int]] = json.load(f)
        candidates = [Proxy.from_dict(d) for d in raw]

    total = len(candidates)
    cache = ProxyCache(
        config.check_cache_file,
        config.proxy_working_recheck_hours,
        config.proxy_failed_recheck_hours,
    )
    cache.load()

    asyncio.get_running_loop().set_exception_handler(lambda _l, _c: None)  # suppress Telethon noise

    working: list[Proxy] = []
    checked = 0
    stop = asyncio.Event()

    def target_reached() -> bool:
        return target_working is not None and len(working) >= target_working

    def emit(proxy: Proxy, ok: bool, *, from_cache: bool = False) -> None:
        nonlocal checked
        checked += 1
        if on_event:
            on_event(ProxyChecked(
                proxy=proxy, ok=ok,
                checked=checked, working=len(working),
                total=total, from_cache=from_cache,
            ))

    # ── Phase 1: serve fresh cache hits in order ──────────────────────────────
    to_test: list[Proxy] = []
    for proxy in candidates:
        if target_reached():
            break
        cached_result = cache.get(proxy)
        if cached_result is not None:
            if cached_result:
                working.append(proxy)
            emit(proxy, cached_result, from_cache=True)
        else:
            to_test.append(proxy)

    # ── Phase 2: test concurrently; retry failures at low concurrency ─────────
    # A high-latency proxy can time out when many handshakes compete for
    # bandwidth, so failures get a second, calmer attempt before being trusted.
    async def run_pass(proxies: list[Proxy], concurrency: int, *, defer_failures: bool) -> list[Proxy]:
        semaphore = asyncio.Semaphore(concurrency)
        failures: list[Proxy] = []

        async def test_one(proxy: Proxy) -> None:
            if stop.is_set():
                return
            async with semaphore:
                if stop.is_set():
                    return
                ok = await check_proxy(proxy, config.api_id, config.api_hash, config.tcp_timeout)
                if ok:
                    cache.record(proxy, True)
                    working.append(proxy)
                    emit(proxy, True)
                    if target_reached():
                        stop.set()
                elif defer_failures:
                    failures.append(proxy)  # give it a calmer retry before judging
                else:
                    # Working has priority; a failing recheck never downgrades a
                    # known-working proxy, and a confirmed-dead one is dropped.
                    cache.record(proxy, False)
                    emit(proxy, False)

        await asyncio.gather(*[asyncio.create_task(test_one(p)) for p in proxies], return_exceptions=True)
        return failures

    try:
        if to_test and not target_reached():
            failures = await run_pass(to_test, config.proxy_check_concurrency, defer_failures=True)
            if failures and not stop.is_set():
                retry_concurrency = max(2, config.proxy_check_concurrency // 4)
                await run_pass(failures, retry_concurrency, defer_failures=False)
    finally:
        cache.save()

    result_working = working[:target_working] if target_working is not None else working

    return CheckResult(
        working=result_working,
        target=target_working,
        total=total,
        checked=checked,
    )


async def recheck(
    config: Config,
    *,
    on_event: OnCheckEvent | None = None,
) -> CheckResult:
    """
    Re-verify all proxies that are currently stored as working in the cache,
    regardless of TTL. Does not require a fetch phase (no VPN needed).

    Useful when previously working proxies go down and you want a quick refresh
    without scanning the channel again.
    """
    cache = ProxyCache(
        config.check_cache_file,
        config.proxy_working_recheck_hours,
        config.proxy_failed_recheck_hours,
    )
    cache.load()

    candidates = cache.working_proxies()

    if not candidates:
        return CheckResult()

    # Force-expire all of them so check() actually re-tests instead of
    # returning stale cache hits.
    cache.clear_working()
    cache.save()

    return await check(config, candidates=candidates, on_event=on_event)
