from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Proxy

# Московское время (UTC+3, без перехода на летнее). Все метки времени пишутся в МСК.
MSK = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    return datetime.now(MSK)


@dataclass
class CacheEntry:
    server: str
    port: int
    secret: str
    ok: bool
    checked_at: str  # ISO 8601 с таймзоной (МСК)

    def age_hours(self) -> float:
        # Парсинг учитывает таймзону, поэтому возраст корректен независимо от того,
        # в какой таймзоне хранится метка (старые UTC-записи тоже работают).
        ts = datetime.fromisoformat(self.checked_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600


class ProxyCache:
    """
    Правила кэша:
    - Новый прокси                               : тест, сохранение результата
    - Рабочий, возраст < working_recheck_hours   : вернуть True из кэша
    - Рабочий, возраст >= working_recheck_hours  : перепроверить (см. record())
    - Нерабочий, возраст < failed_recheck_hours  : вернуть False из кэша
    - Нерабочий, возраст >= failed_recheck_hours : перепроверить (см. record())

    Приоритет при повторной проверке (РАБОЧИЙ всегда побеждает, см. record()):
    - новая проверка успешна                     : сохранить как рабочий
    - новая провалена, ранее был рабочим         : оставить старую запись (без понижения)
    - новая провалена, ранее был нерабочим       : подтверждён мёртвым, удалить
    - новая провалена, прокси неизвестен         : сохранить как нерабочий
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
        True  : прокси в кэше как рабочий, TTL не истёк.
        False : прокси в кэше как нерабочий, TTL не истёк.
        None  : нет в кэше или TTL истёк, нужна (пере)проверка.
        """
        entry = self._entries.get(self._key(proxy))
        if entry is None:
            return None
        if entry.ok and entry.age_hours() < self._working_recheck_hours:
            return True
        if not entry.ok and entry.age_hours() < self._failed_recheck_hours:
            return False
        return None  # TTL истёк, нужна перепроверка

    def is_known(self, proxy: Proxy) -> bool:
        """True, если прокси есть в кэше (даже с истёкшим TTL)."""
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
        Записывает результат проверки с приоритетом на РАБОЧИЙ статус.
        Полная таблица приоритетов описана в docstring класса.
        """
        if ok:
            self.set(proxy, True)          # рабочий всегда побеждает, обновляем метку времени
            return

        existing = self._entries.get(self._key(proxy))
        if existing is None:
            self.set(proxy, False)         # новый прокси провалил проверку, записываем
        elif existing.ok:
            return                         # не понижаем статус заведомо рабочего прокси
        else:
            self.delete(proxy)             # повторный провал нерабочего прокси, удаляем

    def working_proxies(self) -> list[Proxy]:
        """Все прокси, хранящиеся в кэше как рабочие (TTL не учитывается)."""
        return [
            Proxy(server=e.server, port=e.port, secret=e.secret)
            for e in self._entries.values()
            if e.ok
        ]

    def clear_working(self) -> None:
        """Удаляет все рабочие записи (вызывается перед полной перепроверкой)."""
        dead = [k for k, e in self._entries.items() if e.ok]
        for k in dead:
            del self._entries[k]

    @property
    def stats(self) -> tuple[int, int]:
        """Возвращает (кол-во рабочих, кол-во нерабочих) из текущего кэша."""
        working = sum(1 for e in self._entries.values() if e.ok)
        return working, len(self._entries) - working
