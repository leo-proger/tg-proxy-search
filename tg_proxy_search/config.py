from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    """
    Только инфраструктура и тюнинг. Параметры запуска (сколько прокси найти,
    временное окно) выбираются интерактивно в UI.
    """
    api_id: int
    api_hash: str
    tcp_timeout: float = 15.0
    proxy_check_concurrency: int = 8
    # Ограничение на кол-во сообщений канала за один запуск парсинга.
    max_scan_messages: int = 1000
    channel: str = "ProxyMTProto"
    cache_file: str = "proxies.json"
    check_cache_file: str = "proxy_cache.json"
    # Перепроверять рабочий прокси через столько часов (может упасть).
    proxy_working_recheck_hours: float = 48.0
    # Перепроверять нерабочий прокси через столько часов (может восстановиться).
    proxy_failed_recheck_hours: float = 24.0
    auto_add_to_telegram: bool = False

    @staticmethod
    def from_env() -> Config:
        # Публичные ключи Telegram Desktop. Работают без регистрации, но имеют
        # более жёсткие ограничения по частоте запросов, чем личные ключи с my.telegram.org.
        _DEFAULT_API_ID   = 2040
        _DEFAULT_API_HASH = "b18441a1ff607e10a989891a5462e627"
        return Config(
            api_id=int(os.environ.get("API_ID", _DEFAULT_API_ID)),
            api_hash=os.environ.get("API_HASH", _DEFAULT_API_HASH),
            tcp_timeout=float(os.environ.get("TCP_TIMEOUT", "15")),
            proxy_check_concurrency=int(os.environ.get("PROXY_CHECK_CONCURRENCY", "8")),
            max_scan_messages=int(os.environ.get("MAX_SCAN_MESSAGES", "1000")),
            proxy_working_recheck_hours=float(os.environ.get("PROXY_WORKING_RECHECK_HOURS", "48")),
            proxy_failed_recheck_hours=float(os.environ.get("PROXY_FAILED_RECHECK_HOURS", "24")),
            auto_add_to_telegram=os.environ.get("AUTO_ADD_TO_TELEGRAM", "").lower() in ("1", "true", "yes"),
        )
