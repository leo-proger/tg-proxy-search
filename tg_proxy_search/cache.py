from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Proxy

# Moscow time (UTC+3, no DST) — all human-facing timestamps are written in MSK.
MSK = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    return datetime.now(MSK)


@dataclass
class CacheEntry:
    server: str
    port: int
    secret: str
    ok: bool
    checked_at: str  # ISO 8601 with timezone (MSK)

    def age_hours(self) -> float:
        # Parsing is timezone-aware, so age is correct regardless of which
        # timezone the timestamp was stored in (old UTC entries still work).
        ts = datetime.fromisoformat(self.checked_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600


class ProxyCache:
    """
    Caching rules:
    - New proxy                                    → test → store result
    - Working,  age < working_recheck_hours        → return True from cache
    - Working,  age ≥ working_recheck_hours        → re-test (see record())
    - Failed,   age < failed_recheck_hours         → return False from cache
    - Failed,   age ≥ failed_recheck_hours         → re-test (see record())

    Duplicate / re-test resolution — a WORKING status always wins (see record()):
    - new check works                → store as working (priority)
    - new check fails, was working   → keep the old working entry (no downgrade)
    - new check fails, was failing   → confirmed dead → DELETE
    - new check fails, unknown proxy → store as failing
    """

    def __init__(self, path: str, working_recheck_hours: float, failed_recheck_hours: float) -> None:
        self._path = Path(path)
        self._working_recheck_hours = working_recheck_hours
        self._failed_recheck_hours = failed_recheck_hours
        self._entries: dict[str, CacheEntry] = {}

    @staticmethod
    def _key(proxy: Proxy) -> str:
        return f"{proxy.server}:{proxy.port}:{proxy.secret}"

    def load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open() as f:
            raw: dict[str, dict] = json.load(f)
        self._entries = {k: CacheEntry(**v) for k, v in raw.items()}

    def save(self) -> None:
        with self._path.open("w") as f:
            json.dump({k: asdict(v) for k, v in self._entries.items()}, f, indent=2)

    def get(self, proxy: Proxy) -> bool | None:
        """
        True  — cached as working, still within recheck window.
        False — cached as failed, still within recheck window.
        None  — not in cache, or TTL expired → needs (re-)testing.
        """
        entry = self._entries.get(self._key(proxy))
        if entry is None:
            return None
        if entry.ok and entry.age_hours() < self._working_recheck_hours:
            return True
        if not entry.ok and entry.age_hours() < self._failed_recheck_hours:
            return False
        return None  # TTL expired — re-test

    def is_known(self, proxy: Proxy) -> bool:
        """True if the proxy has any entry (even expired). Used to detect rechecks."""
        return self._key(proxy) in self._entries

    def set(self, proxy: Proxy, ok: bool) -> None:
        self._entries[self._key(proxy)] = CacheEntry(
            server=proxy.server,
            port=proxy.port,
            secret=proxy.secret,
            ok=ok,
            checked_at=now_msk().isoformat(),
        )

    def delete(self, proxy: Proxy) -> None:
        self._entries.pop(self._key(proxy), None)

    def record(self, proxy: Proxy, ok: bool) -> None:
        """
        Merge a fresh check result, giving priority to a WORKING status.
        See the class docstring for the full resolution table.
        """
        if ok:
            self.set(proxy, True)          # working always wins, refresh timestamp
            return

        existing = self._entries.get(self._key(proxy))
        if existing is None:
            self.set(proxy, False)         # new proxy that failed → record it
        elif existing.ok:
            return                         # don't downgrade a known-working proxy
        else:
            self.delete(proxy)             # failing recheck of a failing proxy → dead

    def working_proxies(self) -> list[Proxy]:
        """All proxies currently stored as working (any TTL)."""
        return [
            Proxy(server=e.server, port=e.port, secret=e.secret)
            for e in self._entries.values()
            if e.ok
        ]

    def clear_working(self) -> None:
        """Remove all working entries (used before a full recheck)."""
        dead = [k for k, e in self._entries.items() if e.ok]
        for k in dead:
            del self._entries[k]

    @property
    def stats(self) -> tuple[int, int]:
        """Returns (working_count, failed_count) of current entries."""
        working = sum(1 for e in self._entries.values() if e.ok)
        return working, len(self._entries) - working
