# tg-proxy-search

CLI-инструмент для поиска и проверки публичных MTProto-прокси из Telegram-канала @ProxyMTProto.

## Запуск

```bash
uv run python main.py        # интерактивный режим (выбор режима, сбор, проверка)
uv run python diagnose.py "tg://proxy?..."  # диагностика одного прокси
```

## Архитектура

Два этапа работы, которые намеренно разделены:

1. **Fetch** (VPN включён) — парсинг сообщений Telegram через Telethon, запись кандидатов в `proxies.json`
2. **Check** (VPN выключен) — проверка прокси с реального IP, результаты кэшируются в `proxy_cache.json`

Разделение намеренное: Telegram-канал доступен только через VPN, а проверять прокси нужно с реального IP пользователя.

## Модули

- `tg_proxy_search/secret.py` — разбор секретов MTProto: hex/base64url/URL-encoded, классификация по маркер-байту (`0xEE` faketls / `0xDD` dd / plain).
- `tg_proxy_search/checker.py` — два пути проверки:
  - `faketls_check` — для `ee`-прокси: отправляет полноценный 517-байтовый tdlib/Chrome-подобный ClientHello с HMAC-SHA256 дайджестом, верифицирует ответный дайджест сервера.
  - `mtproto_check` — для `dd`/plain: Telethon с `ConnectionTcpMTProxyRandomizedIntermediate`.
  - `check_proxy` — диспетчер, выбирает путь по типу секрета.
- `tg_proxy_search/core.py` — оркестрация: `fetch()` и `check()` с кэшем и событиями прогресса.
- `tg_proxy_search/cache.py` — `ProxyCache`: TTL-кэш (working 48ч, failed 24ч), "working wins" при повторной проверке.
- `tg_proxy_search/parser.py` — извлечение прокси из сообщений (кнопки → текст fallback).
- `tg_proxy_search/models.py` — `Proxy` (frozen dataclass, `posted_at` исключён из hash/eq).

## Критично понимать про fake-TLS

Telethon **не умеет** fake-TLS (`ee`-секреты): он срезает `ee`+домен и говорит randomized-intermediate. Настоящий mtg-прокси молчит или закрывает соединение → прокси ложно помечается мёртвым. Поэтому `ee`-прокси идут через `faketls_check`.

Минимальный самодельный ClientHello тоже не работает: mtg требует не-GREASE cipher suite и SNI-совпадение, а DPI в цензурируемых сетях режет hello не похожие на настоящий браузер. ClientHello должен быть 517 байт с Chrome-подобными расширениями.

## Переменные окружения (.env)

| Переменная | Описание |
|---|---|
| `API_ID` | Telegram API ID |
| `API_HASH` | Telegram API Hash |
| `TCP_TIMEOUT` | таймаут проверки в секундах (default 15) |
| `PROXY_CHECK_CONCURRENCY` | параллельность (default 8) |
| `MAX_SCAN_MESSAGES` | лимит сообщений при fetch (default 1000) |
| `PROXY_WORKING_RECHECK_HOURS` | TTL рабочего прокси в кэше (default 48) |
| `PROXY_FAILED_RECHECK_HOURS` | TTL мёртвого прокси в кэше (default 24) |

## Диагностика

`diagnose.py` — запускать на прокси, которые видны рабочими в Telegram, **с выключенным VPN**. Показывает: TCP-коннект, тип секрета, сырые байты ответа, проверку дайджеста. Байпасит кэш.

Сетевые тесты против реальных прокси из агентской среды могут быть недостоверны из-за VPN или сетевых ограничений. Для воспроизводимой автоматической валидации используйте loopback (`127.0.0.1`) с точной серверной логикой mtg. Финальную проверку реального прокси выполняет пользователь с выключенным VPN.

## Тестирование новых handshake-изменений

Если соответствующие временные loopback-скрипты подготовлены в `/tmp`, запускать их так:

```bash
PYTHONPATH=. python /tmp/loopback_test.py   # fake-TLS client vs mock server
PYTHONPATH=. python /tmp/mtg_loopback.py    # новый hello vs mtg-faithful validation
```

Перед проверкой чекера не полагайтесь на сохранённые результаты из `proxy_cache.json`: старые `ok:false` могут отдаваться из кэша. Очищайте кэш только когда это допустимо для текущей задачи.
