from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Proxy:
    server: str
    port: int
    secret: str
    # Исключено из сравнения и хэша: два прокси с одинаковыми данными,
    # но разными датами поста считаются одним прокси.
    posted_at: str | None = field(default=None, compare=False)

    def tg_link(self) -> str:
        return f"tg://proxy?server={self.server}&port={self.port}&secret={self.secret}"

    @staticmethod
    def from_dict(d: dict[str, str | int]) -> Proxy:
        return Proxy(
            server=str(d["server"]),
            port=int(d["port"]),
            secret=str(d["secret"]),
            posted_at=str(d["posted_at"]) if d.get("posted_at") else None,
        )
