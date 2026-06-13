from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    """
    Infrastructure / tuning only. Run parameters (how many working proxies to
    find, the time window) are chosen interactively in the UI, not here.
    """
    api_id: int
    api_hash: str
    tcp_timeout: float = 15.0
    proxy_check_concurrency: int = 8
    # Safety cap on how many channel messages a single fetch will scan.
    max_scan_messages: int = 1000
    channel: str = "ProxyMTProto"
    cache_file: str = "proxies.json"
    check_cache_file: str = "proxy_cache.json"
    # Re-test a working proxy after this many hours (it may have gone down)
    proxy_working_recheck_hours: float = 48.0
    # Re-test a failed proxy after this many hours (it may have come back)
    proxy_failed_recheck_hours: float = 24.0
    auto_add_to_telegram: bool = False

    @staticmethod
    def from_env() -> Config:
        # Telegram Desktop public credentials — work out of the box but have
        # stricter rate limits than personal API keys from my.telegram.org.
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
